"""Hotel knowledge-base models for the RAG subsystem.

``HotelDocument`` stores a logical document (handbook page, spa brochure,
airport-transfer instructions, ...) and ``HotelDocumentChunk`` stores the
overlapping text chunks derived from it together with their embeddings.

Hard rules (Prompt-2):
- RAG is ONLY for unstructured hotel knowledge. Availability, prices,
  bookings, guest records, orders, and payment state never live here.
- Every document and chunk is scoped to ``hotel_id``. The retriever always
  filters on it, so a guest of hotel A can never retrieve hotel B's chunks.
- Embeddings are stored as plain JSON float arrays; no pgvector or vector
  DB dependency (see :mod:`app.knowledge` for the rationale).
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class HotelDocument(Base):
    __tablename__ = "hotel_documents"

    id: Mapped[int] = mapped_column(primary_key=True)

    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="manual",
    )

    # Ingestion lifecycle for the background job queue (Prompt-1 §6):
    #   "processing" — document row created, chunking+embedding not done yet;
    #   "ready"      — chunks + embeddings persisted, retrievable;
    #   "failed"     — ingestion raised; see ``error`` for the note.
    # The synchronous ``KnowledgeRepository.create_document`` path goes
    # straight to "ready" (it only returns once ingestion is done).
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="processing",
    )

    # Short failure note set when ``status`` becomes "failed". Never a
    # traceback dump — one line, safe to surface to staff users.
    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    chunks: Mapped[list["HotelDocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class HotelDocumentChunk(Base):
    __tablename__ = "hotel_document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)

    document_id: Mapped[int] = mapped_column(
        ForeignKey("hotel_documents.id"),
        nullable=False,
    )

    hotel_id: Mapped[int] = mapped_column(
        ForeignKey("hotels.id"),
        nullable=False,
        index=True,
    )

    chunk_index: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Plain JSON float array. Brute-force cosine in Python is fast enough at
    # this scale, so no pgvector / vector-DB dependency is needed.
    embedding: Mapped[list[float]] = mapped_column(
        JSON,
        nullable=False,
    )

    document: Mapped[HotelDocument] = relationship(
        back_populates="chunks",
    )

    __table_args__ = (Index("ix_hotel_document_chunks_hotel_document", "hotel_id", "document_id"),)
