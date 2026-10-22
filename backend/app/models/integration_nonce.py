"""Replay-protection nonces for the integration API (Master Prompt §12).

Each accepted request signature is recorded once. A second delivery with
the same signature (same timestamp + body, e.g. a replayed capture) hits
the unique constraint and is rejected before the agent runs. Rows older
than the timestamp window are pruned opportunistically on each check —
signatures outside the window are rejected on timestamp grounds anyway.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IntegrationNonce(Base):
    __tablename__ = "integration_nonces"

    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotels.id"), nullable=False, index=True)
    signature: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
