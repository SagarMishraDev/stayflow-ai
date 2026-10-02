"""Conversation persistence for the agent (Phase 6: conversation & memory).

Uses the existing ``conversations`` / ``messages`` tables. Only guest-visible
content is stored: user messages, assistant replies, and a compact record of
tool actions (never hidden chain-of-thought).
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.guest import Guest
from app.models.hotel import Hotel
from app.models.message import Message


def get_or_create_conversation(
    db: Session,
    *,
    hotel_id: int,
    guest_id: int | None,
    channel: str,
    conversation_id: int | None = None,
    conversation_token: str | None = None,
) -> Conversation:
    if conversation_id is not None or conversation_token is not None:
        conversation = None
        if conversation_token:
            conversation = db.scalar(
                select(Conversation).where(
                    Conversation.access_token == conversation_token,
                    Conversation.hotel_id == hotel_id,
                )
            )
        if conversation is None and conversation_id is not None:
            candidate = db.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.hotel_id == hotel_id,
                )
            )

            if candidate is not None:
                if conversation_token:
                    conversation = candidate
                elif guest_id is not None and candidate.guest_id == guest_id:
                    conversation = candidate
        # Public web callers must prove possession of the opaque token before
        # an existing conversation can be continued. A stale/invalid token
        # starts a fresh conversation instead of exposing another transcript.
        if conversation is None or (
            conversation_token and conversation.access_token != conversation_token
        ):
            return create_conversation(db, hotel_id=hotel_id, guest_id=guest_id, channel=channel)
        if conversation_id is not None and conversation.id != conversation_id:
            return create_conversation(db, hotel_id=hotel_id, guest_id=guest_id, channel=channel)
        if guest_id is not None and conversation.guest_id not in (None, guest_id):
            return create_conversation(db, hotel_id=hotel_id, guest_id=guest_id, channel=channel)
        if guest_id is not None and conversation.guest_id is None:
            conversation.guest_id = guest_id
        return conversation

    if guest_id is not None:
        existing = db.scalar(
            select(Conversation)
            .where(
                Conversation.hotel_id == hotel_id,
                Conversation.guest_id == guest_id,
                Conversation.channel == channel,
                Conversation.status == "ACTIVE",
                Conversation.is_active.is_(True),
            )
            .order_by(Conversation.id.desc())
        )
        if existing is not None:
            return existing

    return create_conversation(db, hotel_id=hotel_id, guest_id=guest_id, channel=channel)


def create_conversation(
    db: Session, *, hotel_id: int, guest_id: int | None, channel: str
) -> Conversation:
    hotel = db.get(Hotel, hotel_id)
    if hotel is None:
        raise ValueError(f"Hotel {hotel_id} not found")
    if guest_id is not None:
        guest = db.get(Guest, guest_id)
        if guest is None or guest.hotel_id != hotel_id:
            raise ValueError("Guest not found for this hotel")
    # Anonymous conversations are allowed (guest identified later via tools).
    conversation = Conversation(
        hotel_id=hotel_id,
        guest_id=guest_id,
        channel=channel,
        status="ACTIVE",
        access_token=secrets.token_urlsafe(48),
    )
    db.add(conversation)
    db.flush()
    return conversation


def add_message(
    db: Session,
    conversation_id: int,
    *,
    sender_type: str,
    message: str,
    message_type: str = "TEXT",
) -> Message:
    row = Message(
        conversation_id=conversation_id,
        sender_type=sender_type,
        message=message,
        message_type=message_type,
    )
    db.add(row)
    db.flush()
    return row


def get_history(db: Session, conversation_id: int, *, limit: int = 20) -> list[Message]:
    return list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.desc())
            .limit(limit)
        ).all()
    )[::-1]
