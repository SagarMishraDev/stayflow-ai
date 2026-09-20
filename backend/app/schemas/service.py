from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ServiceResponse(BaseModel):
    id: int
    hotel_id: int
    name: str
    description: str | None
    price: Decimal | None
    category: str | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class ServiceCreate(BaseModel):
    hotel_id: int
    name: str
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    category: str | None = None
    is_active: bool = True


class ServiceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    category: str | None = None
    is_active: bool | None = None
