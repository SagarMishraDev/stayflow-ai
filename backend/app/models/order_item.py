
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"),
        nullable=False,
    )

    menu_item_id: Mapped[int] = mapped_column(
        ForeignKey("menu_items.id"),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    customization: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )