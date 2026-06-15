"""
Built-in graph storage backends.

This module registers the built-in graph backends using the decorator pattern.
"""

from src.backends.storage.graph.registry import (
    register_graph_backend,
    register_graph_backend_alias,
)


@register_graph_backend("neo4j")
def build_neo4j_graph_backend(config, store_cfg):
    """
    Build a Neo4j graph backend.
    
    Args:
        config: Application configuration
        store_cfg: Graph store configuration dictionary
        
    Returns:
        Neo4jRepository instance
    """
    from src.backends.storage.graph.neo4j_repository import Neo4jRepository
    
    # Transform Django-like settings to Neo4j-specific settings
    update = {}
    for key, value in store_cfg.items():
        if key in {
            "BACKEND",
            "ENGINE",
            "OPTIONS",
            "NAME",
            "AUTOCOMMIT",
            "ATOMIC_REQUESTS",
            "CONN_MAX_AGE",
            "CONN_HEALTH_CHECKS",
            "TIME_ZONE",
            "TEST",
        }:
            continue
        if key in {"URI", "URL"}:
            update["NEO4J_URI"] = value
            continue
        if key == "USER":
            update["NEO4J_USER"] = value
            continue
        if key == "PASSWORD":
            update["NEO4J_PASSWORD"] = value
            continue
        if key == "HOST":
            host = str(value or "").strip() or "localhost"
            port = store_cfg.get("PORT") or 7687
            scheme = store_cfg.get("SCHEME") or "bolt"
            update["NEO4J_URI"] = f"{scheme}://{host}:{port}"
            continue
        if key == "PORT":
            host = store_cfg.get("HOST") or "localhost"
            scheme = store_cfg.get("SCHEME") or "bolt"
            update["NEO4J_URI"] = f"{scheme}://{host}:{value}"
            continue
        raise ValueError(f"Unsupported graph setting '{key}'")
    
    cfg = config.copy(update=update) if update else config
    return Neo4jRepository(cfg)


@register_graph_backend("null")
def build_null_graph_backend(config, store_cfg):
    """
    Build a null/no-op graph backend.
    
    Args:
        config: Application configuration (unused)
        store_cfg: Graph store configuration dictionary
        
    Returns:
        NullGraphRepository instance
        
    Raises:
        ValueError: If extra settings are provided for null backend
    """
    from src.backends.storage.graph.null_repository import NullGraphRepository
    
    # Validate that no extra settings are provided for null backend
    extra = set(store_cfg.keys()) - {"BACKEND"}
    if extra:
        raise ValueError(f"Unsupported graph setting(s) for 'null': {', '.join(sorted(extra))}")
    
    return NullGraphRepository()


# Register aliases for null backend
register_graph_backend_alias("noop", "null")
register_graph_backend_alias("disabled", "null")