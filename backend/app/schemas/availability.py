import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class AvailabilityResponse(BaseModel):
    id: int
    room_id: int
    date: dt.date
    available_rooms: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class AvailabilityCreate(BaseModel):
    room_id: int
    date: dt.date
    available_rooms: int = Field(ge=0)
    is_active: bool = True


class AvailabilityUpdate(BaseModel):
    date: dt.date | None = None
    available_rooms: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
