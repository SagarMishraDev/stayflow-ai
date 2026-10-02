from datetime import datetime

from pydantic import BaseModel, ConfigDict

CHANNELS = ("web", "telegram", "whatsapp", "api")
SENDER_TYPES = ("guest", "agent", "staff", "system")


class ConversationResponse(BaseModel):
    id: int
    hotel_id: int
    guest_id: int | None
    channel: str
    status: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationCreate(BaseModel):
    hotel_id: int
    guest_id: int
    channel: str = "web"


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    sender_type: str
    message: str
    message_type: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageCreate(BaseModel):
    sender_type: str = "guest"
    message: str
    message_type: str = "TEXT"
