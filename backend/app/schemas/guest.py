from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GuestResponse(BaseModel):
    id: int
    hotel_id: int
    name: str
    phone: str | None
    email: str | None
    nationality: str | None
    preferences: str | None
    notes: str | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GuestCreate(BaseModel):
    hotel_id: int
    name: str
    phone: str | None = None
    email: str | None = None
    nationality: str | None = None
    preferences: str | None = None
    notes: str | None = None
    is_active: bool = True


class GuestUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    nationality: str | None = None
    preferences: str | None = None
    notes: str | None = None
    is_active: bool | None = None
