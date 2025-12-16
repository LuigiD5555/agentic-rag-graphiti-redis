"""
Vector storage factory and default backend resolution.

This module centralizes creation of the vector store so callers can stay agnostic
to which backend is configured (Weaviate by default).

Design note (Django-style):
- Users can configure multiple aliases via Config.VECTOR_STORES (data-only).
- Backend resolution logic is internal and whitelisted (not user-extensible).
"""

from typing import TYPE_CHECKING, Any, Mapping, Iterable
from urllib.parse import urlparse

from src.rag.interfaces.vector_interface import VectorInterface

if TYPE_CHECKING:  # pragma: no cover
    from src.rag.conf import Config


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


def _config_with_overrides(
    config: "Config",
    overrides: Mapping[str, Any],
    key_map: Mapping[str, str],
    allowed_passthrough: Iterable[str] | None = None,
) -> "Config":
    update: dict[str, Any] = {}
    allowed = set(allowed_passthrough or ())
    for raw_key, raw_value in overrides.items():
        key_upper = str(raw_key or "").upper()
        if key_upper in {"BACKEND", "ENGINE"}:
            continue
        if key_upper in allowed:
            continue
        if key_upper not in key_map:
            raise ValueError(f"Unsupported vector store setting '{raw_key}'")
        update[key_map[key_upper]] = raw_value

    return config.copy(update=update) if update else config


def _normalize_vector_store_cfg(store_cfg: Mapping[str, Any], config: "Config") -> Mapping[str, Any]:
    """
    Accept Django-like keys (ENGINE/HOST/PORT/OPTIONS) and synthesize URL when needed.
    """
    normalized = dict(store_cfg)
    options = normalized.get("OPTIONS") or {}
    if isinstance(options, dict):
        # Bubble up common options into top-level keys when missing.
        normalized.setdefault("GRPC_PORT", options.get("GRPC_PORT"))
        normalized.setdefault("CONNECT_RETRIES", options.get("CONNECT_RETRIES"))
        normalized.setdefault("CONNECT_BACKOFF", options.get("CONNECT_BACKOFF"))
        normalized.setdefault("MULTI_TENANCY", options.get("MULTI_TENANCY"))
        normalized.setdefault("DEFAULT_TENANT", options.get("DEFAULT_TENANT"))

    if "URL" not in normalized:
        host = normalized.get("HOST")
        port = normalized.get("PORT")
        scheme = normalized.get("SCHEME") or "http"
        path = normalized.get("PATH") or ""
        if host or port:
            host = host or "localhost"
            port = port or 8080
            url = f"{scheme}://{host}:{port}"
            if path:
                url = f"{url}/{str(path).lstrip('/')}"
            normalized["URL"] = url
        else:
            # If the configured URL is present in config, parse to infer host/port for logging/consistency.
            parsed = urlparse(getattr(config, "WEAVIATE_URL", ""))
            if parsed.scheme and parsed.hostname:
                normalized.setdefault("HOST", parsed.hostname)
                normalized.setdefault("PORT", parsed.port)
                normalized.setdefault("SCHEME", parsed.scheme)
    if "NAME" in normalized and "CLASS" not in normalized:
        normalized["CLASS"] = normalized["NAME"]
    return normalized


def get_vector_store(config: "Config", alias: str = "default") -> VectorInterface:
    """
    Create the vector store backend selected in settings.

    Django-like usage:
        VECTOR_STORES = {
            "default": {"ENGINE": "weaviate"},
            "analytics": {"ENGINE": "weaviate", "URL": "..."},
        }
    """
    store_cfg = _normalize_vector_store_cfg(_vector_store_settings(config, alias), config)
    backend = (store_cfg.get("BACKEND") or store_cfg.get("ENGINE") or "").strip().lower()
    if not backend:
        backend = (getattr(config, "VECTOR_BACKEND", None) or "weaviate").strip().lower()

    if backend == "weaviate":
        import weaviate
        from weaviate.classes.config import Configure, Property, DataType
        from weaviate.classes.init import AdditionalConfig, Timeout
        from src.storage.vector.weaviate_repository.repository import WeaviateRepository
        from src.storage.vector.weaviate_repository.schema import SchemaManager

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
            allowed_passthrough={
                "OPTIONS",
                "HOST",
                "PORT",
                "SCHEME",
                "PATH",
                "NAME",
                "USER",
                "PASSWORD",
                "LOCATION",
                "AUTOCOMMIT",
                "ATOMIC_REQUESTS",
                "CONN_MAX_AGE",
                "CONN_HEALTH_CHECKS",
                "TIME_ZONE",
                "TEST",
            },
        )

        # Create Weaviate client using v4 API
        additional = AdditionalConfig(
            timeout=Timeout(init=cfg.WEAVIATE_TIMEOUT, query=cfg.WEAVIATE_TIMEOUT)
        )

        # Parse URL to extract host and port
        parsed_url = urlparse(cfg.WEAVIATE_URL)
        host = parsed_url.hostname or "localhost"
        port = parsed_url.port or (443 if parsed_url.scheme == "https" else 8080)
        use_https = parsed_url.scheme == "https"

        # Determine GRPC port
        grpc_port = cfg.WEAVIATE_GRPC_PORT or (50051 if not use_https else 443)

        if cfg.WEAVIATE_API_KEY:
            client = weaviate.connect_to_custom(
                http_host=host,
                http_port=port,
                http_secure=use_https,
                grpc_host=host,
                grpc_port=grpc_port,
                grpc_secure=use_https,
                auth_credentials=weaviate.auth.AuthApiKey(api_key=cfg.WEAVIATE_API_KEY),
                additional_config=additional,
            )
        else:
            client = weaviate.connect_to_custom(
                http_host=host,
                http_port=port,
                http_secure=use_https,
                grpc_host=host,
                grpc_port=grpc_port,
                grpc_secure=use_https,
                additional_config=additional,
            )

        # Define class properties
        def _get_class_properties():
            return [
                Property(name="external_id", data_type=DataType.TEXT),
                Property(name="hash", data_type=DataType.TEXT),
                Property(name="content", data_type=DataType.TEXT),
                Property(name="structure_summary", data_type=DataType.TEXT),
                Property(name="file_path", data_type=DataType.TEXT),
                Property(name="file_type", data_type=DataType.TEXT),
                Property(name="file_size", data_type=DataType.INT),
                Property(name="created_at", data_type=DataType.DATE),
                Property(name="modified_at", data_type=DataType.DATE),
                Property(name="indexed_at", data_type=DataType.DATE),
                Property(name="chunk_index", data_type=DataType.INT),
                Property(name="total_chunks", data_type=DataType.INT),
                Property(name="visibility", data_type=DataType.TEXT),
                Property(name="allowed_user_ids", data_type=DataType.TEXT_ARRAY),
                Property(name="tags", data_type=DataType.TEXT_ARRAY),
                Property(name="metadata", data_type=DataType.TEXT),
                Property(name="source", data_type=DataType.TEXT),
            ]

        # Create SchemaManager
        schema = SchemaManager(
            client=client,
            cfg=cfg,
            class_name=cfg.WEAVIATE_CLASS,
            multitenant_enabled=bool(cfg.WEAVIATE_MULTI_TENANCY),
            default_tenant=cfg.WEAVIATE_DEFAULT_TENANT if cfg.WEAVIATE_MULTI_TENANCY else None,
            class_properties_provider=_get_class_properties,
        )

        # Ensure schema exists
        schema.ensure()

        return WeaviateRepository(schema)

    raise ValueError(f"Unsupported vector BACKEND: {backend}")


__all__ = ["get_vector_store"]
