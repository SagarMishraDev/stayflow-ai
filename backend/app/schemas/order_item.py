from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrderItemResponse(BaseModel):
    id: int
    order_id: int
    menu_item_id: int
    quantity: int
    unit_price: Decimal
    customization: str | None
    subtotal: Decimal

    model_config = ConfigDict(from_attributes=True)


class OrderItemCreate(BaseModel):
    order_id: int
    menu_item_id: int
    quantity: int = Field(gt=0)
    customization: str | None = None


class OrderItemUpdate(BaseModel):
    menu_item_id: int | None = None
    quantity: int | None = Field(default=None, gt=0)
    customization: str | None = None
