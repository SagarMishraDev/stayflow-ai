from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Rate(Base):
    __tablename__ = "rates"

    id: Mapped[int] = mapped_column(primary_key=True)

    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id"),
        nullable=False,
    )

    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        default="INR",
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )