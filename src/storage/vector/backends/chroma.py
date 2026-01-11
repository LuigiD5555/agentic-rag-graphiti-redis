"""Vector store backend implementation for Chroma (stub)."""
from __future__ import annotations

from typing import Any, Mapping

from src.rag.interfaces.vector_interface import VectorInterface


def build_chroma_repository(config: Any, store_cfg: Mapping[str, Any], alias: str) -> VectorInterface:
    """Chroma backend is not implemented yet."""
    raise NotImplementedError("Chroma backend is not implemented yet. Please add a backend implementation.")
