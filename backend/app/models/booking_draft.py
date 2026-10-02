from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

DRAFT_STATUS_PENDING = "PENDING"
DRAFT_STATUS_CONFIRMED = "CONFIRMED"
DRAFT_STATUS_EXPIRED = "EXPIRED"


class BookingDraft(Base):
    """A validated, priced, not-yet-confirmed booking held for guest approval.

    Created by ``preview_booking`` (via ``booking_service.create_booking_draft``)
    and consumed exactly once by ``create_booking`` (via
    ``booking_service.confirm_booking_draft``). The draft pins the exact
    booking parameters plus the backend-computed total price and an expiry;
    availability and pricing are re-validated at confirm time because both can
    change while the draft is pending.
    """

    __tablename__ = "booking_drafts"
    # Matches ix_booking_drafts_hotel_status created by migration 99f111734fcd
    # so that `alembic check` (metadata vs database) stays green.
    __table_args__ = (Index("ix_booking_drafts_hotel_status", "hotel_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id"),
        nullable=False,
    )

    guest_id: Mapped[int] = mapped_column(
        ForeignKey("guests.id"),
        nullable=False,
    )

    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id"),
        nullable=False,
    )

    check_in: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    check_out: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    number_of_guests: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Backend-computed total at preview time; re-checked at confirm time.
    total_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="INR",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DRAFT_STATUS_PENDING,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    @property
    def is_expired(self) -> bool:
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            # Defensive: treat naive timestamps as UTC.
            expires_at = expires_at.replace(tzinfo=UTC)
        return datetime.now(UTC) >= expires_at
