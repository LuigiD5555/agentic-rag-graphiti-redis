"""
Vector storage factory and default backend resolution.

This module centralizes creation of the vector store so callers can stay agnostic
to which backend is configured (Weaviate by default).

Design note (Django-style):
- Users can configure multiple aliases via Config.VECTOR_STORES (data-only).
- Backend resolution logic is internal and whitelisted (not user-extensible).
"""

from __future__ import annotations

from typing import Any, Mapping, Iterable, List
from urllib.parse import urlparse
import types

from weaviate.classes.config import Property, DataType
from src.rag.interfaces.vector_interface import VectorInterface
from src.storage.vector.registry import (
    get_vector_store_factory,
    register_vector_store,
)
from src.storage.vector.backends.chroma import build_chroma_repository


def _get_rag_document_properties() -> List[Property]:
    """
    Define the schema properties for the RAG document collection.

    Returns:
        List of Weaviate Property definitions for the RAG collection.
    """
    return [
        Property(name="content", data_type=DataType.TEXT, description="Document content"),
        Property(name="external_id", data_type=DataType.TEXT, description="External document ID"),
        Property(name="source", data_type=DataType.TEXT, description="Source file path"),
        Property(name="chunk_index", data_type=DataType.INT, description="Chunk index within document"),
        Property(name="file_id", data_type=DataType.TEXT, description="File identifier"),
        Property(name="file_path", data_type=DataType.TEXT, description="Full file path"),
        Property(name="owner_id", data_type=DataType.TEXT, description="Owner user ID"),
        Property(name="visibility", data_type=DataType.TEXT, description="Visibility level"),
        Property(name="allowed_user_ids", data_type=DataType.TEXT_ARRAY, description="Allowed user IDs"),
        Property(name="metadata", data_type=DataType.TEXT, description="Additional metadata (JSON)"),
        Property(name="ingested_at", data_type=DataType.DATE, description="Ingestion timestamp"),
        Property(name="structure_summary", data_type=DataType.TEXT, description="Document structure summary"),
    ]


def _vector_store_settings(config: Any, alias: str) -> Mapping[str, Any]:
    """
    Resolve the vector store settings for a given alias from the settings object.

    Args:
        config: Application settings object or module. Must expose VECTOR_STORES (dict-like).
        alias: The vector store alias (e.g., "default").

    Returns:
        A dict-like mapping with the store configuration.

    Raises:
        TypeError: If VECTOR_STORES or the alias config are not dicts.
        KeyError: If the alias does not exist.
    """
    stores = getattr(config, "VECTOR_STORES", None) or {}
    if not isinstance(stores, dict):
        raise TypeError("VECTOR_STORES must be a dict mapping aliases to dict settings")
    if alias not in stores:
        available = ", ".join(sorted(stores.keys())) or "<none>"
        raise KeyError(f"Unknown VECTOR_STORES alias '{alias}'. Available: {available}")
    store_cfg = stores[alias]
    if not isinstance(store_cfg, dict):
        raise TypeError(f"VECTOR_STORES['{alias}'] must be a dict of settings")
    return store_cfg


def _config_with_overrides(
    config: Any,
    overrides: Mapping[str, Any],
    key_map: Mapping[str, str],
    allowed_passthrough: Iterable[str] | None = None,
) -> Any:
    """
    Create a new settings-like object with selected overrides applied.

    Supports:
      - Pydantic settings objects that provide `model_copy(update=...)`
      - Python modules (e.g., `import src.settings as settings`)
      - Plain objects with attributes

    Args:
        config: Settings object or module.
        overrides: Raw store config dict (Django-style).
        key_map: Mapping from Django-style keys to settings attribute names.
        allowed_passthrough: Keys that are allowed in overrides but should be ignored here.

    Returns:
        A settings-like object with updated attributes.

    Raises:
        ValueError: If an unsupported override key is provided.
    """
    update: dict[str, Any] = {}
    allowed = set(allowed_passthrough or ())

    for raw_key, raw_value in overrides.items():
        key_upper = str(raw_key or "").upper()
        if key_upper in {"BACKEND", "ENGINE"}:
            continue
        if key_upper in allowed:
            continue
        if key_upper == "OPTIONS":
            # OPTIONS is handled elsewhere (normalized before reaching here)
            continue
        if key_upper not in key_map:
            continue
        update[key_map[key_upper]] = raw_value

    if not update:
        return config

    # Case 1: Pydantic v2 style settings
    model_copy = getattr(config, "model_copy", None)
    if callable(model_copy):
        return model_copy(update=update)

    # Case 2: Module or plain object -> build a namespace copy
    # We copy public attributes to avoid mutating the original module/object.
    base_attributes: dict[str, Any] = {}
    try:
        # For modules, vars(config) works; for many objects too.
        base_attributes.update(vars(config))
    except TypeError:
        # Fallback for objects without __dict__
        for name in dir(config):
            if name.startswith("_"):
                continue
            try:
                base_attributes[name] = getattr(config, name)
            except Exception:
                continue

    base_attributes.update(update)
    return types.SimpleNamespace(**base_attributes)


