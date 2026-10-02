from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

SERVICE_REQUEST_STATUSES = (
    "PENDING",
    "ACKNOWLEDGED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
)


class ServiceRequestResponse(BaseModel):
    id: int
    hotel_id: int
    guest_id: int
    service_id: int
    room_number: str | None
    request_text: str | None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ServiceRequestCreate(BaseModel):
    hotel_id: int
    guest_id: int
    service_id: int
    room_number: str | None = None
    request_text: str | None = None
    status: str = "PENDING"

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in SERVICE_REQUEST_STATUSES:
            raise ValueError(f"status must be one of {SERVICE_REQUEST_STATUSES}")
        return normalized


class ServiceRequestUpdate(BaseModel):
    room_number: str | None = None
    request_text: str | None = None
    status: str | None = Field(default=None)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.upper()
        if normalized not in SERVICE_REQUEST_STATUSES:
            raise ValueError(f"status must be one of {SERVICE_REQUEST_STATUSES}")
        return normalized
