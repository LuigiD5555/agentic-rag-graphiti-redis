"""
Registry for graph storage backends with decorator pattern.

This module provides a registry system for graph storage backends,
allowing registration via decorators and lookup by backend name.
"""

import threading
from typing import Callable, Dict, Any

from src.workflows.query.interfaces.graph_interface import GraphInterface

# Type alias for graph backend factory functions
GraphBackendFactory = Callable[[object, Dict[str, Any]], GraphInterface]

_lock = threading.RLock()
_factories: Dict[str, GraphBackendFactory] = {}
_aliases: Dict[str, str] = {}


def register_graph_backend(name: str) -> Callable[[GraphBackendFactory], GraphBackendFactory]:
    """
    Decorator to register a graph backend factory.
    
    Args:
        name: Backend name (e.g., 'neo4j', 'null')
        
    Returns:
        Decorator function
        
    Example:
        @register_graph_backend('neo4j')
        def build_neo4j_backend(config, store_cfg):
            # ... implementation ...
    """
    def decorator(factory: GraphBackendFactory) -> GraphBackendFactory:
        normalized = (name or "").strip().lower()
        if not normalized:
            raise ValueError("Graph backend name must be non-empty")
        if not callable(factory):
            raise TypeError("Graph backend factory must be callable")
        
        with _lock:
            _factories[normalized] = factory
        
        return factory
    return decorator


def register_graph_backend_alias(alias: str, target: str) -> None:
    """
    Register an alias for a graph backend.
    
    Args:
        alias: Alias name (e.g., 'noop', 'disabled')
        target: Target backend name (e.g., 'null')
    """
    normalized_alias = (alias or "").strip().lower()
    normalized_target = (target or "").strip().lower()
    
    if not normalized_alias:
        raise ValueError("Alias name must be non-empty")
    if not normalized_target:
        raise ValueError("Target backend name must be non-empty")
    
    with _lock:
        _aliases[normalized_alias] = normalized_target


def get_graph_backend_factory(name: str) -> GraphBackendFactory:
    """
    Get a graph backend factory by name.
    
    Args:
        name: Backend name or alias
        
    Returns:
        Graph backend factory function
        
    Raises:
        KeyError: If backend not found
    """
    normalized = (name or "").strip().lower()
    
    with _lock:
        # Check aliases first
        actual_name = _aliases.get(normalized, normalized)
        
        if actual_name not in _factories:
            available = ", ".join(sorted(_factories.keys())) or "<none>"
            raise KeyError(f"Unknown graph backend '{name}'. Available: {available}")
        
        return _factories[actual_name]


def list_graph_backends() -> list[str]:
    """
    List all registered graph backends.
    
    Returns:
        List of backend names
    """
    with _lock:
        return sorted(_factories.keys())


def list_graph_backend_aliases() -> Dict[str, str]:
    """
    List all registered graph backend aliases.
    
    Returns:
        Dictionary mapping aliases to target backends
    """
    with _lock:
        return _aliases.copy()


def reset_graph_backend_registry() -> None:
    """
    Reset the graph backend registry (for testing).
    
    Warning: This clears all registered backends and aliases.
    """
    with _lock:
        _factories.clear()
        _aliases.clear()


# Built-in backends loader flag
_builtins_loaded = False
_builtins_lock = threading.Lock()


def ensure_builtin_graph_backends_loaded() -> None:
    """
    Ensure built-in graph backends are loaded.
    
    This function is idempotent and thread-safe.
    """
    global _builtins_loaded
    
    with _builtins_lock:
        if not _builtins_loaded:
            # Import builtins module to trigger registration
            from src.backends.storage.graph import builtins  # noqa: F401
            _builtins_loaded = True
