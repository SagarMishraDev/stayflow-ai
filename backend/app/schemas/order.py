from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

ORDER_TYPES = ("DINE_IN", "ROOM_SERVICE", "TAKEAWAY")
ORDER_STATUSES = (
    "PENDING",
    "CONFIRMED",
    "PREPARING",
    "READY",
    "DELIVERED",
    "CANCELLED",
)


class OrderResponse(BaseModel):
    id: int
    hotel_id: int
    guest_id: int
    room_id: int | None
    order_type: str
    table_number: int | None
    status: str
    status_reason: str | None = None
    scheduled_for: datetime | None = None
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

    @field_validator("order_type")
    @classmethod
    def validate_order_type(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in ORDER_TYPES:
            raise ValueError(f"order_type must be one of {ORDER_TYPES}")
        return normalized

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in ORDER_STATUSES:
            raise ValueError(f"status must be one of {ORDER_STATUSES}")
        return normalized


class OrderUpdate(BaseModel):
    room_id: int | None = None
    order_type: str | None = None
    table_number: int | None = None
    status: str | None = None
    is_active: bool | None = None

    @field_validator("order_type")
    @classmethod
    def validate_order_type(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.upper()
        if normalized not in ORDER_TYPES:
            raise ValueError(f"order_type must be one of {ORDER_TYPES}")
        return normalized

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.upper()
        if normalized not in ORDER_STATUSES:
            raise ValueError(f"status must be one of {ORDER_STATUSES}")
        return normalized
