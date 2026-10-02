from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class NegotiationEvaluateRequest(BaseModel):
    hotel_id: int
    room_id: int
    check_in: date
    check_out: date
    offered_price: Decimal = Field(gt=0)


class NegotiationEvaluateResponse(BaseModel):
    accepted: bool
    requires_approval: bool
    base_price: Decimal
    offered_price: Decimal
    minimum_acceptable_price: Decimal
    maximum_discount_percent: Decimal
    reason: str
