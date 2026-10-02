"""Hotel-knowledge RAG tool (Phase 2).

``search_hotel_knowledge`` answers guest questions from the hotel's
unstructured knowledge base: handbook, check-in instructions, parking,
spa, airport transfers, restaurant descriptions, long-form policy
explanations, local guides, accessibility info.

Hard boundary: this tool is NEVER used for availability, prices, bookings,
guest records, orders, or payment state — those stay SQL/tool operations.

``hotel_id`` is resolved from the tool context only. The argument schema has
no ``hotel_id`` field, so the LLM cannot supply (or spoof) one, and the
retriever additionally filters every chunk row by it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.tools.registry import ToolContext, ToolSpec
from app.knowledge import (
    KnowledgeRepository,
    Retriever,
    default_embedding_provider,
)


class SearchHotelKnowledgeArgs(BaseModel):
    query: str = Field(
        description=(
            "The guest's knowledge question in their own words, "
            "e.g. 'What spa treatments do you offer?'"
        ),
    )
    top_k: int = Field(
        default=3,
        ge=1,
        le=10,
        description="How many knowledge chunks to retrieve",
    )


def search_hotel_knowledge(
    db: Session, ctx: ToolContext, args: SearchHotelKnowledgeArgs
) -> dict[str, Any]:
    query = args.query.strip()
    if not query:
        raise ValueError("query must not be empty")
    embedding = default_embedding_provider()
    retriever = Retriever(KnowledgeRepository(db, embedding), embedding)
    # hotel_id comes from the channel context, never from LLM arguments.
    results = retriever.search(hotel_id=ctx.hotel_id, query=query, top_k=args.top_k)
    return {
        "query": query,
        "results": [
            {
                "document_id": r.document_id,
                "title": r.document_title,
                "content": r.content,
                "score": round(r.score, 4),
            }
            for r in results
        ],
    }


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="search_hotel_knowledge",
        description=(
            "Search the hotel's unstructured knowledge base (handbook, spa, "
            "restaurant, airport transfers, check-in instructions, local "
            "guides, long-form policy explanations). Use for general "
            "knowledge questions ONLY — NEVER for prices, availability, "
            "bookings, guest records, orders, or payments; those have "
            "dedicated tools."
        ),
        args_model=SearchHotelKnowledgeArgs,
        handler=search_hotel_knowledge,
        read_only=True,
    ),
]

__all__ = ["SPECS", "search_hotel_knowledge"]
