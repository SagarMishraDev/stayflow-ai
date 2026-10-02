"""Pytest bootstrap for deterministic test configuration and isolation.

Unit tests must not download or load the real sentence-transformer model:
``EMBEDDING_PROVIDER=hashed`` keeps ``default_embedding_provider()`` on the
hashed fallback. The integration test marked ``@pytest.mark.slow``
constructs ``SentenceTransformerEmbedding`` explicitly and loads the real
model (run it with ``pytest -m slow``).

Rate-limit buckets are process-global in the application, so every test gets
a clean limiter state to prevent one test from affecting another.
"""

import os

import pytest

from app.core.rate_limit import reset_rate_limit_state

os.environ.setdefault("AGENT_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "hashed")


@pytest.fixture(autouse=True)
def _fresh_rate_limit_buckets():
    """Keep rate-limit state isolated between tests."""
    reset_rate_limit_state()
    yield
    reset_rate_limit_state()
