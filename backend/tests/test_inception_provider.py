"""Inception Labs Mercury provider: response parsing, errors, retries.

All HTTP is mocked (no API key exists in this sandbox); live calls against
api.inceptionlabs.ai remain unverified.
"""

import time

import httpx
import pytest

from app.agent.config import AgentConfig, build_provider
from app.agent.providers.base import ProviderContext, ProviderError
from app.agent.providers.inception import InceptionProvider
from app.agent.providers.mock import MockProvider
from app.core.config import Settings


def _ctx() -> ProviderContext:
    return ProviderContext(hotel_id=1, hotel_name="Test Hotel", currency="INR", today="2026-09-29")


def _provider(**kw) -> InceptionProvider:
    return InceptionProvider(api_key="test-key", **kw)


def _ok_response(**message) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", **message}, "finish_reason": "stop"}]},
    )


def _install(monkeypatch, responses):
    """Replace httpx.post with a fake serving the given responses/exceptions."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def test_normal_text_reply(monkeypatch):
    calls = _install(monkeypatch, [_ok_response(content="Hello, guest!")])
    resp = _provider().chat([{"role": "user", "content": "hi"}], [], _ctx())
    assert resp.content == "Hello, guest!"
    assert resp.tool_calls == []
    assert not resp.wants_tools
    url, kwargs = calls[0]
    assert url == "https://api.inceptionlabs.ai/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert kwargs["json"]["model"] == "mercury-2.5"
    # The API key must never appear in the URL or body.
    assert "test-key" not in url
    assert "test-key" not in str(kwargs["json"])


def test_single_tool_call(monkeypatch):
    _install(
        monkeypatch,
        [
            _ok_response(
                content="",
                tool_calls=[
                    {
                        "id": "call_0",
                        "type": "function",
                        "function": {
                            "name": "check_room_availability",
                            "arguments": '{"hotel_id": 1, "room_id": 3}',
                        },
                    }
                ],
            )
        ],
    )
    resp = _provider().chat([{"role": "user", "content": "available?"}], [{"name": "x"}], _ctx())
    assert resp.wants_tools
    assert len(resp.tool_calls) == 1
    call = resp.tool_calls[0]
    assert call.name == "check_room_availability"
    assert call.arguments == {"hotel_id": 1, "room_id": 3}


def test_multiple_tool_calls_in_order(monkeypatch):
    _install(
        monkeypatch,
        [
            _ok_response(
                content="",
                tool_calls=[
                    {
                        "id": "a",
                        "type": "function",
                        "function": {"name": "list_rooms", "arguments": "{}"},
                    },
                    {
                        "id": "b",
                        "type": "function",
                        # Some servers send arguments as an object already.
                        "function": {
                            "name": "get_menu",
                            "arguments": {"hotel_id": 1},
                        },
                    },
                ],
            )
        ],
    )
    resp = _provider().chat([], [], _ctx())
    assert [c.name for c in resp.tool_calls] == ["list_rooms", "get_menu"]
    assert resp.tool_calls[1].arguments == {"hotel_id": 1}


def test_malformed_tool_arguments_raise_provider_error(monkeypatch):
    _install(
        monkeypatch,
        [
            _ok_response(
                content="",
                tool_calls=[
                    {
                        "id": "a",
                        "type": "function",
                        "function": {"name": "x", "arguments": "{not valid json"},
                    }
                ],
            )
        ],
    )
    with pytest.raises(ProviderError, match="malformed tool arguments"):
        _provider().chat([], [], _ctx())


def test_non_object_tool_arguments_raise_provider_error(monkeypatch):
    _install(
        monkeypatch,
        [
            _ok_response(
                content="",
                tool_calls=[
                    {
                        "id": "a",
                        "type": "function",
                        "function": {"name": "x", "arguments": "[1, 2]"},
                    }
                ],
            )
        ],
    )
    with pytest.raises(ProviderError, match="malformed tool arguments"):
        _provider().chat([], [], _ctx())


def test_401_raises_provider_error(monkeypatch):
    calls = _install(monkeypatch, [httpx.Response(401, json={"error": "bad key"})])
    with pytest.raises(ProviderError, match="authentication failed"):
        _provider().chat([], [], _ctx())
    assert len(calls) == 1  # auth errors are not retried


def test_403_raises_provider_error(monkeypatch):
    _install(monkeypatch, [httpx.Response(403, json={"error": "forbidden"})])
    with pytest.raises(ProviderError, match="authentication failed"):
        _provider().chat([], [], _ctx())


def test_400_raises_without_retry(monkeypatch):
    calls = _install(monkeypatch, [httpx.Response(400, json={"error": "bad request"})])
    with pytest.raises(ProviderError, match="HTTP 400"):
        _provider().chat([], [], _ctx())
    assert len(calls) == 1


def test_timeout_raises_provider_error(monkeypatch):
    _install(monkeypatch, [httpx.TimeoutException("timed out")])
    with pytest.raises(ProviderError, match="timed out"):
        _provider().chat([], [], _ctx())


def test_connection_error_raises_provider_error(monkeypatch):
    _install(monkeypatch, [httpx.ConnectError("refused")])
    with pytest.raises(ProviderError):
        _provider().chat([], [], _ctx())


def test_retry_on_429_then_success(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)  # keep the suite fast
    calls = _install(
        monkeypatch,
        [
            httpx.Response(429, json={"error": "rate limited"}),
            _ok_response(content="recovered"),
        ],
    )
    resp = _provider(max_retries=2).chat([], [], _ctx())
    assert resp.content == "recovered"
    assert len(calls) == 2


def test_5xx_retries_then_gives_up(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)  # keep the suite fast
    calls = _install(
        monkeypatch,
        [
            httpx.Response(503, json={"error": "down"}),
            httpx.Response(503, json={"error": "down"}),
        ],
    )
    with pytest.raises(ProviderError, match="after 2 attempts"):
        _provider(max_retries=1).chat([], [], _ctx())
    assert len(calls) == 2


def test_invalid_json_raises_provider_error(monkeypatch):
    _install(monkeypatch, [httpx.Response(200, content=b"not json")])
    with pytest.raises(ProviderError, match="invalid JSON"):
        _provider().chat([], [], _ctx())


def test_missing_choices_raises_provider_error(monkeypatch):
    _install(monkeypatch, [httpx.Response(200, json={"choices": []})])
    with pytest.raises(ProviderError, match="no choices"):
        _provider().chat([], [], _ctx())


def test_missing_api_key_rejected():
    with pytest.raises(ValueError, match="API key"):
        InceptionProvider(api_key="")
    with pytest.raises(ValueError, match="INCEPTION_API_KEY"):
        build_provider(AgentConfig(provider_name="inception", inception_api_key=None))


def test_build_provider_inception(monkeypatch):
    config = AgentConfig(provider_name="inception", inception_api_key="k")
    provider = build_provider(config)
    assert isinstance(provider, InceptionProvider)
    assert provider.model == "mercury-2.5"
    assert provider.base_url == "https://api.inceptionlabs.ai/v1"


def test_from_settings_llm_provider_takes_precedence(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "inception")
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    monkeypatch.setenv("INCEPTION_API_KEY", "k")
    settings = Settings(database_url="postgresql+psycopg://localhost:5432/x")
    config = AgentConfig.from_settings(settings)
    assert config.provider_name == "inception"
    assert isinstance(build_provider(config), InceptionProvider)


def test_from_settings_falls_back_to_agent_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    settings = Settings(database_url="postgresql+psycopg://localhost:5432/x")
    config = AgentConfig.from_settings(settings)
    assert config.provider_name == "mock"
    assert isinstance(build_provider(config), MockProvider)


def test_runner_message_translation_to_openai_format(monkeypatch):
    """The runner's internal tool-call format is translated on the wire."""
    calls = _install(monkeypatch, [_ok_response(content="ok")])
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "book"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"name": "preview_booking", "arguments": {"hotel_id": 1}}],
        },
        {"role": "tool", "name": "preview_booking", "content": '{"draft_id": 7}'},
    ]
    _provider().chat(messages, [], _ctx())
    sent = calls[0][1]["json"]["messages"]
    assistant_msg = sent[2]
    assert assistant_msg["tool_calls"][0]["type"] == "function"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "preview_booking"
    assert assistant_msg["tool_calls"][0]["function"]["arguments"] == '{"hotel_id": 1}'
    tool_msg = sent[3]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == assistant_msg["tool_calls"][0]["id"]
