"""Hotel-knowledge RAG subsystem.

Scope (hard rule): this package is ONLY for unstructured hotel knowledge —
handbook pages, check-in instructions, parking, spa, airport transfers,
restaurant descriptions, long-form policy explanations, local guides,
accessibility info. Availability, prices, bookings, guest records, orders,
and payment state NEVER enter this store; those stay SQL/tool operations.

Tenant isolation: every document and chunk carries ``hotel_id`` and the
retriever only ever reads chunks through the hotel-scoped SQL filter in
:class:`KnowledgeRepository.list_chunks`.

Vector store: plain Postgres (the chunk table), brute-force cosine in
Python. Rationale is documented in :mod:`app.knowledge.retriever` —
no pgvector, no vector DB, no new infrastructure. Embeddings come from a
local sentence-transformer model by default (see
:mod:`app.knowledge.embeddings`).
"""

from __future__ import annotations

from app.core.config import get_settings
from app.knowledge.chunking import chunk_text
from app.knowledge.embeddings import (
    ApiEmbeddingProvider,
    EmbeddingProvider,
    HashedBagOfWordsEmbedding,
    SentenceTransformerEmbedding,
)
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.retriever import RetrievedChunk, Retriever, cosine_similarity


def default_embedding_provider() -> EmbeddingProvider:
    """The embedding backend used by the agent tool and seed scripts.

    Selected by the ``EMBEDDING_PROVIDER`` setting (see
    :mod:`app.core.config`):

    - ``"sentence-transformer"`` (default): real semantic embeddings from
      the local model named by ``EMBEDDING_MODEL``.
    - ``"hashed"``: the deterministic stdlib-only hashed bag-of-words
      model — no model download, used by the unit-test suite.
    """
    settings = get_settings()
    if settings.embedding_provider == "hashed":
        return HashedBagOfWordsEmbedding()
    return SentenceTransformerEmbedding(model_name=settings.embedding_model)


__all__ = [
    "ApiEmbeddingProvider",
    "EmbeddingProvider",
    "HashedBagOfWordsEmbedding",
    "KnowledgeRepository",
    "RetrievedChunk",
    "Retriever",
    "SentenceTransformerEmbedding",
    "chunk_text",
    "cosine_similarity",
    "default_embedding_provider",
]
