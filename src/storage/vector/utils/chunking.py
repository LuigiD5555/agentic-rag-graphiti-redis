from __future__ import annotations

from typing import Any, Dict, List, Tuple

from src import logger
try:
    from langchain_core.documents import Document
except ImportError:
    from langchain.schema import Document  # type: ignore

from .text_utils import effective_limit


def prepare_embedding_segments(chunks: List[Document], limit: int) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Optionally split oversized chunks into smaller segments before embedding.
    """
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
