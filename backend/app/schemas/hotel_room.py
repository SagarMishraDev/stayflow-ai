from pydantic import BaseModel, ConfigDict


class HotelRoomResponse(BaseModel):
    id: int
    hotel_id: int
    room_id: int
    room_number: str
    is_active: bool
    cleaning_status: str = "READY"

    model_config = ConfigDict(from_attributes=True)


class HotelRoomCreate(BaseModel):
    hotel_id: int
    room_id: int
    room_number: str
    is_active: bool = True


class HotelRoomUpdate(BaseModel):
    room_number: str | None = None
    is_active: bool | None = None
