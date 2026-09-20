import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RateResponse(BaseModel):
    id: int
    room_id: int
    date: dt.date
    price: Decimal
    currency: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class RateCreate(BaseModel):
    room_id: int
    date: dt.date
    price: Decimal = Field(gt=0)
    currency: str = "INR"
    is_active: bool = True


class RateUpdate(BaseModel):
    date: dt.date | None = None
    price: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None
    is_active: bool | None = None
