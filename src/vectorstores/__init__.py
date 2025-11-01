"""
Backend factory for vector databases.

Usage in your app:
    from src.config.settings import Config
    from src.vectorstores import get_vector_store

    cfg = Config()
    vector = get_vector_store(cfg)  # returns the configured backend (Weaviate by default)
"""

from typing import cast
from src.config.settings import Config
from src.interfaces.vector_interface import VectorInterface
from src.storage.vector.weaviate_repository import WeaviateRepository


def get_vector_store(config: Config) -> VectorInterface:
    """
    Create the vector store backend selected in settings.
    Supported values today:
        - "weaviate"  (default)
    Future backends can be added here (e.g., "milvus", "faiss", "pgvector").
    """
    backend = (getattr(config, "VECTOR_BACKEND", "weaviate") or "weaviate").lower()

    if backend == "weaviate":
        return cast(VectorInterface, WeaviateRepository(config))

    raise ValueError(f"Unsupported VECTOR_BACKEND: {backend}")
