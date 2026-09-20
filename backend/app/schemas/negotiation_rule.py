from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class NegotiationRuleResponse(BaseModel):
    id: int
    hotel_id: int
    room_id: int | None
    is_enabled: bool
    minimum_price: Decimal
    maximum_discount_percent: Decimal
    requires_approval: bool
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class NegotiationRuleCreate(BaseModel):
    hotel_id: int
    room_id: int | None = None
    is_enabled: bool = True
    minimum_price: Decimal = Field(ge=0)
    maximum_discount_percent: Decimal = Field(ge=0, le=100)
    requires_approval: bool = False
    is_active: bool = True


class NegotiationRuleUpdate(BaseModel):
    room_id: int | None = None
    is_enabled: bool | None = None
    minimum_price: Decimal | None = Field(default=None, ge=0)
    maximum_discount_percent: Decimal | None = Field(default=None, ge=0, le=100)
    requires_approval: bool | None = None
    is_active: bool | None = None
