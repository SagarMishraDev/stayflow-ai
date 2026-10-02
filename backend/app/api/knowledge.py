"""Staff API for hotel-knowledge documents (Prompt-1 §6).

Ingestion is asynchronous: ``POST /documents`` persists the document with
status ``"processing"`` and enqueues an arq job, answering **202**
immediately. The worker chunks + embeds the content and flips the status
to ``"ready"`` (or ``"failed"`` with an ``error`` note). Clients poll
``GET /documents/{id}`` for the status.

``INGEST_JOBS_SYNC=true`` keeps the old synchronous behaviour available
for single-process setups with no Redis: ingestion runs inline and the
endpoint answers 200 with the final status.

All routes are staff-JWT protected and hotel-scoped like the rest of the
staff API (see :mod:`app.api.router`).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

# Shared staff-API helpers live in app.api.router (no import cycle: that
# module never imports this one).
from app.api.router import (
    _commit_or_409,
    _get_or_404,
    _hotel_exists,
    _require_tenant,
    _scoped_hotel_id,
)
from app.core.config import get_settings
from app.core.security import get_current_user
from app.db.session import get_db
from app.jobs.queue import enqueue_ingestion
from app.knowledge import KnowledgeRepository, default_embedding_provider
from app.models.hotel_user import HotelUser
from app.models.knowledge import HotelDocument
from app.schemas.knowledge import DocumentCreate, DocumentResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_QUEUE_UNAVAILABLE_DETAIL = (
    "Job queue unavailable: the document was saved but ingestion could not "
    "be enqueued. Check that Redis is running (REDIS_URL) or set "
    "INGEST_JOBS_SYNC=true."
)


def _repo(db: Session) -> KnowledgeRepository:
    return KnowledgeRepository(db, default_embedding_provider())


def _get_owned_document(db: Session, document_id: int, current_user: HotelUser) -> HotelDocument:
    document = _get_or_404(db, HotelDocument, document_id, "Document not found")
    _require_tenant(document.hotel_id, current_user)
    return document


@router.post("/documents", response_model=DocumentResponse)
async def create_knowledge_document(
    payload: DocumentCreate,
    response: Response,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> HotelDocument:
    """Submit a knowledge document for ingestion.

    Queue mode (default): persists the document as ``"processing"``,
    enqueues the chunking + embedding job, answers 202 immediately.
    Sync mode (``INGEST_JOBS_SYNC=true``): ingests inline, answers 200.
    """
    _hotel_exists(db, payload.hotel_id)
    _require_tenant(payload.hotel_id, current_user)
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")

    repo = _repo(db)
    try:
        document = repo.create_pending_document(
            hotel_id=payload.hotel_id,
            title=payload.title,
            source=payload.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    # The worker is a separate process: it must see this row.
    _commit_or_409(db, "Could not save document")
    db.refresh(document)

    if get_settings().ingest_jobs_sync:
        try:
            repo.ingest_content(
                document=document,
                content=payload.content,
                chunk_size=payload.chunk_size,
                overlap=payload.overlap,
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 — note persisted on the document
            db.rollback()
            note = f"ingestion failed: {type(exc).__name__}: {exc}"[:500]
            logger.exception("synchronous ingestion failed for document %s", document.id)
            repo.set_document_status(
                hotel_id=document.hotel_id,
                document_id=document.id,
                status="failed",
                error=note,
            )
            db.commit()
            raise HTTPException(status_code=500, detail=note) from None
        return document

    try:
        await enqueue_ingestion(
            hotel_id=document.hotel_id,
            document_id=document.id,
            title=document.title,
            content=payload.content,
            chunk_size=payload.chunk_size,
            overlap=payload.overlap,
        )
    except Exception as exc:  # noqa: BLE001 — Redis down, auth, serialization…
        logger.exception("could not enqueue ingestion for document %s", document.id)
        repo.set_document_status(
            hotel_id=document.hotel_id,
            document_id=document.id,
            status="failed",
            error=f"could not enqueue ingestion job: {type(exc).__name__}",
        )
        db.commit()
        raise HTTPException(status_code=503, detail=_QUEUE_UNAVAILABLE_DETAIL) from None

    response.status_code = 202
    return document


@router.get("/documents", response_model=list[DocumentResponse])
def list_knowledge_documents(
    hotel_id: int | None = None,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> list[HotelDocument]:
    scoped_hotel_id = _scoped_hotel_id(hotel_id, current_user)
    return _repo(db).list_documents(scoped_hotel_id)


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_knowledge_document(
    document_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> HotelDocument:
    return _get_owned_document(db, document_id, current_user)


@router.delete("/documents/{document_id}", status_code=204)
def delete_knowledge_document(
    document_id: int,
    db: Session = Depends(get_db, scope="function"),
    current_user: HotelUser = Depends(get_current_user),
) -> None:
    document = _get_owned_document(db, document_id, current_user)
    _repo(db).delete_document(document.hotel_id, document.id)
    db.commit()
