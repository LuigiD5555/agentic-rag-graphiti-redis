from __future__ import annotations

from typing import Any, Mapping

from src.rag.interfaces.graph_interface import GraphInterface


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
        GRAPH_STORES = {"default": {"BACKEND": "neo4j"}}
    """
    store_cfg = _graph_settings(config, alias)
    backend = (store_cfg.get("BACKEND") or "neo4j").lower()

    if backend == "neo4j":
        if "ENGINE" in store_cfg:
            raise ValueError("Use BACKEND (whitelisted) instead of ENGINE (import path)")
        from src.storage.graph.neo4j_repository import Neo4jRepository

        update: dict[str, Any] = {}
        for key, value in store_cfg.items():
            if key == "BACKEND":
                continue
            if key == "URI":
                update["NEO4J_URI"] = value
                continue
            if key == "USER":
                update["NEO4J_USER"] = value
                continue
            if key == "PASSWORD":
                update["NEO4J_PASSWORD"] = value
                continue
            raise ValueError(f"Unsupported graph setting '{key}'")

        cfg = config.model_copy(update=update) if update else config
        return Neo4jRepository(cfg)

    if backend in {"null", "noop", "disabled"}:
        from src.storage.graph.null_repository import NullGraphRepository

        extra = set(store_cfg.keys()) - {"BACKEND"}
        if extra:
            raise ValueError(f"Unsupported graph setting(s) for '{backend}': {', '.join(sorted(extra))}")
        return NullGraphRepository()

    raise ValueError(f"Unsupported graph BACKEND: {backend}")


__all__ = ["get_graph_store"]
