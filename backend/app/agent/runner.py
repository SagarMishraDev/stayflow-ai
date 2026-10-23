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
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import conversation as conversation_store
from app.agent.config import AgentConfig, build_provider
from app.agent.language import (
    ResponseLanguage,
    build_language_instruction,
    resolve_response_language,
)
from app.agent.prompts import build_system_prompt
from app.agent.providers.base import LLMResponse, ProviderContext, ProviderError
from app.agent.relative_dates import resolve_relative_stay
from app.agent.tools.registry import ToolContext, ToolRegistry, build_registry
from app.models.guest import Guest
from app.models.hotel import Hotel
from app.models.room import Room

logger = logging.getLogger(__name__)

# Guest-facing fallback lines, per response language — a provider outage
# must not flip the conversation back to English-only text.
_FALLBACKS: dict[str, dict[ResponseLanguage, str]] = {
    "provider_down": {
        ResponseLanguage.ENGLISH: (
            "I'm having trouble reaching my assistant brain right now. "
            "Please try again in a moment."
        ),
        ResponseLanguage.HINDI: (
            "माफ़ कीजिए, अभी मेरा सिस्टम जवाब नहीं दे पा रहा है। कृपया थोड़ी देर में फिर कोशिश कीजिए।"
        ),
        ResponseLanguage.HINGLISH: (
            "Sorry, abhi mera system jawab nahi de pa raha hai. "
            "Please thodi der mein phir try kijiye."
        ),
    },
    "generic_error": {
        ResponseLanguage.ENGLISH: "Something went wrong on my side. Please try again in a moment.",
        ResponseLanguage.HINDI: "माफ़ कीजिए, मेरी तरफ़ से कुछ गड़बड़ हो गई। कृपया फिर कोशिश कीजिए।",
        ResponseLanguage.HINGLISH: (
            "Sorry, meri taraf se kuch gadbad ho gayi. Please phir try kijiye."
        ),
    },
    "unsure": {
        ResponseLanguage.ENGLISH: "I'm not sure how to help with that. Could you rephrase?",
        ResponseLanguage.HINDI: ("माफ़ कीजिए, मैं समझ नहीं पाया। क्या आप इसे दूसरे शब्दों में बता सकते हैं?"),
        ResponseLanguage.HINGLISH: (
            "Sorry, main samajh nahi paya. Kya aap isse dusre words mein bata sakte hain?"
        ),
    },
    "too_complex": {
        ResponseLanguage.ENGLISH: (
            "I needed a few too many steps for that — could you ask me in a "
            "simpler way, or tell me exactly what you'd like to do?"
        ),
        ResponseLanguage.HINDI: (
            "इसके लिए मुझे कुछ ज़्यादा steps लगे — क्या आप इसे आसान शब्दों में "
            "पूछ सकते हैं, या बता दीजिए कि आपको ठीक क्या चाहिए?"
        ),
        ResponseLanguage.HINGLISH: (
            "Iske liye mujhe kuch zyada steps lage — kya aap isse simpler "
            "words mein pooch sakte hain, ya bata dijiye aapko exactly kya chahiye?"
        ),
    },
}


def _fallback(kind: str, language: ResponseLanguage) -> str:
    return _FALLBACKS[kind][language]


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
    detected_language: str | None = None
    response_language: str | None = None


def _provider_context(
    db: Session,
    hotel_id: int,
    guest_id: int | None = None,
    response_language: str = "english",
) -> ProviderContext:
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
    # "Today" is the hotel-local date: a guest chatting near midnight
    # must get weekend/tomorrow resolution against the hotel's clock,
    # not the server's.
    tz_name = hotel.timezone or "Asia/Kolkata"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("Asia/Kolkata")
        tz_name = "Asia/Kolkata"
    return ProviderContext(
        hotel_id=hotel_id,
        hotel_name=hotel.name,
        currency=hotel.currency or "INR",
        today=datetime.now(tz).date().isoformat(),
        timezone=tz_name,
        room_types=[{"id": r.id, "room_type": r.room_type, "capacity": r.capacity} for r in rooms],
        guest_id=guest_id,
        guest_name=guest_name,
        response_language=response_language,
    )


def _date_resolution_note(message: str, today: date) -> str:
    """Deterministic relative-date resolution for the system prompt.

    When the guest's message carries a relative phrase ("next weekend",
    "kal", "agle Shukravar"), the resolver — not the LLM — computes the
    exact dates against the hotel-local today, and the note pins them
    for this turn so every provider resolves the phrase identically.
    """
    stay = resolve_relative_stay(message, today)
    if stay is None:
        return ""
    return (
        "\n\nDETERMINISTIC DATE RESOLUTION for the guest's latest message: "
        f"the relative date phrase resolves to check-in {stay.check_in.isoformat()} "
        f"({stay.words().split(' to ')[0]}) and check-out "
        f"{stay.check_out.isoformat()} ({stay.words().split(' to ')[1]}). "
        "Use these exact dates (pass them to tools as ISO dates) and restate "
        "them to the guest in words before asking for confirmation."
    )


