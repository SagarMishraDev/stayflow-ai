from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class OrderResponse(BaseModel):
    id: int
    hotel_id: int
    guest_id: int
    room_id: int | None
    order_type: str
    table_number: int | None
    status: str
    total_amount: Decimal
    created_at: datetime
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class OrderCreate(BaseModel):
    hotel_id: int
    guest_id: int
    room_id: int | None = None
    order_type: str
    table_number: int | None = None
    status: str = "PENDING"
    is_active: bool = True


class OrderUpdate(BaseModel):
    room_id: int | None = None
    order_type: str | None = None
    table_number: int | None = None
    status: str | None = None
    is_active: bool | None = None
