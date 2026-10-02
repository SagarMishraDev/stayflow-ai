"""CRUD for hotel knowledge documents and their embedding chunks.

Tenant rule: every method takes ``hotel_id`` explicitly and only ever reads
or writes rows for that hotel. Chunks are loaded via the same filter, so the
retriever cannot leak another hotel's content even if called carelessly.

Like the rest of the codebase, writes are flushed but not committed — the
caller owns the transaction.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.knowledge.chunking import chunk_text
from app.knowledge.embeddings import EmbeddingProvider
from app.models.knowledge import HotelDocument, HotelDocumentChunk


class KnowledgeRepository:
    """Hotel-scoped persistence for documents and their chunks."""

    def __init__(self, db: Session, embedding: EmbeddingProvider) -> None:
        self._db = db
        self._embedding = embedding

    # ------------------------------------------------------------------ #
    # documents                                                           #
    # ------------------------------------------------------------------ #
    # Ingestion lifecycle (Prompt-1 §6): ``create_pending_document`` stores
    # the row with status "processing" and no chunks; the background worker
    # later calls ``ingest_content`` which chunks + embeds and flips the
    # status to "ready" (or "failed" with an error note). ``create_document``
    # is the synchronous path: it does both steps inline and only returns
    # once the document is "ready".

    def create_pending_document(
        self,
        *,
        hotel_id: int,
        title: str,
        source: str = "manual",
    ) -> HotelDocument:
        """Persist a document row with status ``"processing"`` and no chunks.

        The caller is expected to enqueue (or run) the ingestion work that
        fills in the chunks via :meth:`ingest_content`.
        """
        if not title.strip():
            raise ValueError("title must not be empty")
        document = HotelDocument(
            hotel_id=hotel_id,
            title=title.strip(),
            source=source,
            status="processing",
        )
        self._db.add(document)
        self._db.flush()  # assign document.id
        self._db.refresh(document)
        return document

    def ingest_content(
        self,
        *,
        document: HotelDocument,
        content: str,
        chunk_size: int = 120,
        overlap: int = 20,
    ) -> HotelDocument:
        """Chunk + embed ``content`` into a pending document; marks it ready."""
        if not content.strip():
            raise ValueError("content must not be empty")
        chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
        vectors = self._embedding.embed_many(chunks)
        for index, (text, vector) in enumerate(zip(chunks, vectors, strict=True)):
            self._db.add(
                HotelDocumentChunk(
                    document_id=document.id,
                    hotel_id=document.hotel_id,
                    chunk_index=index,
                    content=text,
                    embedding=vector,
                )
            )
        document.status = "ready"
        document.error = None
        self._db.flush()
        self._db.refresh(document)
        return document

    def set_document_status(
        self,
        *,
        hotel_id: int,
        document_id: int,
        status: str,
        error: str | None = None,
    ) -> HotelDocument | None:
        """Hotel-scoped status transition. Returns None when not found."""
        if status not in ("processing", "ready", "failed"):
            raise ValueError(f"unknown document status: {status!r}")
        document = self.get_document(hotel_id, document_id)
        if document is None:
            return None
        document.status = status
        document.error = error
        self._db.flush()
        self._db.refresh(document)
        return document

    def create_document(
        self,
        *,
        hotel_id: int,
        title: str,
        content: str,
        source: str = "manual",
        chunk_size: int = 120,
        overlap: int = 20,
    ) -> HotelDocument:
        """Ingest a document synchronously: persist it, chunk it, embed it.

        Only returns once the document is ``"ready"``. On failure the
        document is marked ``"failed"`` with an error note and the original
        exception is re-raised.
        """
        document = self.create_pending_document(hotel_id=hotel_id, title=title, source=source)
        try:
            return self.ingest_content(
                document=document,
                content=content,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        except Exception as exc:
            document.status = "failed"
            document.error = f"ingestion failed: {type(exc).__name__}: {exc}"[:500]
            self._db.flush()
            raise

    def get_document(self, hotel_id: int, document_id: int) -> HotelDocument | None:
        return self._db.scalar(
            select(HotelDocument).where(
                HotelDocument.id == document_id,
                HotelDocument.hotel_id == hotel_id,
            )
        )

    def list_documents(self, hotel_id: int) -> list[HotelDocument]:
        return list(
            self._db.scalars(
                select(HotelDocument)
                .where(HotelDocument.hotel_id == hotel_id)
                .order_by(HotelDocument.id)
            ).all()
        )

    def document_exists(self, hotel_id: int, title: str) -> bool:
        return (
            self._db.scalar(
                select(HotelDocument.id).where(
                    HotelDocument.hotel_id == hotel_id,
                    HotelDocument.title == title,
                )
            )
            is not None
        )

    def delete_document(self, hotel_id: int, document_id: int) -> bool:
        """Delete a document and all its chunks. Returns True if it existed."""
        document = self.get_document(hotel_id, document_id)
        if document is None:
            return False
        self._db.execute(
            delete(HotelDocumentChunk).where(
                HotelDocumentChunk.document_id == document_id,
                HotelDocumentChunk.hotel_id == hotel_id,
            )
        )
        self._db.delete(document)
        self._db.flush()
        return True

    # ------------------------------------------------------------------ #
    # chunks (read path for the retriever)                                #
    # ------------------------------------------------------------------ #
    def list_chunks(self, hotel_id: int) -> list[HotelDocumentChunk]:
        """All chunks for a hotel, in document/chunk order.

        The ``hotel_id`` filter is the tenant-isolation boundary: the
        retriever must never see rows from another hotel. Only chunks of
        ``"ready"`` documents are returned — documents still ``"processing"``
        or marked ``"failed"`` are never surfaced to guests.
        """
        return list(
            self._db.scalars(
                select(HotelDocumentChunk)
                .join(HotelDocument, HotelDocument.id == HotelDocumentChunk.document_id)
                .options(selectinload(HotelDocumentChunk.document))
                .where(
                    HotelDocumentChunk.hotel_id == hotel_id,
                    HotelDocument.status == "ready",
                )
                .order_by(HotelDocumentChunk.document_id, HotelDocumentChunk.chunk_index)
            ).all()
        )

    def count_chunks(self, hotel_id: int) -> int:
        return len(self.list_chunks(hotel_id))
