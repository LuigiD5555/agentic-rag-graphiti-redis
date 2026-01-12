"""Document splitting and chunking utilities.

This module provides utilities for splitting documents into chunks for embedding,
with support for various splitting strategies and progress tracking.
"""

from typing import Any, Dict, List, Tuple

from langchain_core.documents import Document

from src.workflows.query.audit import get_logger

logger = get_logger(__name__)


def prepare_embedding_segments(chunks: List[Document], limit: int) -> List[Tuple[str, Dict[str, Any]]]:
    """Split oversized chunks into smaller segments before embedding.

    Args:
        chunks: List of document chunks.
        limit: Token limit for each segment.

    Returns:
        List of (text, metadata) tuples ready for embedding.
    """
    from src.utils.text import effective_limit

    effective = effective_limit(limit)
    if effective <= 0:
        return [
            (chunk.page_content or "", dict(getattr(chunk, "metadata") or {}))
            for chunk in chunks
        ]

    segments: List[Tuple[str, Dict[str, Any]]] = []
    for chunk in chunks:
        content = chunk.page_content or ""
        metadata = dict(getattr(chunk, "metadata") or {})
        tokens = content.split()
        if not tokens:
            segments.append((content, metadata))
            continue
        if len(tokens) <= effective:
            segments.append((content, metadata))
            continue

        segments_created = 0
        start = 0
        while start < len(tokens):
            end = min(start + effective, len(tokens))
            segments.append((" ".join(tokens[start:end]), metadata))
            start = end
            segments_created += 1

        source = metadata.get("source") or metadata.get("file_path") or "document"
        logger.debug(
            "Chunk from %s split into %d segments to honor %d-token embedding limit.",
            source,
            segments_created,
            effective,
        )

    return segments


__all__ = ["prepare_embedding_segments"]
