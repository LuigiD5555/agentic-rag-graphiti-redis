from __future__ import annotations

from src.interfaces.vector_interface import SupportsExists, VectorInterface


def vector_store_contains(vector_store: VectorInterface, hash_id: str) -> bool:
    if isinstance(vector_store, SupportsExists):
        try:
            return vector_store.exists(hash_id)
        except (AttributeError, NotImplementedError, TypeError):
            return False
    return False


__all__ = ["vector_store_contains"]