def _retrieved_knowledge_note(db: Session, ctx: ToolContext, message: str) -> str:
    """Deterministic knowledge pre-retrieval for LLM-backed providers.

    Whether the knowledge tools get called is otherwise the model's
    choice — and live, Mercury repeatedly answered the Hindi pool
    question ("स्विमिंग पूल का समय क्या है?") without calling them, so
    the grounded Serenity Spa plunge-pool chunk never reached
    generation and the reply guessed, transliterated the name into
    nonsense, or dropped it entirely. Retrieval itself is deterministic
    and hotel-isolated, so the runner runs it for every guest turn and
    injects whatever matches into the system prompt — the same results,
    under the same semantics, the tools themselves return (FAQ
    word-overlap; knowledge cosine > 0 after query expansion). Nothing
    is injected when nothing matches, so greetings and booking slot
    replies carry no extra noise. A retrieval failure must never break
    the chat: log it and continue without the note.
    """
    # Deferred import, mirroring build_registry: the tool modules import
    # the registry, which the runner already depends on.
    from app.agent.tools.hotel_tools import SearchFaqArgs, search_faq
    from app.agent.tools.knowledge_tools import (
        SearchHotelKnowledgeArgs,
        search_hotel_knowledge,
    )

    try:
        faq = search_faq(
            db, ctx, SearchFaqArgs(hotel_id=ctx.hotel_id, query=message, limit=3)
        )
        knowledge = search_hotel_knowledge(
            db, ctx, SearchHotelKnowledgeArgs(query=message, top_k=3)
        )
    except Exception:  # noqa: BLE001 - retrieval must never break the chat
        logger.exception("Knowledge pre-retrieval failed; continuing without it")
        return ""

    lines: list[str] = []
    for item in faq.get("results", []):
        lines.append(f"- FAQ — Q: {item['question']} A: {item['answer']}")
    for item in knowledge.get("results", []):
        lines.append(f'- From "{item["title"]}": {item["content"]}')
    if not lines:
        return ""
    return (
        "\n\nRETRIEVED HOTEL KNOWLEDGE for the guest's latest message — "
        "passages from THIS hotel's own FAQ and knowledge base, retrieved "
        "for you because they match the guest's question:\n"
        + "\n".join(lines)
        + "\nAnswer the guest's question from this material when it covers "
        "the topic. Keep facility and place names in their original English "
        "spelling in every language — never transliterate or translate a "
        "proper noun. If the material does not cover what the guest asked, "
        "say so honestly instead of inventing details."
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

    # Resolve this turn's response language BEFORE the new message joins
    # the history: explicit request > detection of the latest message >
    # most recent classifiable guest message > stored preference.
    prior_guest_texts = [
        row.message
        for row in conversation_store.get_history(db, conversation.id, limit=50)
        if row.sender_type == "guest" and row.message_type == "TEXT"
    ]
    response_language, detection = resolve_response_language(
        text, prior_guest_texts, conversation.preferred_language
    )
    if detection.response_language is not None:
        # The guest wrote in a classifiable language (or asked for one):
        # it becomes the conversation's preference from this turn on.
        conversation.preferred_language = detection.response_language.value
        db.commit()

    conversation_store.add_message(db, conversation.id, sender_type="guest", message=text)
    db.commit()

    provider_context = _provider_context(
        db, hotel_id, guest_id=conversation.guest_id, response_language=response_language.value
    )
    tool_ctx = ToolContext(
        hotel_id=hotel_id,
        conversation_id=conversation.id,
        guest_id=conversation.guest_id,
        channel=channel,
    )

    # Real-LLM providers get two deterministic assists the mock does not
    # need: knowledge pre-retrieval (below) and the empty-completion
    # retry in the loop. The mock is deterministic and routes knowledge
    # itself, so its behaviour is deliberately untouched.
    llm_backed = getattr(provider, "name", "") != "mock"
    knowledge_note = (
        _retrieved_knowledge_note(db, tool_ctx, text) if llm_backed else ""
    )

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": build_system_prompt(provider_context)
            + _date_resolution_note(text, date.fromisoformat(provider_context.today))
            + knowledge_note
            + "\n\n"
            + build_language_instruction(response_language),
        }
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
                reply = _fallback("provider_down", response_language)
                break
            except Exception:  # noqa: BLE001 - never crash the chat on provider bugs
                logger.exception("LLM provider raised unexpectedly")
                degraded = True
                reply = _fallback("generic_error", response_language)
                break

            if llm_backed and not llm.wants_tools and not llm.content.strip():
                # A final answer with no text and no tool calls is an
                # empty completion, not evidence the guest was unclear:
                # Mercury intermittently returns one for perfectly
                # ordinary messages (observed live on Hindi booking and
                # FAQ turns), and the guest would otherwise be told "I
                # didn't understand" for a message the model simply
                # failed to answer. Re-ask once; only a second empty
                # completion earns the "unsure" fallback below.
                logger.warning(
                    "LLM returned an empty final answer (iteration %d); retrying once",
                    iteration,
                )
                try:
                    llm = provider.chat(messages, tool_defs, provider_context)
                except ProviderError:
                    logger.exception("LLM provider failed on empty-answer retry")
                    degraded = True
                    reply = _fallback("provider_down", response_language)
                    break
                except Exception:  # noqa: BLE001 - never crash the chat on provider bugs
                    logger.exception("LLM provider raised unexpectedly on empty-answer retry")
                    degraded = True
                    reply = _fallback("generic_error", response_language)
                    break

            if not llm.wants_tools:
                reply = llm.content.strip() or _fallback("unsure", response_language)
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
            reply = _fallback("too_complex", response_language)
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
        detected_language=detection.detected.value,
        response_language=response_language.value,
    )
