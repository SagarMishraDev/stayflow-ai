from pydantic import BaseModel, ConfigDict


class HotelResponse(BaseModel):
    id: int
    name: str
    description: str | None
    city: str
    address: str | None
    phone: str | None
    email: str | None
    timezone: str
    currency: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class HotelCreate(BaseModel):
    name: str
    description: str | None = None
    city: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    timezone: str = "Asia/Kolkata"
    currency: str = "INR"
    is_active: bool = True


class HotelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    city: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    timezone: str | None = None
    currency: str | None = None
    is_active: bool | None = None
