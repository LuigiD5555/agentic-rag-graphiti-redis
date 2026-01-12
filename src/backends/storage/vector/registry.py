"""Registry for vector store backend factories."""

import threading
from typing import Callable, Mapping, Any

from src.workflows.query.interfaces.vector_interface import VectorInterface

VectorStoreFactoryFn = Callable[[Any, Mapping[str, Any], str], VectorInterface]

_lock = threading.RLock()
_factories: dict[str, VectorStoreFactoryFn] = {}


def register_vector_store(name: str, factory: VectorStoreFactoryFn) -> None:
    """
    Register a vector store backend factory under a short name.

    External modules can use this hook to plug new backends (e.g. Chroma).
    """
    normalized = (name or "").strip().lower()
    if not normalized:
        raise ValueError("Vector store name must be non-empty")
    if not callable(factory):
        raise TypeError("Vector store factory must be callable")
    with _lock:
        _factories[normalized] = factory


def get_vector_store_factory(name: str) -> VectorStoreFactoryFn:
    normalized = (name or "").strip().lower()
    with _lock:
        if normalized not in _factories:
            available = ", ".join(sorted(_factories.keys())) or "<none>"
            raise KeyError(f"Unknown vector backend '{normalized}'. Available: {available}")
        return _factories[normalized]


def list_vector_stores() -> list[str]:
    with _lock:
        return sorted(_factories.keys())


def reset_vector_store_registry() -> None:  # pragma: no cover
    with _lock:
        _factories.clear()
