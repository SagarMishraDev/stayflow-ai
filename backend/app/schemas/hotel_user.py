from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HotelUserCreate(BaseModel):
    name: str
    email: str
    phone: str | None = None
    role: str
    password: str = Field(min_length=8)
    department: str | None = None
    hotel_id: int | None = None  # super admins may create users in another hotel


class HotelUserUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    role: str | None = None
    department: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


class HotelUserResponse(BaseModel):
    id: int
    hotel_id: int
    name: str
    email: str
    phone: str | None
    role: str
    department: str | None = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
