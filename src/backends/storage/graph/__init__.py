from typing import Any, Mapping
from urllib.parse import urlparse

from src.workflows.query.interfaces.graph_interface import GraphInterface
from .registry import ensure_builtin_graph_backends_loaded, get_graph_backend_factory


def _graph_settings(config, alias: str) -> Mapping[str, Any]:
    stores = getattr(config, "GRAPH_STORES", None) or {}
    if not isinstance(stores, dict):
        raise TypeError("Config.GRAPH_STORES must be a dict mapping aliases to dict settings")
    if alias not in stores:
        available = ", ".join(sorted(stores.keys())) or "<none>"
        raise KeyError(f"Unknown GRAPH_STORES alias '{alias}'. Available: {available}")
    store_cfg = stores[alias]
    if not isinstance(store_cfg, dict):
        raise TypeError(f"Config.GRAPH_STORES['{alias}'] must be a dict of settings")
    return store_cfg


def get_graph_store(config, alias: str = "default") -> GraphInterface:
    """
    Create the graph store backend selected in settings.

    Django-like usage:
        GRAPH_STORES = {"default": {"ENGINE": "neo4j"}}
    """
    store_cfg = dict(_graph_settings(config, alias))
    
    # Normalize URI/URL configuration
    if "URI" not in store_cfg and "URL" not in store_cfg:
        host = store_cfg.get("HOST")
        port = store_cfg.get("PORT")
        scheme = store_cfg.get("SCHEME") or "bolt"
        if host or port:
            host = host or "localhost"
            port = port or 7687
            store_cfg["URI"] = f"{scheme}://{host}:{port}"
        else:
            parsed = urlparse(getattr(config, "NEO4J_URI", ""))
            if parsed.scheme and parsed.hostname:
                store_cfg.setdefault("HOST", parsed.hostname)
                store_cfg.setdefault("PORT", parsed.port)
                store_cfg.setdefault("SCHEME", parsed.scheme)

    # Get backend name
    backend = (store_cfg.get("BACKEND") or store_cfg.get("ENGINE") or "neo4j").lower()
    
    # Ensure built-in backends are loaded
    ensure_builtin_graph_backends_loaded()
    
    # Get factory from registry
    factory = get_graph_backend_factory(backend)
    
    # Create and return backend instance
    return factory(config, store_cfg)


__all__ = ["get_graph_store"]
