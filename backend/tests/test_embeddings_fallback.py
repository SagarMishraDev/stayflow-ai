"""ResilientEmbeddingProvider: semantic embeddings with a hashed net.

The wrapper must:
- pass successful primary results through untouched;
- on the first primary failure, serve the hashed fallback AND cache the
  failure (the primary is never retried in this process — no
  retry-storm against a model that already failed to load/encode);
- report the fallback's dimension once tripped.

All providers here are stubs — no model is downloaded.
"""

from app.knowledge import HashedBagOfWordsEmbedding, ResilientEmbeddingProvider


class _FailingPrimary:
    """Primary whose every operation raises, counting its calls."""

    def __init__(self):
        self.embed_calls = 0
        self.dimension_calls = 0

    @property
    def dimension(self):
        self.dimension_calls += 1
        raise RuntimeError("model exploded (simulated OOM)")

    def embed(self, text):
        return self.embed_many([text])[0]

    def embed_many(self, texts):
        self.embed_calls += 1
        raise RuntimeError("model exploded (simulated OOM)")


class _WorkingPrimary:
    dimension = 3

    def __init__(self):
        self.embed_calls = 0

    def embed(self, text):
        return self.embed_many([text])[0]

    def embed_many(self, texts):
        self.embed_calls += 1
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_failure_engages_hashed_fallback_and_caches_it():
    primary = _FailingPrimary()
    fallback = HashedBagOfWordsEmbedding()
    provider = ResilientEmbeddingProvider(primary, fallback)

    first = provider.embed("does the hotel have a pool?")
    assert provider.primary_failed is True
    # The answer really is the hashed provider's vector.
    assert first == fallback.embed("does the hotel have a pool?")
    assert len(first) == fallback.dimension

    # Second call must NOT retry the primary.
    second = provider.embed_many(["spa timings", "airport shuttle"])
    assert second == fallback.embed_many(["spa timings", "airport shuttle"])
    assert primary.embed_calls == 1


def test_dimension_falls_back_after_primary_failure():
    primary = _FailingPrimary()
    fallback = HashedBagOfWordsEmbedding()
    provider = ResilientEmbeddingProvider(primary, fallback)

    assert provider.dimension == fallback.dimension
    assert provider.primary_failed is True
    # Cached: the primary's dimension is not probed again.
    assert provider.dimension == fallback.dimension
    assert primary.dimension_calls == 1


def test_working_primary_passes_through_untouched():
    primary = _WorkingPrimary()
    provider = ResilientEmbeddingProvider(primary, HashedBagOfWordsEmbedding())

    assert provider.dimension == 3
    assert provider.embed("hello") == [1.0, 0.0, 0.0]
    assert provider.embed_many(["a", "b"]) == [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    assert provider.primary_failed is False
    assert primary.embed_calls == 2
