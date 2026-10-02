"""Schemas for the hotel-knowledge document API (Prompt-1 §6).

Document ingestion is asynchronous: ``POST /knowledge/documents`` answers
202 with ``status == "processing"`` and the arq worker flips the document
to ``"ready"`` (or ``"failed"`` with an ``error`` note) once chunking +
embedding finish. Clients poll ``GET /knowledge/documents/{id}``.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentCreate(BaseModel):
    hotel_id: int
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    source: str = Field(default="manual", max_length=100)
    chunk_size: int = Field(default=120, ge=1, le=2000)
    overlap: int = Field(default=20, ge=0, le=1999)


class DocumentResponse(BaseModel):
    id: int
    hotel_id: int
    title: str
    source: str
    status: str
    error: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
