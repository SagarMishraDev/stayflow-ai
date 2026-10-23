from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Payment record lifecycle. A record is evidence staff entered (or a
# gateway reported); "captured" means the hotel recorded the money as
# received — it is not, by itself, proof of bank settlement.
PAYMENT_STATUSES = ("pending", "captured", "refunded", "failed")
PAYMENT_METHODS = ("cash", "card", "upi", "bank_transfer", "other")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_hotel_created", "hotel_id", "created_at"),
        Index("ix_payments_booking", "booking_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id"),
        nullable=False,
    )

    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id"),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="cash",
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
    )

    # External reference (UPI txn id, gateway payment id, receipt no.).
    reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
