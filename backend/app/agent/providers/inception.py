"""Inception Labs Mercury provider.

Talks to Mercury's OpenAI-compatible chat-completions API::

    POST {base_url}/chat/completions
    {"model": "mercury-2.5", "messages": [...], "tools": [...]}

The default base URL (``https://api.inceptionlabs.ai/v1``) follows Inception
Labs' documented OpenAI-compatible endpoint shape, but it is configurable
because the exact host cannot be live-verified from this sandbox (no API key
is available here). The API key is sent only as a Bearer token and is never
logged.

Supports plain text replies plus OpenAI-style ``tool_calls`` (single and
parallel). Every failure mode surfaces as :class:`ProviderError` — raw
``httpx`` exceptions never escape.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.agent.providers.base import (
    LLMResponse,
    ProviderContext,
    ProviderError,
    ToolCallRequest,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.inceptionlabs.ai/v1"
DEFAULT_MODEL = "mercury-2.5"

# Exponential backoff between retries (seconds): 1, 2, 4, ... capped at 8s.
# ``time.sleep`` is module-referenced so tests can monkeypatch it to keep
# retry tests instant.
_RETRY_BACKOFF_BASE = 1.0
_RETRY_BACKOFF_CAP = 8.0


def _retry_delay_seconds(failed_attempt: int) -> float:
    return min(_RETRY_BACKOFF_BASE * (2 ** max(0, failed_attempt - 1)), _RETRY_BACKOFF_CAP)


def _is_retryable(status_code: int) -> bool:
    """Retry on 429 (rate limited) and 5xx (transient server errors) only."""
    return status_code == 429 or 500 <= status_code < 600


def _parse_tool_arguments(tool_name: str, raw: Any) -> dict[str, Any]:
    """Normalize OpenAI-style tool arguments to a dict.

    OpenAI-compatible servers usually send ``arguments`` as a JSON string,
    but some send an object directly. Anything else is a malformed provider
    response.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise ProviderError(
                f"Inception returned malformed tool arguments for '{tool_name}': not valid JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderError(
                f"Inception returned malformed tool arguments for '{tool_name}': "
                "expected a JSON object"
            )
        return parsed
    raise ProviderError(
        f"Inception returned malformed tool arguments for '{tool_name}': "
        f"unexpected type {type(raw).__name__}"
    )


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the runner's internal message format to OpenAI's wire format.

    The runner records assistant tool calls as ``{"name", "arguments"}`` and
    tool results as ``{"role": "tool", "name", "content"}``; OpenAI expects
    ``function``-style calls with ids and ``tool_call_id`` references.
    """
    out: list[dict[str, Any]] = []
    pending_ids: list[str] = []  # ids of the most recent assistant tool-call block
    call_counter = 0
    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            pending_ids = []
            openai_calls = []
            for call in msg["tool_calls"]:
                call_id = f"call_{call_counter}"
                call_counter += 1
                pending_ids.append(call_id)
                openai_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": call.get("name"),
                            "arguments": json.dumps(call.get("arguments") or {}),
                        },
                    }
                )
            out.append(
                {
                    "role": "assistant",
                    "content": msg.get("content") or None,
                    "tool_calls": openai_calls,
                }
            )
        elif role == "tool":
            call_id = pending_ids.pop(0) if pending_ids else f"call_{call_counter}"
            call_counter += 1
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": str(msg.get("content", "")),
                }
            )
        else:
            out.append({"role": role, "content": msg.get("content", "")})
    return out


def _parse_response(data: Any) -> LLMResponse:
    if not isinstance(data, dict):
        raise ProviderError("Inception returned a malformed response (not a JSON object)")
    choices = data.get("choices")
    if not choices:
        raise ProviderError("Inception returned no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ProviderError("Inception returned a malformed choice (not a JSON object)")
    message = first.get("message") or {}
    content = message.get("content") or ""
    if not isinstance(content, str):
        content = ""
    tool_calls: list[ToolCallRequest] = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        name = function.get("name")
        if not name:
            continue
        tool_calls.append(
            ToolCallRequest(
                name=name,
                arguments=_parse_tool_arguments(name, function.get("arguments")),
            )
        )
    return LLMResponse(content=content, tool_calls=tool_calls)


class InceptionProvider:
    """LLM provider for Inception Labs Mercury (OpenAI-compatible API)."""

    name = "inception"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: int = 120,
        temperature: float = 0.2,
        max_retries: int = 2,
    ) -> None:
        if not api_key:
            raise ValueError("InceptionProvider requires an API key (set INCEPTION_API_KEY)")
        # Stored privately; never include in logs or error messages.
        self._api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_retries = max(0, max_retries)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        context: ProviderContext,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _to_openai_messages(messages),
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
        data = self._post(payload)
        return _parse_response(data)

    def _post(self, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                response = httpx.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    f"Inception request timed out after {self.timeout_seconds}s"
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"Inception request failed: {exc}") from exc

            if response.status_code in (401, 403):
                raise ProviderError(
                    f"Inception authentication failed (HTTP {response.status_code}); "
                    "check INCEPTION_API_KEY"
                )
            if _is_retryable(response.status_code):
                if attempt < attempts:
                    delay = _retry_delay_seconds(attempt)
                    logger.warning(
                        "Inception returned HTTP %s; retrying in %.1fs (%d/%d)",
                        response.status_code,
                        delay,
                        attempt,
                        attempts - 1,
                    )
                    time.sleep(delay)
                    continue
                raise ProviderError(
                    f"Inception request failed with HTTP {response.status_code} "
                    f"after {attempts} attempts"
                )
            if response.status_code >= 400:
                raise ProviderError(f"Inception request failed with HTTP {response.status_code}")
            try:
                return response.json()
            except ValueError as exc:
                raise ProviderError(f"Inception returned invalid JSON: {exc}") from exc
        # Unreachable: the loop always returns or raises.
        raise ProviderError("Inception request failed")
