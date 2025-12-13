from __future__ import annotations

import threading
from typing import Callable

from src.rag.interfaces.provider_adapter_interface import ProviderAdapterInterface


ProviderFactoryFn = Callable[[object], ProviderAdapterInterface]

_lock = threading.RLock()
_providers: dict[str, ProviderFactoryFn] = {}


def register_provider(name: str, factory: ProviderFactoryFn) -> None:
    """
    Register a provider adapter factory under a short name (e.g. "lmstudio").

    This is the extension point external apps can use from their AppConfig.ready().
    """
    normalized = (name or "").strip().lower()
    if not normalized:
        raise ValueError("Provider name must be non-empty")
    if not callable(factory):
        raise TypeError("Provider factory must be callable")
    with _lock:
        _providers[normalized] = factory


def get_provider_factory(name: str) -> ProviderFactoryFn:
    normalized = (name or "").strip().lower()
    with _lock:
        if normalized not in _providers:
            available = ", ".join(sorted(_providers.keys())) or "<none>"
            raise KeyError(f"Unknown provider '{normalized}'. Available: {available}")
        return _providers[normalized]


def list_providers() -> list[str]:
    with _lock:
        return sorted(_providers.keys())


def reset_provider_registry() -> None:  # pragma: no cover
    with _lock:
        _providers.clear()
