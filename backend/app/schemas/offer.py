from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OfferResponse(BaseModel):
    id: int
    hotel_id: int
    name: str
    description: str | None
    discount_type: str
    discount_value: Decimal
    valid_from: date
    valid_until: date
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class OfferCreate(BaseModel):
    hotel_id: int
    name: str
    description: str | None = None
    discount_type: str
    discount_value: Decimal = Field(ge=0)
    valid_from: date
    valid_until: date
    is_active: bool = True


class OfferUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    discount_type: str | None = None
    discount_value: Decimal | None = Field(default=None, ge=0)
    valid_from: date | None = None
    valid_until: date | None = None
    is_active: bool | None = None
