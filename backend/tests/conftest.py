"""Pytest bootstrap: force the deterministic mock agent provider and the
fast stdlib-only hashed embedding provider in tests.

Unit tests must not download or load the real sentence-transformer model:
``EMBEDDING_PROVIDER=hashed`` keeps ``default_embedding_provider()`` on the
hashed fallback. The integration test marked ``@pytest.mark.slow``
constructs ``SentenceTransformerEmbedding`` explicitly and loads the real
model (run it with ``pytest -m slow``).
"""

import os

os.environ.setdefault("AGENT_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "hashed")
