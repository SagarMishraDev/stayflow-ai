"""Top-k cosine-similarity retrieval over hotel knowledge chunks.

Why Postgres + brute-force cosine instead of pgvector / a vector DB:

- **Scale**: a hotel knowledge base is hundreds to low-thousands of chunks.
  A single indexed ``WHERE hotel_id = ?`` scan plus Python-side cosine math
  answers in milliseconds — no ANN index needed.
- **Tenant isolation**: isolation is a plain SQL predicate enforced in
  :meth:`KnowledgeRepository.list_chunks`, trivially auditable. A shared
  vector index would need the same filter *plus* trust in the index's
  filtering semantics.
- **Zero new infrastructure**: no pgvector extension, no sidecar service.
  The default
  :class:`~app.knowledge.embeddings.SentenceTransformerEmbedding` is a local
  model that runs fully offline after its one-time download; the
  ``EMBEDDING_PROVIDER=hashed`` fallback is pure stdlib.

If the corpus ever grows past ~100k chunks per hotel, replace
:meth:`Retriever.search`'s in-memory scan with an ANN index — the
repository's hotel-scoped read boundary stays the same.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.knowledge.embeddings import EmbeddingProvider
from app.knowledge.repository import KnowledgeRepository


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: int
    document_title: str
    chunk_index: int
    content: str
    score: float  # cosine similarity in [-1, 1]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors."""
    if len(a) != len(b):
        raise ValueError("vectors must have the same dimension")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class Retriever:
    """Hotel-scoped top-k retrieval. Never consults cross-hotel data."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        embedding: EmbeddingProvider,
    ) -> None:
        self._repository = repository
        self._embedding = embedding

    def search(
        self,
        *,
        hotel_id: int,
        query: str,
        top_k: int = 3,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        """Return the top-k chunks for ``hotel_id`` most similar to ``query``.

        Chunks with similarity ``<= min_score`` are dropped, so unrelated
        content (zero token overlap) is never returned as an answer.
        """
        query = query.strip()
        if not query:
            return []
        chunks = self._repository.list_chunks(hotel_id)  # hotel_id-filtered SQL
        if not chunks:
            return []
        query_vector = self._embedding.embed(query)
        scored = [(cosine_similarity(query_vector, chunk.embedding), chunk) for chunk in chunks]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        results: list[RetrievedChunk] = []
        for score, chunk in scored[: max(top_k, 0)]:
            if score <= min_score:
                continue
            results.append(
                RetrievedChunk(
                    document_id=chunk.document_id,
                    document_title=chunk.document.title if chunk.document else "",
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    score=score,
                )
            )
        return results
