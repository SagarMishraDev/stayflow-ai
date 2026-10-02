"""Background job queue for slow RAG ingestion (Prompt-1 §6).

Covers:
- ``POST /api/v1/knowledge/documents`` answers 202 with
  ``status == "processing"`` *immediately* — before the worker runs.
- The arq worker completes chunking + embedding and flips the document to
  ``"ready"`` (chunks persisted, retrievable).
- A failing ingestion flips the document to ``"failed"`` with an error
  note instead of crashing.
- ``INGEST_JOBS_SYNC=true`` ingests inline (200, no Redis involved).

No real Redis is required: jobs run against fakeredis through a genuine
arq ``Worker`` in burst mode, so the true enqueue → run → result path is
exercised (serialization included).
"""

from __future__ import annotations

import asyncio

import arq.worker
import pytest
from arq import Worker
from arq.connections import ArqRedis
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

import app.jobs.queue as jobs_queue
from app.core.config import get_settings
from app.db.session import get_db
from app.jobs.tasks import ingest_document
from app.knowledge import KnowledgeRepository, default_embedding_provider
from tests._helpers import client, make_hotel, ok, uid


class FakeArqRedis(FakeRedis, ArqRedis):
    """arq's Redis API backed by fakeredis — no real Redis in tests."""

    def __init__(self, **kwargs):
        FakeRedis.__init__(self, **kwargs)
        # Attributes ArqRedis.__init__ would normally set.
        self.job_serializer = None
        self.job_deserializer = None
        self.default_queue_name = "arq:queue"
        self.expires_extra_ms = 86400000


async def _noop_log_redis_info(*args, **kwargs):
    # fakeredis does not implement INFO; this is only worker startup logging.
    return None


@pytest.fixture()
def fake_queue(monkeypatch):
    """Shared fake Redis server; the API's queue lookup is patched to use it.

    fakeredis sockets bind to the event loop that first uses them, and the
    API enqueues from the TestClient portal's loop while the test drains
    from its own. Each side therefore gets its own ``FakeArqRedis``
    instance, all sharing one ``FakeServer`` (shared in-memory state).
    """
    monkeypatch.setattr(arq.worker, "log_redis_info", _noop_log_redis_info)
    server = FakeServer()

    async def _get_pool():
        # Created lazily on first enqueue — inside the TestClient portal's
        # loop, so this instance's sockets bind to that loop.
        return FakeArqRedis(server=server)

    monkeypatch.setattr(jobs_queue, "get_job_queue", _get_pool)
    return server


def _drain_queue(server) -> None:
    """Run a real arq Worker in burst mode until the fake queue is empty."""

    async def _run():
        # Fresh pool instance bound to this loop; state shared via server.
        pool = FakeArqRedis(server=server)
        # Construct inside the running loop: Worker.__init__ grabs
        # asyncio.get_event_loop() and must see this loop.
        worker = Worker(
            functions=[ingest_document],
            redis_pool=pool,
            burst=True,
            handle_signals=False,
            max_tries=1,
        )
        await worker.async_run()

    asyncio.run(_run())


def _get(path):
    r = client.get(path)
    ok(r, 200)
    return r.json()


def test_document_api_returns_202_processing_then_worker_marks_ready(fake_queue):
    hotel = make_hotel()
    title = uid("QueuedDoc")
    content = " ".join(f"word{i}" for i in range(300))

    r = client.post(
        "/api/v1/knowledge/documents",
        json={
            "hotel_id": hotel["id"],
            "title": title,
            "content": content,
            "source": "test",
        },
    )
    ok(r, 202)
    body = r.json()
    assert body["status"] == "processing"
    assert body["id"] is not None
    assert body["title"] == title
    assert body["hotel_id"] == hotel["id"]
    doc_id = body["id"]

    # Prompt return: the API answered before any worker ran — still
    # "processing" and no chunks persisted.
    assert _get(f"/api/v1/knowledge/documents/{doc_id}")["status"] == "processing"
    db = next(get_db())
    try:
        assert KnowledgeRepository(db, default_embedding_provider()).count_chunks(hotel["id"]) == 0
    finally:
        db.close()

    _drain_queue(fake_queue)

    doc = _get(f"/api/v1/knowledge/documents/{doc_id}")
    assert doc["status"] == "ready"
    assert doc["error"] is None
    db = next(get_db())
    try:
        repo = KnowledgeRepository(db, default_embedding_provider())
        chunks = repo.list_chunks(hotel["id"])
        assert len(chunks) > 1
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        assert all(len(c.embedding) == 256 for c in chunks)  # hashed provider in tests
    finally:
        db.close()


