from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Guest(Base):
    __tablename__ = "guests"
    __table_args__ = (
        # A messaging-channel identity is unique per hotel so repeat
        # webhooks resolve to the same guest instead of creating dupes.
        UniqueConstraint("hotel_id", "telegram_chat_id", name="uq_guests_hotel_telegram_chat_id"),
        UniqueConstraint("hotel_id", "whatsapp_number", name="uq_guests_hotel_whatsapp_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    phone: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    nationality: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --- Messaging channel identifiers (Prompt-1 sections 4-5) --------------
    telegram_chat_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    whatsapp_number: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    preferences: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
