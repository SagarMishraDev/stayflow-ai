from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    id: int
    hotel_id: int
    actor_type: str
    actor_id: int | None
    action: str
    entity_type: str | None
    entity_id: int | None
    details: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationResponse(BaseModel):
    id: int
    hotel_id: int
    user_id: int
    type: str
    title: str
    message: str
    reference_type: str | None
    reference_id: int | None
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