def _normalize_vector_store_cfg(store_cfg: Mapping[str, Any], config: Any) -> Mapping[str, Any]:
    """
    Accept Django-like keys (ENGINE/HOST/PORT/OPTIONS) and synthesize URL when needed.

    Args:
        store_cfg: Raw store configuration mapping.
        config: Settings object/module, used as fallback for WEAVIATE_URL.

    Returns:
        A normalized store configuration mapping.
    """
    normalized = dict(store_cfg)
    options = normalized.get("OPTIONS") or {}
    if isinstance(options, dict):
        if options.get("GRPC_PORT") is not None:
            normalized.setdefault("GRPC_PORT", options["GRPC_PORT"])
        if options.get("CONNECT_RETRIES") is not None:
            normalized.setdefault("CONNECT_RETRIES", options["CONNECT_RETRIES"])
        if options.get("CONNECT_BACKOFF") is not None:
            normalized.setdefault("CONNECT_BACKOFF", options["CONNECT_BACKOFF"])
        if options.get("MULTI_TENANCY") is not None:
            normalized.setdefault("MULTI_TENANCY", options["MULTI_TENANCY"])
        if options.get("DEFAULT_TENANT") is not None:
            normalized.setdefault("DEFAULT_TENANT", options["DEFAULT_TENANT"])
        if options.get("TIMEOUT") is not None:
            normalized.setdefault("TIMEOUT", options["TIMEOUT"])

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

    if "NAME" in normalized and "CLASS" not in normalized:
        normalized["CLASS"] = normalized["NAME"]

    return normalized


def _build_weaviate_repository(config: Any, store_cfg: Mapping[str, Any], alias: str) -> VectorInterface:
    """
    Build the default Weaviate repository backend.

    This is the only backend implemented for now, but the registry allows
    more in the future.
    """
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
        },
    )

    weaviate_url = getattr(cfg, "WEAVIATE_URL", None) or store_cfg.get("URL") or "http://localhost:8080"
    weaviate_api_key = getattr(cfg, "WEAVIATE_API_KEY", None) or store_cfg.get("API_KEY")
    weaviate_class = getattr(cfg, "WEAVIATE_CLASS", None) or store_cfg.get("CLASS") or "RagDocument"
    weaviate_timeout = getattr(cfg, "WEAVIATE_TIMEOUT", None) or store_cfg.get("TIMEOUT") or 120
    weaviate_multi_tenancy = bool(
        getattr(cfg, "WEAVIATE_MULTI_TENANCY", False) or store_cfg.get("MULTI_TENANCY") or False
    )
    weaviate_default_tenant = getattr(cfg, "WEAVIATE_DEFAULT_TENANT", None) or store_cfg.get("DEFAULT_TENANT") or "default"
    weaviate_grpc_port = getattr(cfg, "WEAVIATE_GRPC_PORT", None) or store_cfg.get("GRPC_PORT")
    skip_init_checks = bool(getattr(cfg, "WEAVIATE_SKIP_INIT_CHECKS", False))

    from weaviate.classes.init import AdditionalConfig, Timeout
    from src.storage.vector.weaviate_repository.repository import WeaviateRepository
    from src.storage.vector.weaviate_repository.schema import SchemaManager

    additional = AdditionalConfig(timeout=Timeout(init=weaviate_timeout, query=weaviate_timeout))

    parsed_url = urlparse(weaviate_url)
    host = parsed_url.hostname or "localhost"
    port = parsed_url.port or (443 if parsed_url.scheme == "https" else 8080)
    use_https = parsed_url.scheme == "https"
    grpc_port = weaviate_grpc_port or (50051 if not use_https else 443)

    import weaviate

    if weaviate_api_key:
        client = weaviate.connect_to_custom(
            http_host=host,
            http_port=port,
            http_secure=use_https,
            grpc_host=host,
            grpc_port=grpc_port,
            grpc_secure=use_https,
            auth_credentials=weaviate.auth.AuthApiKey(api_key=weaviate_api_key),
            additional_config=additional,
            skip_init_checks=skip_init_checks,
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
            skip_init_checks=skip_init_checks,
        )

    schema_manager = SchemaManager(
        client=client,
        cfg=cfg,
        class_name=weaviate_class,
        multitenant_enabled=weaviate_multi_tenancy,
        default_tenant=weaviate_default_tenant if weaviate_multi_tenancy else None,
        class_properties_provider=_get_rag_document_properties,
    )
    schema_manager.ensure_class()

    return WeaviateRepository(schema=schema_manager)


register_vector_store("weaviate", _build_weaviate_repository)
register_vector_store("chroma", build_chroma_repository)


def get_vector_store(config: Any, alias: str = "default") -> VectorInterface:
    """
    Create the vector store backend selected in settings.

    Django-like usage:
        VECTOR_STORES = {
            "default": {"ENGINE": "weaviate"},
            "analytics": {"ENGINE": "weaviate", "URL": "..."},
        }

    Args:
        config: Application settings object or module.
        alias: Vector store alias to use.

    Returns:
        An instance implementing VectorInterface.
    """
    store_cfg = _normalize_vector_store_cfg(_vector_store_settings(config, alias), config)
    backend = (store_cfg.get("BACKEND") or store_cfg.get("ENGINE") or "").strip().lower()
    if not backend:
        backend = (getattr(config, "VECTOR_BACKEND", None) or "weaviate").strip().lower()

    factory = get_vector_store_factory(backend)
    return factory(config, store_cfg, alias)
