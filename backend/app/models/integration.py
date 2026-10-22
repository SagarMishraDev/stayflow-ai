"""Persistence for the server-to-server integration API (Master Prompt §12).

Two hotel-scoped tables:

- ``integration_idempotency_keys`` — one row per (hotel, Idempotency-Key).
  The first delivery stores its response; a duplicate delivery with the
  same key returns the stored response without re-running the agent or
  duplicating conversation messages.
- ``integration_request_logs`` — a minimal audit trail for integration
  calls: hotel, outcome, and ids only. No secrets, no signatures, and no
  guest message content (PII) are ever written here.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IntegrationIdempotencyKey(Base):
    __tablename__ = "integration_idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "hotel_id", "idempotency_key", name="uq_integration_idempotency_hotel_key"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class IntegrationRequestLog(Base):
    __tablename__ = "integration_request_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"), nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    webhook_delivered: Mapped[bool | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
