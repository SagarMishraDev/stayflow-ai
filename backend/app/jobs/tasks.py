"""arq task functions for slow operations (Prompt-1 §6).

Each task opens its own DB session — the worker is a separate process from
the API, so it must never reuse a request-scoped session. Tenant isolation
is enforced the same way as the API: every task takes ``hotel_id``
explicitly and the repository only touches rows for that hotel.

Failure policy is deliberate: a task that raises marks its document
``"failed"`` with a one-line error note and does NOT re-raise, so arq does
not retry it into an inconsistent state. A failed document stays visible
via the API (status ``"failed"`` + ``error``) and can be re-submitted with
a fresh POST.
"""

from __future__ import annotations

import logging
from typing import Any

from app.db.session import SessionLocal
from app.knowledge import KnowledgeRepository, default_embedding_provider

logger = logging.getLogger(__name__)

_ERROR_NOTE_LIMIT = 500


async def ingest_document(
    ctx: dict[str, Any],
    *,
    hotel_id: int,
    document_id: int,
    title: str,
    content: str,
    chunk_size: int = 120,
    overlap: int = 20,
) -> dict[str, Any]:
    """Chunk + embed a pending knowledge document, then mark it ready.

    Runs in the arq worker process. On success the document status becomes
    ``"ready"``; on any exception it becomes ``"failed"`` with a short error
    note (never a traceback). Idempotent: documents that are not in
    ``"processing"`` state are skipped, so a duplicate/redelivered job can
    never double-ingest chunks.
    """
    db = SessionLocal()
    try:
        repo = KnowledgeRepository(db, default_embedding_provider())
        document = repo.get_document(hotel_id, document_id)
        if document is None:
            logger.warning(
                "ingest_document: document %s for hotel %s not found; skipping",
                document_id,
                hotel_id,
            )
            return {"ok": False, "reason": "document-not-found"}
        if document.status != "processing":
            logger.info(
                "ingest_document: document %s already %s; skipping",
                document_id,
                document.status,
            )
            return {"ok": False, "reason": f"already-{document.status}"}

        repo.ingest_content(
            document=document,
            content=content,
            chunk_size=chunk_size,
            overlap=overlap,
        )
        db.commit()
        chunk_count = repo.count_chunks(hotel_id)
        logger.info(
            "ingest_document: document %s (%r) ready for hotel %s",
            document_id,
            title,
            hotel_id,
        )
        return {"ok": True, "document_id": document_id, "hotel_chunks": chunk_count}
    except Exception as exc:  # noqa: BLE001 — the failure note must never escape
        db.rollback()
        note = f"ingestion failed: {type(exc).__name__}: {exc}"[:_ERROR_NOTE_LIMIT]
        logger.exception(
            "ingest_document: document %s for hotel %s failed",
            document_id,
            hotel_id,
        )
        try:
            repo = KnowledgeRepository(db, default_embedding_provider())
            repo.set_document_status(
                hotel_id=hotel_id,
                document_id=document_id,
                status="failed",
                error=note,
            )
            db.commit()
        except Exception:  # noqa: BLE001 — best effort; the original error is logged
            db.rollback()
            logger.exception(
                "ingest_document: could not persist failure status for document %s",
                document_id,
            )
        return {"ok": False, "reason": "failed", "error": note}
    finally:
        db.close()
