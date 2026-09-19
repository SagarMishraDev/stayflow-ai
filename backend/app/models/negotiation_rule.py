from sqlalchemy import Boolean, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NegotiationRule(Base):
    __tablename__ = "negotiation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)

    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id"),
        nullable=False,
    )

    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id"),
        nullable=True,
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    minimum_price: Mapped[float] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    maximum_discount_percent: Mapped[float] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )