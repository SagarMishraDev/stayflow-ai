"""Overlapping word-window chunker for hotel knowledge documents.

Long documents (handbook pages, spa brochures, local guides) are split into
fixed-size word windows with an overlap so that context straddling a window
boundary is still retrievable.
"""

from __future__ import annotations


def chunk_text(text: str, chunk_size: int = 120, overlap: int = 20) -> list[str]:
    """Split ``text`` into overlapping word windows.

    Args:
        text: Document text to chunk.
        chunk_size: Maximum words per chunk (must be >= 1).
        overlap: Words shared between consecutive chunks (clamped to
            ``chunk_size - 1``).

    Returns:
        List of chunk strings, in document order. Empty text yields ``[]``.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    words = text.split()
    if not words:
        return []
    overlap = min(max(overlap, 0), chunk_size - 1)
    step = chunk_size - overlap
    chunks: list[str] = []
    start = 0
    while start < len(words):
        chunks.append(" ".join(words[start : start + chunk_size]))
        if start + chunk_size >= len(words):
            break
        start += step
    return chunks
