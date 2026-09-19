from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)

    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id"),
        nullable=False,
    )

    guest_id: Mapped[int] = mapped_column(
        ForeignKey("guests.id"),
        nullable=False,
    )

    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("hotel_rooms.id"),
        nullable=True,
    )
    
    order_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    table_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PENDING",
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )