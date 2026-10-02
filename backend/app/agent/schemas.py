from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    hotel_id: int
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None
    conversation_token: str | None = Field(default=None, min_length=20, max_length=128)
    guest_id: int | None = None
    channel: str = "web"


class ToolTraceResponse(BaseModel):
    tool: str
    arguments: dict[str, Any]
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: int
    conversation_token: str
    iterations: int
    degraded: bool = False
    tool_trace: list[ToolTraceResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
