"""Ollama provider: talks to a local Ollama server's /api/chat endpoint."""

from __future__ import annotations

from typing import Any

import httpx

from app.agent.providers.base import (
    LLMResponse,
    ProviderContext,
    ProviderError,
    ToolCallRequest,
)


class OllamaProvider:
    """LLM provider backed by Ollama's chat API with native tool calling."""

    name = "ollama"

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout_seconds: int = 120,
        temperature: float = 0.2,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        context: ProviderContext,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Ollama request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(f"Ollama returned invalid JSON: {exc}") from exc

        message = data.get("message") or {}
        content = message.get("content") or ""
        tool_calls: list[ToolCallRequest] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            name = function.get("name")
            if not name:
                continue
            arguments = function.get("arguments") or {}
            if not isinstance(arguments, dict):
                # Some servers return arguments as a JSON string.
                try:
                    import json

                    arguments = json.loads(arguments)
                except (ValueError, TypeError):
                    arguments = {}
            tool_calls.append(ToolCallRequest(name=name, arguments=arguments))

        return LLMResponse(content=content, tool_calls=tool_calls)
