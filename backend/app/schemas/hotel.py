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
