"""Hotel-knowledge RAG subsystem.

Covers: chunking, deterministic local embeddings, ingestion, hotel-scoped
retrieval (tenant isolation), empty-store handling, the
``search_hotel_knowledge`` tool (context-resolved hotel_id, arg validation),
and the routing guarantee that RAG is never consulted for
price/availability questions.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

from app.agent.tools.registry import ToolContext, build_registry
from app.db.session import get_db
from app.knowledge import (
    HashedBagOfWordsEmbedding,
    KnowledgeRepository,
    Retriever,
    SentenceTransformerEmbedding,
    chunk_text,
    cosine_similarity,
    default_embedding_provider,
)
from tests._helpers import (
    client,
    future,
    make_hotel,
    make_room,
    ok,
    seed_rates_availability,
    uid,
)


def _db():
    return next(get_db())


def _repo(db):
    return KnowledgeRepository(db, default_embedding_provider())


def _chat(hotel_id, message, **kw):
    r = client.post("/api/v1/agent/chat", json={"hotel_id": hotel_id, "message": message, **kw})
    ok(r, 200)
    return r.json()


# --------------------------------------------------------------------- #
# chunking                                                               #
# --------------------------------------------------------------------- #
def test_chunking_overlapping_windows():
    words = [f"w{i}" for i in range(10)]
    chunks = chunk_text(" ".join(words), chunk_size=4, overlap=2)
    assert chunks == [
        "w0 w1 w2 w3",
        "w2 w3 w4 w5",
        "w4 w5 w6 w7",
        "w6 w7 w8 w9",
    ]
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=0)
    # Oversized overlap is clamped and still terminates covering the tail.
    chunks = chunk_text(" ".join(words), chunk_size=3, overlap=99)
    assert chunks[-1].split()[-1] == "w9"


# --------------------------------------------------------------------- #
# embeddings                                                             #
# --------------------------------------------------------------------- #
def test_embeddings_deterministic_and_normalized():
    emb = HashedBagOfWordsEmbedding(dimension=64)
    vec1 = emb.embed("spa massage sauna")
    vec2 = emb.embed("spa massage sauna")
    assert vec1 == vec2  # deterministic
    assert len(vec1) == emb.dimension == 64
    norm = sum(v * v for v in vec1) ** 0.5
    assert norm == pytest.approx(1.0)
    assert cosine_similarity(vec1, vec1) == pytest.approx(1.0)
    # Texts sharing tokens are more similar than disjoint ones.
    related = emb.embed("spa massage wellness treatments")
    unrelated = emb.embed("airport transfer taxi shuttle")
    assert cosine_similarity(vec1, related) > cosine_similarity(vec1, unrelated)
    with pytest.raises(ValueError):
        HashedBagOfWordsEmbedding(dimension=0)


# --------------------------------------------------------------------- #
# ingestion                                                              #
# --------------------------------------------------------------------- #
def test_ingest_document_creates_chunks_and_embeddings():
    hotel = make_hotel()
    db = _db()
    try:
        repo = _repo(db)
        content = " ".join(f"word{i}" for i in range(300))
        doc = repo.create_document(
            hotel_id=hotel["id"], title=uid("Doc"), content=content, source="test"
        )
        db.commit()
        assert doc.id is not None
        assert doc.hotel_id == hotel["id"]
        assert doc.created_at.tzinfo is not None  # tz-aware timestamp
        chunks = repo.list_chunks(hotel["id"])
        assert len(chunks) > 1
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        assert all(c.hotel_id == hotel["id"] for c in chunks)
        assert all(len(c.embedding) == 256 for c in chunks)
        assert repo.document_exists(hotel["id"], doc.title) is True
        assert repo.document_exists(hotel["id"], "no such title") is False
    finally:
        db.close()


def test_document_crud_is_hotel_scoped():
    hotel_a = make_hotel()
    hotel_b = make_hotel()
    db = _db()
    try:
        repo = _repo(db)
        doc = repo.create_document(
            hotel_id=hotel_a["id"],
            title=uid("ScopedDoc"),
            content="secret knowledge for hotel A",
        )
        db.commit()
        # Hotel B cannot see or delete hotel A's document.
        assert repo.get_document(hotel_b["id"], doc.id) is None
        assert repo.get_document(hotel_a["id"], doc.id) is not None
        assert repo.delete_document(hotel_b["id"], doc.id) is False
        assert repo.delete_document(hotel_a["id"], doc.id) is True
        assert repo.list_chunks(hotel_a["id"]) == []
        assert repo.delete_document(hotel_a["id"], doc.id) is False
    finally:
        db.close()


# --------------------------------------------------------------------- #
# retrieval                                                              #
# --------------------------------------------------------------------- #
def _seed_three_docs(hotel_id):
    db = _db()
    try:
        repo = _repo(db)
        repo.create_document(
            hotel_id=hotel_id,
            title="Spa and wellness",
            content=(
                "Our Serenity Spa offers aromatherapy massage, deep-tissue "
                "massage and hot-stone therapy daily from 9 AM to 9 PM. The "
                "sauna, steam room and plunge pool are complimentary."
            ),
            source="test",
        )
        repo.create_document(
            hotel_id=hotel_id,
            title="Restaurants and dining",
            content=(
                "Saffron Court serves a breakfast buffet from 7 AM with live "
                "dosa counters, and dinner with themed nights. Azure rooftop "
                "serves pan-Asian cuisine until 11:30 PM."
            ),
            source="test",
        )
        repo.create_document(
            hotel_id=hotel_id,
            title="Airport transfers",
            content=(
                "A complimentary shuttle runs every 30 minutes to the airport "
                "terminal. Private sedan and SUV transfers can be arranged at "
                "the front desk with two hours notice."
            ),
            source="test",
        )
        db.commit()
    finally:
        db.close()


def test_retrieval_returns_relevant_chunk():
    hotel = make_hotel()
    _seed_three_docs(hotel["id"])
    db = _db()
    try:
        retriever = Retriever(_repo(db), default_embedding_provider())
        results = retriever.search(
            hotel_id=hotel["id"],
            query="What spa treatments and massage do you offer?",
            top_k=2,
        )
        assert results
        assert len(results) <= 2
        assert results[0].document_title == "Spa and wellness"
        assert results[0].score > 0
        assert "aromatherapy" in results[0].content
    finally:
        db.close()


def test_hotel_isolation_retriever():
    hotel_a = make_hotel()
    hotel_b = make_hotel()
    db = _db()
    try:
        repo = _repo(db)
        repo.create_document(
            hotel_id=hotel_a["id"],
            title="A Spa Guide",
            content="Hotel A serenity spa offers aromatherapy massage and sauna.",
            source="test",
        )
        repo.create_document(
            hotel_id=hotel_b["id"],
            title="B Observatory",
            content="Hotel B rooftop observatory stargazing telescope midnight astronomy.",
            source="test",
        )
        db.commit()
        retriever = Retriever(repo, default_embedding_provider())

        results_a = retriever.search(hotel_id=hotel_a["id"], query="spa", top_k=5)
        assert results_a, "hotel A should retrieve its own spa chunk"
        assert all(r.document_title == "A Spa Guide" for r in results_a)
        assert all("observatory" not in r.content for r in results_a)

        # Hotel B's exclusive content is retrievable by B, never by A.
        results_b = retriever.search(
            hotel_id=hotel_b["id"], query="observatory stargazing telescope", top_k=5
        )
        assert any(r.document_title == "B Observatory" for r in results_b)
        results_a2 = retriever.search(
            hotel_id=hotel_a["id"], query="observatory stargazing telescope", top_k=5
        )
        assert all(r.document_title != "B Observatory" for r in results_a2)
    finally:
        db.close()


def test_empty_store_returns_no_results():
    hotel = make_hotel()
    db = _db()
    try:
        retriever = Retriever(_repo(db), default_embedding_provider())
        assert retriever.search(hotel_id=hotel["id"], query="spa") == []
        assert retriever.search(hotel_id=hotel["id"], query="   ") == []
    finally:
        db.close()


def test_non_ready_documents_are_never_retrieved():
    """Chunks of processing/failed documents are excluded from retrieval."""
    hotel = make_hotel()
    db = _db()
    try:
        repo = _repo(db)
        content = "The serenity spa offers aromatherapy massage and cedar sauna sessions daily."
        repo.create_document(
            hotel_id=hotel["id"], title="Ready spa guide", content=content, source="test"
        )
        processing_doc = repo.create_pending_document(
            hotel_id=hotel["id"], title="Half-ingested draft", source="test"
        )
        # Simulate chunks that exist while the document is still processing
        # (the background-job window): they must not be retrievable.
        repo.ingest_content(document=processing_doc, content=content)
        repo.set_document_status(
            hotel_id=hotel["id"], document_id=processing_doc.id, status="processing"
        )
        failed_doc = repo.create_document(
            hotel_id=hotel["id"], title="Broken doc", content=content, source="test"
        )
        repo.set_document_status(
            hotel_id=hotel["id"], document_id=failed_doc.id, status="failed", error="boom"
        )
        db.commit()

        retriever = Retriever(repo, default_embedding_provider())
        results = retriever.search(hotel_id=hotel["id"], query="spa aromatherapy", top_k=10)
        assert results, "the ready document should still be retrievable"
        titles = {r.document_title for r in results}
        assert "Ready spa guide" in titles
        assert "Half-ingested draft" not in titles
        assert "Broken doc" not in titles

        # And through the agent tool: only the ready document's content.
        registry = build_registry()
        ctx = ToolContext(hotel_id=hotel["id"], channel="web")
        tool_result = registry.execute(
            "search_hotel_knowledge", {"query": "spa aromatherapy", "top_k": 10}, db, ctx
        )
        assert tool_result.ok is True
        tool_titles = {r["title"] for r in tool_result.data["results"]}
        assert "Ready spa guide" in tool_titles
        assert "Half-ingested draft" not in tool_titles
        assert "Broken doc" not in tool_titles
    finally:
        db.close()


# --------------------------------------------------------------------- #
# agent tool                                                             #
# --------------------------------------------------------------------- #
def test_tool_registered_and_read_only():
    registry = build_registry()
    assert "search_hotel_knowledge" in registry.names
    spec = next(s for s in registry._tools.values() if s.name == "search_hotel_knowledge")
    assert spec.read_only is True


def test_tool_resolves_hotel_from_context_not_llm_args():
    hotel_a = make_hotel()
    hotel_b = make_hotel()
    _seed_three_docs(hotel_a["id"])
    db = _db()
    try:
        registry = build_registry()
        # Even if the LLM smuggles a hotel_id into the arguments, it is
        # ignored: the schema has no hotel_id field and the handler uses ctx.
        res = registry.execute(
            "search_hotel_knowledge",
            {"query": "spa treatments massage", "hotel_id": hotel_b["id"]},
            db,
            ToolContext(hotel_id=hotel_a["id"]),
        )
        assert res.ok is True
        assert res.data["results"], "hotel A's chunks must be returned"
        titles = {r["title"] for r in res.data["results"]}
        assert "Spa and wellness" in titles

        # Same query under hotel B's context finds nothing (B has no docs).
        res_b = registry.execute(
            "search_hotel_knowledge",
            {"query": "spa treatments massage"},
            db,
            ToolContext(hotel_id=hotel_b["id"]),
        )
        assert res_b.ok is True
        assert res_b.data["results"] == []
    finally:
        db.close()


def test_tool_rejects_empty_query():
    hotel = make_hotel()
    db = _db()
    try:
        registry = build_registry()
        ctx = ToolContext(hotel_id=hotel["id"])
        for bad in ("", "   "):
            res = registry.execute("search_hotel_knowledge", {"query": bad}, db, ctx)
            assert res.ok is False, f"empty query {bad!r} must fail safely"
            assert res.error
    finally:
        db.close()


def test_tool_top_k_validation():
    hotel = make_hotel()
    db = _db()
    try:
        registry = build_registry()
        res = registry.execute(
            "search_hotel_knowledge",
            {"query": "spa", "top_k": 0},
            db,
            ToolContext(hotel_id=hotel["id"]),
        )
        assert res.ok is False
    finally:
        db.close()


# --------------------------------------------------------------------- #
# routing: RAG is never consulted for price / availability               #
# --------------------------------------------------------------------- #
def test_rag_not_consulted_for_price_question():
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type=uid("DeluxePx"), capacity=2, total_rooms=5)
    start = future(60)
    seed_rates_availability(room["id"], start, 2, price=2500, available=5)
    _seed_three_docs(hotel["id"])  # knowledge exists; still must not be used
    end = start + timedelta(days=2)
    body = _chat(hotel["id"], f"What is the price for {room['room_type']} from {start} to {end}?")
    tools = [t["tool"] for t in body["tool_trace"]]
    assert "get_room_rate" in tools
    assert "search_hotel_knowledge" not in tools


def test_rag_not_consulted_for_availability_question():
    hotel = make_hotel()
    room = make_room(hotel["id"], room_type=uid("DeluxeAv"), capacity=2, total_rooms=5)
    start = future(60)
    seed_rates_availability(room["id"], start, 2, price=2500, available=5)
    _seed_three_docs(hotel["id"])
    end = start + timedelta(days=2)
    body = _chat(hotel["id"], f"Is {room['room_type']} available from {start} to {end}?")
    tools = [t["tool"] for t in body["tool_trace"]]
    assert "check_room_availability" in tools
    assert "search_hotel_knowledge" not in tools


def test_knowledge_question_uses_rag_end_to_end():
    hotel = make_hotel()
    db = _db()
    try:
        _repo(db).create_document(
            hotel_id=hotel["id"],
            title="Spa and wellness",
            content=(
                "Our Serenity Spa offers aromatherapy massage, deep-tissue "
                "massage and hot-stone therapy daily from 9 AM to 9 PM."
            ),
            source="test",
        )
        db.commit()
    finally:
        db.close()
    body = _chat(hotel["id"], "Tell me about your spa treatments")
    tools = [t["tool"] for t in body["tool_trace"]]
    assert "search_hotel_knowledge" in tools
    assert "aromatherapy" in body["reply"].lower()


def test_knowledge_question_with_empty_store_degrades_gracefully():
    hotel = make_hotel()
    body = _chat(hotel["id"], "Tell me about your sauna")
    tools = [t["tool"] for t in body["tool_trace"]]
    assert "search_hotel_knowledge" in tools
    assert body["reply"]  # a polite fallback, not a crash


# --------------------------------------------------------------------- #
# seed script                                                            #
# --------------------------------------------------------------------- #
def _load_seed_module():
    import importlib.util

    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "seed_knowledge.py")
    spec = importlib.util.spec_from_file_location("seed_knowledge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_script_is_idempotent():
    hotel = make_hotel()
    mod = _load_seed_module()
    first = mod.seed_hotel_knowledge(hotel["id"])
    assert first == {"created": 5, "skipped": 0}
    second = mod.seed_hotel_knowledge(hotel["id"])
    assert second == {"created": 0, "skipped": 5}
    db = _db()
    try:
        docs = _repo(db).list_documents(hotel["id"])
        assert len(docs) == 5
        titles = {d.title for d in docs}
        assert "Spa and wellness" in titles
        assert "Airport pickup and transfers" in titles
        # Every seeded doc produced chunks.
        assert _repo(db).count_chunks(hotel["id"]) >= 5
    finally:
        db.close()


# --------------------------------------------------------------------- #
# SentenceTransformerEmbedding (unit tests use a fake encoder so the    #
# suite never downloads the real model; see tests/conftest.py)          #
# --------------------------------------------------------------------- #
class _FakeSentenceTransformer:
    """Stand-in for ``sentence_transformers.SentenceTransformer`` (no torch)."""

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        return [[float(len(text)), 1.0, 0.0] for text in texts]


def test_sentence_transformer_embedding_implements_protocol(monkeypatch):
    import app.knowledge.embeddings as embeddings_mod

    seen = {}

    def _fake_loader(model_name):
        seen["model_name"] = model_name
        return _FakeSentenceTransformer()

    monkeypatch.setattr(embeddings_mod, "_load_sentence_transformer", _fake_loader)
    provider = SentenceTransformerEmbedding(model_name="fake-model")

    # The model name is honoured but nothing is loaded until first use.
    assert seen == {}
    assert provider.model_name == "fake-model"
    assert provider.dimension == 3
    assert seen["model_name"] == "fake-model"

    vec = provider.embed("hello")
    assert vec == [5.0, 1.0, 0.0]
    assert all(isinstance(v, float) for v in vec)

    # Batch order matches the input order.
    batch = provider.embed_many(["a", "abcd"])
    assert batch == [[1.0, 1.0, 0.0], [4.0, 1.0, 0.0]]

    # embed_many delegates to a single encoder call (one model.encode).
    calls = []
    fake = _FakeSentenceTransformer()
    orig_encode = fake.encode

    def _recording_encode(texts, **kwargs):
        calls.append(list(texts))
        return orig_encode(texts, **kwargs)

    fake.encode = _recording_encode
    monkeypatch.setattr(embeddings_mod, "_load_sentence_transformer", lambda name: fake)
    SentenceTransformerEmbedding(model_name="fake-model").embed_many(["x", "yy"])
    assert calls == [["x", "yy"]]


def test_sentence_transformer_rejects_empty_model_name():
    with pytest.raises(ValueError):
        SentenceTransformerEmbedding(model_name="")
    with pytest.raises(ValueError):
        SentenceTransformerEmbedding(model_name="   ")


def test_sentence_transformer_missing_dependency_message(monkeypatch):
    import sys

    import app.knowledge.embeddings as embeddings_mod

    # Pretend sentence-transformers is not installed: the import inside the
    # loader must raise ImportError (None in sys.modules halts the import).
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    embeddings_mod._model_cache.pop("missing-dep-model", None)
    with pytest.raises(ImportError, match="EMBEDDING_PROVIDER=hashed"):
        SentenceTransformerEmbedding(model_name="missing-dep-model").embed("x")


def test_default_embedding_provider_selection(monkeypatch):
    from types import SimpleNamespace

    import app.knowledge as knowledge_pkg

    monkeypatch.setattr(
        knowledge_pkg,
        "get_settings",
        lambda: SimpleNamespace(embedding_provider="hashed", embedding_model="x"),
    )
    assert isinstance(knowledge_pkg.default_embedding_provider(), HashedBagOfWordsEmbedding)

    # The sentence-transformer provider is constructed without loading the
    # model, so this stays fast and offline in unit tests.
    monkeypatch.setattr(
        knowledge_pkg,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_provider="sentence-transformer",
            embedding_model="all-MiniLM-L6-v2",
        ),
    )
    provider = knowledge_pkg.default_embedding_provider()
    assert isinstance(provider, SentenceTransformerEmbedding)
    assert provider.model_name == "all-MiniLM-L6-v2"


# --------------------------------------------------------------------- #
# slow integration tests: real all-MiniLM-L6-v2 model.                   #
# The default `pytest` run skips these (`-m 'not slow'` in addopts);     #
# run them with `pytest -m slow`. The model downloads once (~90 MB)      #
# on first run into the Hugging Face cache, then runs fully offline.     #
# --------------------------------------------------------------------- #
@pytest.mark.slow
def test_sentence_transformer_end_to_end_retrieval():
    provider = SentenceTransformerEmbedding()  # loads the real local model
    assert provider.dimension == 384  # all-MiniLM-L6-v2
    hotel = make_hotel()
    db = _db()
    try:
        repo = KnowledgeRepository(db, provider)
        repo.create_document(
            hotel_id=hotel["id"],
            title="Spa and wellness",
            content=(
                "Our Serenity Spa offers aromatherapy massage, deep-tissue "
                "massage and hot-stone therapy daily from 9 AM to 9 PM."
            ),
            source="test",
        )
        repo.create_document(
            hotel_id=hotel["id"],
            title="Airport transfers",
            content=("A complimentary shuttle runs every 30 minutes to the airport terminal."),
            source="test",
        )
        db.commit()
        assert all(len(c.embedding) == 384 for c in repo.list_chunks(hotel["id"]))

        retriever = Retriever(repo, provider)
        results = retriever.search(
            hotel_id=hotel["id"],
            query="What spa treatments and massage do you offer?",
            top_k=2,
        )
        assert results, "expected the spa chunk to be retrieved"
        assert results[0].document_title == "Spa and wellness"
        assert "aromatherapy" in results[0].content
    finally:
        db.close()


_FAQ_DOCS = [
    (
        "Check-in and check-out",
        "Guests may check in from 2 PM. Check-out is at 11 AM. Early check-in "
        "can be arranged on request, subject to room availability.",
    ),
    (
        "Parking",
        "Complimentary valet parking is available in the basement garage for "
        "all in-house guests. Self-parking is also available on level B2.",
    ),
    (
        "Spa and wellness",
        "Our Serenity Spa offers aromatherapy massage, deep-tissue massage "
        "and hot-stone therapy daily from 9 AM to 9 PM.",
    ),
    (
        "Pet policy",
        "Pets are not permitted in guest rooms, with the exception of "
        "registered service animals accompanying their owners.",
    ),
    (
        "Rooftop pool",
        "The rooftop infinity pool is open daily from 7 AM to 7 PM. Towels "
        "are provided; children must be supervised at all times.",
    ),
]

# (guest phrasing, expected document title). The phrasings deliberately use
# synonyms/paraphrases with little token overlap, where hashed bag-of-words
# struggles and a semantic model should win.
_FAQ_QUERIES = [
    ("When can I arrive and get my room key?", "Check-in and check-out"),
    ("Where can I leave my car overnight?", "Parking"),
    ("Do you offer massages?", "Spa and wellness"),
    ("Can I bring my dog to the hotel?", "Pet policy"),
    ("pool opening hours", "Rooftop pool"),
]


def _rank_of(retriever, hotel_id, query, expected_title, top_k=5):
    """1-based rank of the expected document, or None if not retrieved."""
    results = retriever.search(hotel_id=hotel_id, query=query, top_k=top_k)
    for rank, hit in enumerate(results, start=1):
        if hit.document_title == expected_title:
            return rank
    return None


@pytest.mark.slow
def test_sentence_transformer_retrieval_quality_vs_hashed_baseline():
    """Hand-picked FAQ queries: the semantic model must retrieve the right
    chunk (top-3) and rank it no worse than the hashed baseline."""
    st_provider = SentenceTransformerEmbedding()  # real local model
    hashed_provider = HashedBagOfWordsEmbedding()
    hotel_st = make_hotel()
    hotel_hashed = make_hotel()
    db = _db()
    try:
        for title, content in _FAQ_DOCS:
            KnowledgeRepository(db, st_provider).create_document(
                hotel_id=hotel_st["id"], title=title, content=content, source="test"
            )
            KnowledgeRepository(db, hashed_provider).create_document(
                hotel_id=hotel_hashed["id"], title=title, content=content, source="test"
            )
        db.commit()
        st_retriever = Retriever(KnowledgeRepository(db, st_provider), st_provider)
        hashed_retriever = Retriever(KnowledgeRepository(db, hashed_provider), hashed_provider)

        for query, expected in _FAQ_QUERIES:
            rank_st = _rank_of(st_retriever, hotel_st["id"], query, expected)
            rank_hashed = _rank_of(hashed_retriever, hotel_hashed["id"], query, expected)
            assert rank_st is not None, (
                f"sentence-transformer failed to retrieve {expected!r} for {query!r}"
            )
            assert rank_st <= 3, (
                f"sentence-transformer ranked {expected!r} at {rank_st} for {query!r}"
            )
            if rank_hashed is not None:
                assert rank_st <= rank_hashed, (
                    f"sentence-transformer rank {rank_st} worse than hashed "
                    f"rank {rank_hashed} for {query!r}"
                )
    finally:
        db.close()
