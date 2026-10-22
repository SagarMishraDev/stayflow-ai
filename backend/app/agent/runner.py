"""The agent runner: Understand -> Decide -> Tool -> Respond.

One ``run_chat`` call processes a single guest message:

1. Load (or create) the conversation and persist the guest message.
2. Build the provider context (hotel facts) and message history.
3. Loop: ask the LLM; execute any requested tools through the validated
   registry; feed results back. Stop at a final answer or ``max_iterations``.
4. Persist the assistant reply and return it with the tool trace.

Safety properties:

- The LLM never touches the database directly; only registered tools do.
- Tool arguments are validated with pydantic before execution.
- Unknown tools and invalid arguments become error messages *to the LLM*,
  not crashes.
- Provider failures degrade to a graceful guest-facing message.
- Loops are bounded by ``max_iterations``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import conversation as conversation_store
from app.agent.config import AgentConfig, build_provider
from app.agent.prompts import build_system_prompt
from app.agent.providers.base import LLMResponse, ProviderContext, ProviderError
from app.agent.tools.registry import ToolContext, ToolRegistry, build_registry
from app.models.guest import Guest
from app.models.hotel import Hotel
from app.models.room import Room

logger = logging.getLogger(__name__)

# Hard ceiling on agent loop iterations, independent of per-request config.
# ``AgentConfig.max_iterations`` may lower the cap for a call but never raise
# it above this constant, so a misconfigured caller cannot spin the loop.
MAX_TOOL_ROUNDS = 8


@dataclass
class ToolTraceEntry:
    tool: str
    arguments: dict[str, Any]
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class ChatResult:
    reply: str
    conversation_id: int
    iterations: int
    tool_trace: list[ToolTraceEntry] = field(default_factory=list)
    degraded: bool = False


def _provider_context(db: Session, hotel_id: int, guest_id: int | None = None) -> ProviderContext:
    hotel = db.get(Hotel, hotel_id)
    if hotel is None:
        raise ValueError(f"Hotel {hotel_id} not found")
    rooms = db.scalars(
        select(Room).where(Room.hotel_id == hotel_id, Room.is_active.is_(True))
    ).all()
    guest_name: str | None = None
    if guest_id is not None:
        guest = db.get(Guest, guest_id)
        if guest is not None and guest.hotel_id == hotel_id:
            guest_name = guest.name
    return ProviderContext(
        hotel_id=hotel_id,
        hotel_name=hotel.name,
        currency=hotel.currency or "INR",
        today=date.today().isoformat(),
        room_types=[{"id": r.id, "room_type": r.room_type, "capacity": r.capacity} for r in rooms],
        guest_id=guest_id,
        guest_name=guest_name,
    )


def _history_messages(db: Session, conversation_id: int, limit: int) -> list[dict[str, Any]]:
    """Rebuild OpenAI-style history, including past tool calls/results."""
    messages: list[dict[str, Any]] = []
    pending_calls: list[dict[str, Any]] = []

    def flush_calls() -> None:
        if pending_calls:
            messages.append(
                {"role": "assistant", "content": "", "tool_calls": pending_calls.copy()}
            )
            pending_calls.clear()

    for row in conversation_store.get_history(db, conversation_id, limit=limit):
        if row.sender_type == "guest":
            flush_calls()
            messages.append({"role": "user", "content": row.message})
        elif row.message_type == "TOOL_CALL":
            try:
                payload = json.loads(row.message)
                pending_calls.append({"name": payload["tool"], "arguments": payload["arguments"]})
            except (ValueError, KeyError, TypeError):
                continue
        elif row.message_type == "TOOL_RESULT":
            flush_calls()
            try:
                payload = json.loads(row.message)
                messages.append(
                    {
                        "role": "tool",
                        "name": payload["tool"],
                        "content": payload["content"],
                    }
                )
            except (ValueError, KeyError, TypeError):
                continue
        elif row.sender_type == "agent":
            flush_calls()
            messages.append({"role": "assistant", "content": row.message})
    flush_calls()
    return messages


def run_chat(
    db: Session,
    *,
    hotel_id: int,
    message: str,
    conversation_id: int | None = None,
    guest_id: int | None = None,
    channel: str = "web",
    config: AgentConfig | None = None,
    provider=None,
    registry: ToolRegistry | None = None,
    script: list[dict[str, Any]] | None = None,
) -> ChatResult:
    """Process one guest message and return the agent's reply."""
    config = config or AgentConfig()
    provider = provider or build_provider(config, script=script)
    registry = registry or build_registry()

    text = (message or "").strip()
    if not text:
        raise ValueError("message must not be empty")
    if len(text) > 4000:
        raise ValueError("message is too long (max 4000 characters)")

    conversation = conversation_store.get_or_create_conversation(
        db,
        hotel_id=hotel_id,
        guest_id=guest_id,
        channel=channel,
        conversation_id=conversation_id,
    )
    db.commit()

    # If the guest identified themselves mid-conversation, adopt them.
    if guest_id is not None and conversation.guest_id != guest_id:
        conversation.guest_id = guest_id
        db.commit()

    conversation_store.add_message(db, conversation.id, sender_type="guest", message=text)
    db.commit()

    provider_context = _provider_context(db, hotel_id, guest_id=conversation.guest_id)
    tool_ctx = ToolContext(
        hotel_id=hotel_id,
        conversation_id=conversation.id,
        guest_id=conversation.guest_id,
        channel=channel,
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(provider_context)}
    ]
    messages.extend(_history_messages(db, conversation.id, config.history_limit))
    tool_defs = registry.definitions()

    trace: list[ToolTraceEntry] = []
    reply = ""
    degraded = False
    iterations = 0

    # The iteration cap is enforced twice: per-call config, clamped by the
    # hard MAX_TOOL_ROUNDS ceiling above.
    iterations_cap = max(1, min(config.max_iterations, MAX_TOOL_ROUNDS))

    try:
        for iteration in range(1, iterations_cap + 1):
            iterations = iteration
            try:
                llm: LLMResponse = provider.chat(messages, tool_defs, provider_context)
            except ProviderError:
                logger.exception("LLM provider failed")
                degraded = True
                reply = (
                    "I'm having trouble reaching my assistant brain right now. "
                    "Please try again in a moment."
                )
                break
            except Exception:  # noqa: BLE001 - never crash the chat on provider bugs
                logger.exception("LLM provider raised unexpectedly")
                degraded = True
                reply = "Something went wrong on my side. Please try again in a moment."
                break

            if not llm.wants_tools:
                reply = llm.content.strip() or (
                    "I'm not sure how to help with that. Could you rephrase?"
                )
                messages.append({"role": "assistant", "content": reply})
                break

            # Execute the requested tools and feed results back.
            assistant_turn: dict[str, Any] = {
                "role": "assistant",
                "content": llm.content or "",
                "tool_calls": [{"name": c.name, "arguments": c.arguments} for c in llm.tool_calls],
            }
            messages.append(assistant_turn)

            for call in llm.tool_calls:
                result = registry.execute(call.name, call.arguments, db, tool_ctx)
                entry = ToolTraceEntry(
                    tool=call.name,
                    arguments=call.arguments,
                    ok=result.ok,
                    result=result.data,
                    error=result.error,
                )
                trace.append(entry)
                conversation_store.add_message(
                    db,
                    conversation.id,
                    sender_type="agent",
                    message=json.dumps({"tool": call.name, "arguments": call.arguments}),
                    message_type="TOOL_CALL",
                )
                tool_content = (
                    json.dumps(result.data, default=str) if result.ok else f"ERROR: {result.error}"
                )
                conversation_store.add_message(
                    db,
                    conversation.id,
                    sender_type="agent",
                    message=json.dumps({"tool": call.name, "content": tool_content}),
                    message_type="TOOL_RESULT",
                )
                messages.append(
                    {
                        "role": "tool",
                        "name": call.name,
                        "content": tool_content,
                    }
                )
            db.commit()
        else:
            # max_iterations exhausted without a final answer.
            degraded = True
            reply = (
                "I needed a few too many steps for that — could you ask me in a "
                "simpler way, or tell me exactly what you'd like to do?"
            )
    finally:
        if reply:
            conversation_store.add_message(db, conversation.id, sender_type="agent", message=reply)
            db.commit()

    return ChatResult(
        reply=reply,
        conversation_id=conversation.id,
        iterations=iterations,
        tool_trace=trace,
        degraded=degraded,
    )
