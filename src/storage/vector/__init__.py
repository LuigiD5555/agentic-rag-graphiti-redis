"""
Vector storage factory and default backend resolution.

This module centralizes creation of the vector store so callers can stay agnostic
to which backend is configured (Weaviate by default).

Design note (Django-style):
- Users can configure multiple aliases via Config.VECTOR_STORES (data-only).
- Backend resolution logic is internal and whitelisted (not user-extensible).
"""

from typing import TYPE_CHECKING, Any, Mapping

from src.rag.interfaces.vector_interface import VectorInterface

if TYPE_CHECKING:  # pragma: no cover
    from src.settings import Config


def _vector_store_settings(config: "Config", alias: str) -> Mapping[str, Any]:
    stores = getattr(config, "VECTOR_STORES", None) or {}
    if not isinstance(stores, dict):
        raise TypeError("Config.VECTOR_STORES must be a dict mapping aliases to dict settings")
    if alias not in stores:
        available = ", ".join(sorted(stores.keys())) or "<none>"
        raise KeyError(f"Unknown VECTOR_STORES alias '{alias}'. Available: {available}")
    store_cfg = stores[alias]
    if not isinstance(store_cfg, dict):
        raise TypeError(f"Config.VECTOR_STORES['{alias}'] must be a dict of settings")
    return store_cfg


def _config_with_overrides(config: "Config", overrides: Mapping[str, Any], key_map: Mapping[str, str]) -> "Config":
    update: dict[str, Any] = {}
    for raw_key, raw_value in overrides.items():
        if raw_key == "BACKEND":
            continue
        if raw_key == "ENGINE":
            raise ValueError("Use BACKEND (whitelisted) instead of ENGINE (import path)")
        if raw_key not in key_map:
            raise ValueError(f"Unsupported vector store setting '{raw_key}'")
        update[key_map[raw_key]] = raw_value

    return config.model_copy(update=update) if update else config


def get_vector_store(config: "Config", alias: str = "default") -> VectorInterface:
    """
    Create the vector store backend selected in settings.

    Django-like usage:
        VECTOR_STORES = {
            "default": {"BACKEND": "weaviate"},
            "analytics": {"BACKEND": "weaviate", "URL": "..."},
        }
    """
    store_cfg = _vector_store_settings(config, alias)
    backend = (store_cfg.get("BACKEND") or getattr(config, "VECTOR_BACKEND", "weaviate") or "weaviate").lower()

    if backend == "weaviate":
        from src.storage.vector.weaviate_repository.repository import WeaviateRepository

        cfg = _config_with_overrides(
            config,
            store_cfg,
            {
                "URL": "WEAVIATE_URL",
                "API_KEY": "WEAVIATE_API_KEY",
                "CLASS": "WEAVIATE_CLASS",
                "MULTI_TENANCY": "WEAVIATE_MULTI_TENANCY",
                "DEFAULT_TENANT": "WEAVIATE_DEFAULT_TENANT",
                "TIMEOUT": "WEAVIATE_TIMEOUT",
                "GRPC_PORT": "WEAVIATE_GRPC_PORT",
                "CONNECT_RETRIES": "WEAVIATE_CONNECT_RETRIES",
                "CONNECT_BACKOFF": "WEAVIATE_CONNECT_BACKOFF",
            },
        )
        return WeaviateRepository(cfg)

    raise ValueError(f"Unsupported vector BACKEND: {backend}")


__all__ = ["get_vector_store"]
