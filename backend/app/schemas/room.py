from pydantic import BaseModel, ConfigDict


class RoomResponse(BaseModel):
    id: int
    hotel_id: int
    room_type: str
    description: str | None
    capacity: int
    total_rooms: int
    amenities: str | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class RoomCreate(BaseModel):
    hotel_id: int
    room_type: str
    description: str | None = None
    capacity: int
    total_rooms: int
    amenities: str | None = None
    is_active: bool = True


class RoomUpdate(BaseModel):
    room_type: str | None = None
    description: str | None = None
    capacity: int | None = None
    total_rooms: int | None = None
    amenities: str | None = None
    is_active: bool | None = None
