from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    hotel_id: int
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None
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
    iterations: int
    degraded: bool = False
    # Internal language metadata for staff tooling/tests — the labels are
    # never part of the guest-visible reply text.
    detected_language: str | None = None
    response_language: str | None = None
    tool_trace: list[ToolTraceResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