def test_failed_ingestion_marks_document_failed(fake_queue):
    hotel = make_hotel()
    db = next(get_db())
    try:
        repo = KnowledgeRepository(db, default_embedding_provider())
        doc = repo.create_pending_document(
            hotel_id=hotel["id"], title=uid("FailDoc"), source="test"
        )
        db.commit()
        doc_id = doc.id
    finally:
        db.close()

    async def _enqueue():
        pool = await jobs_queue.get_job_queue()
        await pool.enqueue_job(
            "ingest_document",
            hotel_id=hotel["id"],
            document_id=doc_id,
            title="FailDoc",
            content="",  # invalid: ingestion must fail, not crash
        )

    asyncio.run(_enqueue())
    _drain_queue(fake_queue)

    doc = _get(f"/api/v1/knowledge/documents/{doc_id}")
    assert doc["status"] == "failed"
    assert doc["error"] is not None
    assert "ValueError" in doc["error"]
    # No chunks were persisted for the failed document.
    db = next(get_db())
    try:
        assert KnowledgeRepository(db, default_embedding_provider()).count_chunks(hotel["id"]) == 0
    finally:
        db.close()


def test_sync_flag_ingests_inline_without_redis(monkeypatch):
    """INGEST_JOBS_SYNC=true: the endpoint ingests inline and answers 200."""
    # Patch the attribute on the shared settings object (the convention
    # used by test_rate_limit.py) — never cache_clear(), which would
    # discard the instance other tests monkeypatch.
    monkeypatch.setattr(get_settings(), "ingest_jobs_sync", True)
    hotel = make_hotel()
    r = client.post(
        "/api/v1/knowledge/documents",
        json={
            "hotel_id": hotel["id"],
            "title": uid("SyncDoc"),
            "content": " ".join(f"syncword{i}" for i in range(300)),
            "source": "test",
        },
    )
    ok(r, 200)
    body = r.json()
    assert body["status"] == "ready"
    db = next(get_db())
    try:
        assert KnowledgeRepository(db, default_embedding_provider()).count_chunks(hotel["id"]) > 1
    finally:
        db.close()


def test_document_endpoints_are_hotel_scoped(fake_queue):
    from fastapi.testclient import TestClient

    from app.core.security import create_access_token, hash_password
    from app.db.session import SessionLocal
    from app.main import app
    from app.models.hotel_user import HotelUser

    hotel_a = make_hotel()
    hotel_b = make_hotel()
    r = client.post(
        "/api/v1/knowledge/documents",
        json={
            "hotel_id": hotel_a["id"],
            "title": uid("ScopedDoc"),
            "content": "secret knowledge for hotel A " * 40,
            "source": "test",
        },
    )
    ok(r, 202)
    doc_id = r.json()["id"]
    _drain_queue(fake_queue)

    # A staff token for hotel B…
    db = SessionLocal()
    try:
        user_b = HotelUser(
            hotel_id=hotel_b["id"],
            name="Scope Staff",
            email=f"{uid('scope')}@example.com",
            role="staff",
            password_hash=hash_password("scope-pass-123"),
        )
        db.add(user_b)
        db.commit()
        db.refresh(user_b)
        token_b = create_access_token(hotel_user_id=user_b.id, hotel_id=hotel_b["id"], role="staff")
        headers_b = {"Authorization": f"Bearer {token_b}"}
    finally:
        db.close()

    plain = TestClient(app)
    # …must not read hotel A's document…
    r = plain.get(
        f"/api/v1/knowledge/documents/{doc_id}",
        headers=headers_b,
    )
    assert r.status_code == 403, r.text

    # …nor list it.
    r = plain.get(
        "/api/v1/knowledge/documents",
        params={"hotel_id": hotel_b["id"]},
        headers=headers_b,
    )
    ok(r, 200)
    assert all(d["hotel_id"] == hotel_b["id"] for d in r.json())

    # And unauthenticated requests are rejected.
    r = plain.post(
        "/api/v1/knowledge/documents",
        json={"hotel_id": hotel_a["id"], "title": "x", "content": "y"},
    )
    assert r.status_code in (401, 403), r.text
