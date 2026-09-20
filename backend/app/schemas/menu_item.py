from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MenuItemResponse(BaseModel):
    id: int
    hotel_id: int
    name: str
    description: str | None
    category: str | None
    price: Decimal
    is_available: bool
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class MenuItemCreate(BaseModel):
    hotel_id: int
    name: str
    description: str | None = None
    category: str | None = None
    price: Decimal = Field(ge=0)
    is_available: bool = True
    is_active: bool = True


class MenuItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    is_available: bool | None = None
    is_active: bool | None = None
