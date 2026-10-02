"""Background job queue for slow operations (Prompt-1 §6).

Redis + arq. The API enqueues jobs and answers immediately; the ``worker``
service (see docker-compose.yml) runs them.

- :mod:`app.jobs.tasks` — the arq task functions (RAG document ingestion).
- :mod:`app.jobs.queue` — Redis settings, the process-wide pool, the
  enqueue helper, and the ``WorkerSettings`` class the arq CLI consumes
  (``arq app.jobs.queue.WorkerSettings``).
"""

from __future__ import annotations

from app.jobs.queue import WorkerSettings, enqueue_ingestion, get_job_queue, redis_settings
from app.jobs.tasks import ingest_document

__all__ = [
    "WorkerSettings",
    "enqueue_ingestion",
    "get_job_queue",
    "ingest_document",
    "redis_settings",
]
