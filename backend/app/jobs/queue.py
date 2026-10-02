"""arq/Redis wiring for the background job queue (Prompt-1 §6).

The API never builds Redis connections inline: :func:`get_job_queue`
hands out one process-wide :class:`~arq.connections.ArqRedis` pool,
created lazily from :attr:`app.core.config.Settings.redis_url` so the API
can boot even when Redis is down (enqueue then fails per-request with a
503 instead of taking the whole API down).

The worker entrypoint is the :class:`WorkerSettings` class below, consumed
by the arq CLI::

    arq app.jobs.queue.WorkerSettings

(in Docker: the ``worker`` service in docker-compose.yml).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.jobs import Job

from app.core.config import get_settings
from app.jobs.tasks import ingest_document

logger = logging.getLogger(__name__)

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    """Build arq's :class:`RedisSettings` from ``Settings.redis_url``.

    Accepted form: ``redis://[:password@]host[:port][/db]`` (the
    ``rediss://`` scheme is not supported — TLS termination, if needed,
    belongs in front of Redis, not in this parser).
    """
    parsed = urlparse(get_settings().redis_url)
    if parsed.scheme != "redis" or not parsed.hostname:
        raise ValueError(
            f"redis_url must look like redis://host[:port][/db], got {get_settings().redis_url!r}"
        )
    database = 0
    if parsed.path and parsed.path != "/":
        try:
            database = int(parsed.path.lstrip("/"))
        except ValueError as exc:
            raise ValueError(f"redis_url database must be an integer, got {parsed.path!r}") from exc
    return RedisSettings(
        host=parsed.hostname,
        port=parsed.port or 6379,
        database=database,
        password=parsed.password,
    )


async def get_job_queue() -> ArqRedis:
    """Return the process-wide arq Redis pool, creating it on first use."""
    global _pool
    if _pool is None:
        settings = redis_settings()
        logger.info(
            "Connecting job queue to Redis at %s:%s/%s",
            settings.host,
            settings.port,
            settings.database,
        )
        _pool = await create_pool(settings)
    return _pool


async def enqueue_ingestion(
    *,
    hotel_id: int,
    document_id: int,
    title: str,
    content: str,
    chunk_size: int = 120,
    overlap: int = 20,
) -> Job:
    """Enqueue RAG document ingestion; raises if Redis is unreachable.

    The job payload carries the raw ``content`` — the worker chunks and
    embeds it, then flips the document to ``"ready"`` (or ``"failed"``).
    """
    pool = await get_job_queue()
    return await pool.enqueue_job(
        "ingest_document",
        hotel_id=hotel_id,
        document_id=document_id,
        title=title,
        content=content,
        chunk_size=chunk_size,
        overlap=overlap,
    )


class WorkerSettings:
    """arq worker configuration (``arq app.jobs.queue.WorkerSettings``).

    ``redis_settings`` is read from the environment at import time, so the
    worker container only needs ``REDIS_URL`` (plus the usual ``DATABASE_URL``
    and embedding settings) to be set.
    """

    functions = [ingest_document]
    redis_settings = redis_settings()

    # A stuck embedding run must not wedge the worker forever; the task
    # itself marks the document "failed" on exception.
    job_timeout = 600
    max_tries = 1

    @staticmethod
    async def on_startup(ctx: dict) -> None:
        logger.info("arq worker starting (queue: %s)", ctx.get("queue_name", "arq:queue"))

    @staticmethod
    async def on_shutdown(ctx: dict) -> None:
        logger.info("arq worker shutting down")
