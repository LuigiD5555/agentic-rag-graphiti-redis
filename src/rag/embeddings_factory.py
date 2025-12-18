from __future__ import annotations

from typing import Optional

from src.providers.factory import ProviderFactory
from src.rag.conf import Config
from src.rag.interfaces.embedding_interface import EmbeddingInterface


def get_embedding_service(
    config: Config,
    provider: Optional[ProviderFactory] = None,
) -> EmbeddingInterface:
    """
    Return the embedding service specified by the configuration.

    Defaults to LM Studio, but can be switched to GPU-backed local embeddings.
    """
    backend = (getattr(config, "EMBEDDING_BACKEND", "lmstudio") or "lmstudio").strip().lower()
    if backend == "local_gpu":
        # Lazy import so torch/sentence-transformers stay optional unless needed.
        from src.utils.local_gpu.factory import build_local_gpu_embedding_service

        return build_local_gpu_embedding_service(config)

    provider = provider or ProviderFactory(config)
    return provider.embeddings()
