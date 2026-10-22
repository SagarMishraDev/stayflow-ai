import re

from pydantic import BaseModel, ConfigDict, field_validator

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_time(value: str | None) -> str | None:
    if value is None:
        return value
    if not _TIME_RE.match(value):
        raise ValueError("time must be HH:MM in 24-hour format, e.g. 14:00")
    return value


class HotelResponse(BaseModel):
    id: int
    public_id: str
    name: str
    description: str | None
    city: str
    address: str | None
    phone: str | None
    email: str | None
    check_in_time: str | None
    check_out_time: str | None
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
    check_in_time: str | None = None
    check_out_time: str | None = None
    timezone: str = "Asia/Kolkata"
    currency: str = "INR"
    is_active: bool = True

    @field_validator("check_in_time", "check_out_time")
    @classmethod
    def _check_times(cls, value: str | None) -> str | None:
        return _validate_time(value)


class HotelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    city: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    timezone: str | None = None
    currency: str | None = None
    is_active: bool | None = None

    @field_validator("check_in_time", "check_out_time")
    @classmethod
    def _check_times(cls, value: str | None) -> str | None:
        return _validate_time(value)
