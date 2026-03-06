import threading
from typing import Callable

from src.workflows.query.interfaces.provider_adapter_interface import ProviderAdapterInterface


ProviderFactoryFn = Callable[[object], ProviderAdapterInterface]

_lock = threading.RLock()
_providers: dict[str, ProviderFactoryFn] = {}


def register_provider(name: str, factory: ProviderFactoryFn) -> None:
    """
    Register a provider adapter factory under a short name (e.g. "lmstudio").

    This is the extension point for selecting between multiple LLM APIs via
    ProviderAdapterInterface implementations.
    """
    normalized = (name or "").strip().lower()
    if not normalized:
        raise ValueError("Provider name must be non-empty")
    if not callable(factory):
        raise TypeError("Provider factory must be callable")
    with _lock:
        _providers[normalized] = factory


def provider(name: str) -> Callable[[ProviderFactoryFn], ProviderFactoryFn]:
    """
    Decorator to register a provider adapter factory.
    
    Args:
        name: Provider name (e.g., 'lmstudio', 'openai', 'ollama')
        
    Returns:
        Decorator function
        
    Example:
        @provider('lmstudio')
        def build_lmstudio_adapter(config):
            # ... implementation ...
    """
    def decorator(factory: ProviderFactoryFn) -> ProviderFactoryFn:
        register_provider(name, factory)
        return factory
    return decorator


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


# Built-in providers loader flag
_builtins_loaded = False
_builtins_lock = threading.Lock()


def ensure_builtin_providers_loaded() -> None:
    """
    Ensure built-in providers are loaded.
    
    This function is idempotent and thread-safe.
    """
    global _builtins_loaded
    
    with _builtins_lock:
        if not _builtins_loaded:
            # Import builtins module to trigger registration
            from src.backends.llm import builtins  # noqa: F401
            _builtins_loaded = True
