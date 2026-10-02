"""Embedding providers for the knowledge base.

The default provider is :class:`SentenceTransformerEmbedding`, a real
semantic model (``all-MiniLM-L6-v2``) that runs fully locally: the model
weights download once (~90 MB) on first use into the Hugging Face cache and
inference is offline afterwards — no API keys, no network at query time.

``HashedBagOfWordsEmbedding`` is kept as a fast, deterministic, stdlib-only
fallback (selected with ``EMBEDDING_PROVIDER=hashed``): it needs no model
download, which makes it ideal for unit tests and CI.

``ApiEmbeddingProvider`` is a thin extension point for teams that later want
a hosted embedding API — it is deliberately *not* wired in by default.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol


class EmbeddingProvider(Protocol):
    """Contract every embedding backend must satisfy."""

    @property
    def dimension(self) -> int:
        """Length of the vectors returned by :meth:`embed`."""
        ...

    def embed(self, text: str) -> list[float]:
        """Embed a single text into a dense vector."""
        ...

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts; order matches the input."""
        ...


_TOKEN_RE = re.compile(r"[a-z0-9]+")


class SentenceTransformerEmbedding:
    """Real semantic embeddings via a local sentence-transformer model.

    Implements the existing :class:`EmbeddingProvider` protocol unchanged, so
    it is a drop-in swap for :class:`HashedBagOfWordsEmbedding`.

    The model downloads once from Hugging Face on first use (``~90 MB`` for
    the default ``all-MiniLM-L6-v2``) into the Hugging Face cache
    (``~/.cache/huggingface`` by default, or ``HF_HOME``/``HF_HUB_CACHE``);
    afterwards everything runs offline. Loading is lazy — constructing the
    provider never touches the network — and model instances are cached per
    model name so repeated construction is cheap.

    Vectors are L2-normalized by the encoder, matching the normalization
    contract of the hashed provider.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        if not model_name or not model_name.strip():
            raise ValueError("model_name must not be empty")
        self._model_name = model_name.strip()
        self._model: Any = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self) -> Any:
        if self._model is None:
            self._model = _load_sentence_transformer(self._model_name)
        return self._model

    @property
    def dimension(self) -> int:
        model = self._load()
        # sentence-transformers >= 5 renamed get_sentence_embedding_dimension
        # to get_embedding_dimension; support both.
        get_dim = getattr(model, "get_embedding_dimension", None)
        if get_dim is None:
            get_dim = model.get_sentence_embedding_dimension
        return int(get_dim())

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in row] for row in vectors]


_model_cache: dict[str, Any] = {}


def _load_sentence_transformer(model_name: str) -> Any:
    """Load (and cache) a sentence-transformer model by name.

    Imported lazily so that merely importing this module — or selecting the
    ``hashed`` provider — never requires the ``sentence-transformers``
    package to be installed.
    """
    if model_name not in _model_cache:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "The 'sentence-transformers' package is required for the "
                f"'{model_name}' embedding model but is not installed. "
                "Install it (pip install sentence-transformers) or set "
                "EMBEDDING_PROVIDER=hashed to use the stdlib-only fallback."
            ) from exc
        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


class HashedBagOfWordsEmbedding:
    """Deterministic local embeddings via the hashing trick.

    Each token is hashed (SHA-256) into one of ``dimension`` buckets, counts
    are accumulated, and the vector is L2-normalized. Same text always yields
    the same vector; similar texts yield vectors with high cosine similarity.
    """

    def __init__(self, dimension: int = 256) -> None:
        if dimension < 1:
            raise ValueError("dimension must be >= 1")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "big") % self._dimension
            vector[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class ApiEmbeddingProvider:
    """Extension point for a hosted embedding API (e.g. an OpenAI-compatible
    ``/embeddings`` endpoint).

    Not wired into the app: constructing it does not make any network calls.
    Offline deployments must keep using the local providers
    (:class:`SentenceTransformerEmbedding` or
    :class:`HashedBagOfWordsEmbedding`) — never a hosted API.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        dimension: int,
        api_key: str | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self._dimension = dimension
        self.api_key = api_key

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:  # noqa: ARG002
        raise NotImplementedError(
            "ApiEmbeddingProvider is a stub: implement the HTTP call to "
            f"{self.endpoint} before using it."
        )

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]
