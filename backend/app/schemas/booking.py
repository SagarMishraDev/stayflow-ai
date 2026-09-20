from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class BookingResponse(BaseModel):
    id: int
    hotel_id: int
    guest_id: int
    room_id: int
    check_in: date
    check_out: date
    number_of_guests: int
    final_price: Decimal
    booking_status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BookingCreate(BaseModel):
    hotel_id: int
    guest_id: int
    room_id: int
    check_in: date
    check_out: date
    number_of_guests: int = Field(gt=0)
    final_price: Decimal = Field(ge=0)
    booking_status: str = "PENDING"


class BookingUpdate(BaseModel):
    check_in: date | None = None
    check_out: date | None = None
    number_of_guests: int | None = Field(default=None, gt=0)
    final_price: Decimal | None = Field(default=None, ge=0)
    booking_status: str | None = None
