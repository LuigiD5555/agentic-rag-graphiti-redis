from typing import Any, Mapping
from urllib.parse import urlparse

from src.workflows.query.interfaces.graph_interface import GraphInterface


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

    backend = (store_cfg.get("BACKEND") or store_cfg.get("ENGINE") or "neo4j").lower()

    if backend == "neo4j":
        from src.backends.storage.graph.neo4j_repository import Neo4jRepository

        update: dict[str, Any] = {}
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

    if backend in {"null", "noop", "disabled"}:
        from src.backends.storage.graph.null_repository import NullGraphRepository

        extra = set(store_cfg.keys()) - {"BACKEND"}
        if extra:
            raise ValueError(f"Unsupported graph setting(s) for '{backend}': {', '.join(sorted(extra))}")
        return NullGraphRepository()

    raise ValueError(f"Unsupported graph BACKEND: {backend}")


__all__ = ["get_graph_store"]
