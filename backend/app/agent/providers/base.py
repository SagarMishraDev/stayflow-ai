"""LLM provider abstraction.

The agent never talks to an LLM vendor directly. Every provider implements
:class:`LLMProvider`, so the runner can work with Ollama in production and a
deterministic mock in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCallRequest:
    """A single tool call requested by the LLM."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """What the provider returned for one turn."""

    content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return len(self.tool_calls) > 0


class ProviderError(Exception):
    """The LLM provider failed (network, timeout, bad response)."""


@dataclass
class ProviderContext:
    """Hotel-specific facts the runner injects for the provider."""

    hotel_id: int
    hotel_name: str
    currency: str
    today: str  # ISO date, hotel-local
    room_types: list[dict[str, Any]] = field(default_factory=list)
    guest_id: int | None = None
    guest_name: str | None = None


class LLMProvider(Protocol):
    """Interface every LLM provider must implement."""

    name: str

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        context: ProviderContext,
    ) -> LLMResponse:
        """Run one LLM turn.

        ``messages`` are OpenAI-style ``{"role": ..., "content": ...}`` dicts.
        ``tools`` are JSON-schema tool definitions (OpenAI function format).
        Must raise :class:`ProviderError` on failure, never return None.
        """
        ...
