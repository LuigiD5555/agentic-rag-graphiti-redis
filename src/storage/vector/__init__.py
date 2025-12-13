"""
Vector storage factory and default backend resolution.

This module centralizes creation of the vector store so callers can stay agnostic
to which backend is configured (Weaviate by default).
"""

from typing import TYPE_CHECKING, Any, cast

from src.rag.interfaces.vector_interface import VectorInterface
from src.storage.plugins import create_storage_instance

if TYPE_CHECKING:  # pragma: no cover
    from src.settings import Config


def _build_default_vector_storage_config(config: "Config") -> dict[str, Any]:
    """
    Build a default storage config dict for the vector backend.
    """
    backend = (getattr(config, "VECTOR_BACKEND", "weaviate") or "weaviate").lower()

    if backend == "weaviate":
        # ENGINE points to the plugin class; additional options could be passed
        # here in the future if needed.
        return {
            "ENGINE": "src.storage.vector.weaviate_repository.plugin.WeaviateVectorPlugin",
            "BACKEND": backend,
        }

    raise ValueError(f"Unsupported VECTOR_BACKEND: {backend}")


def get_vector_store(config: "Config") -> VectorInterface:
    """
    Create the vector store backend selected in settings.

    Supported values today:
        - "weaviate"  (default)

    Future backends can be added by introducing new plugins and mapping VECTOR_BACKEND
    values to their ENGINE strings.
    """
    storage_cfg = _build_default_vector_storage_config(config)

    # Pass the Config instance explicitly so plugins can reuse it.
    plugin = create_storage_instance(
        {
            **storage_cfg,
            "config": config,
        }
    )

    # Prefer an explicit get_client() method on the plugin, if present.
    client = getattr(plugin, "get_client", None)
    if callable(client):
        return cast(VectorInterface, client())

    # Fallback to a '_repo' attribute or the plugin itself.
    return cast(VectorInterface, getattr(plugin, "_repo", plugin))


__all__ = ["get_vector_store"]
