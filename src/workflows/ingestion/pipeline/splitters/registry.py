"""
Registry for text splitter strategies with decorator pattern.

This module provides a registry system for text splitter strategies,
allowing registration via decorators and lookup by strategy name.
"""

import threading
from typing import Callable, Dict, Any, Optional

from .strategies import SplitterStrategy


# Type alias for splitter factory functions
SplitterFactory = Callable[[Any, Optional[object]], object]

_lock = threading.RLock()
_factories: Dict[SplitterStrategy, SplitterFactory] = {}


def register_splitter(strategy: SplitterStrategy) -> Callable[[SplitterFactory], SplitterFactory]:
    """
    Decorator to register a text splitter factory.
    
    Args:
        strategy: Splitter strategy (e.g., SplitterStrategy.RECURSIVE)
        
    Returns:
        Decorator function
        
    Example:
        @register_splitter(SplitterStrategy.RECURSIVE)
        def build_recursive_splitter(options, markdown_levels):
            # ... implementation ...
    """
    def decorator(factory: SplitterFactory) -> SplitterFactory:
        if not callable(factory):
            raise TypeError("Splitter factory must be callable")
        
        with _lock:
            _factories[strategy] = factory
        
        return factory
    return decorator


def get_splitter_factory(strategy: SplitterStrategy) -> SplitterFactory:
    """
    Get a splitter factory by strategy.
    
    Args:
        strategy: Splitter strategy
        
    Returns:
        Splitter factory function
        
    Raises:
        KeyError: If strategy not found
    """
    with _lock:
        if strategy not in _factories:
            available = ", ".join(sorted(s.value for s in _factories.keys())) or "<none>"
            raise KeyError(f"Unknown splitter strategy '{strategy.value}'. Available: {available}")
        
        return _factories[strategy]


def list_splitter_strategies() -> list[SplitterStrategy]:
    """
    List all registered splitter strategies.
    
    Returns:
        List of splitter strategies
    """
    with _lock:
        return sorted(_factories.keys(), key=lambda s: s.value)


def reset_splitter_registry() -> None:
    """
    Reset the splitter registry (for testing).
    
    Warning: This clears all registered splitters.
    """
    with _lock:
        _factories.clear()


# Built-in splitters loader flag
_builtins_loaded = False
_builtins_lock = threading.Lock()


def ensure_builtin_splitters_loaded() -> None:
    """
    Ensure built-in text splitters are loaded.
    
    This function is idempotent and thread-safe.
    """
    global _builtins_loaded
    
    with _builtins_lock:
        if not _builtins_loaded:
            # Import builtins module to trigger registration
            from src.workflows.ingestion.pipeline.splitters import builtins  # noqa: F401
            _builtins_loaded = True