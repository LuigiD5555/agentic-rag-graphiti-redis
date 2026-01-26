import os
from typing import Any
from src.backends.llm.adapters.base import ProviderAdapterBase
from src.workflows.query.interfaces.embedding_interface import EmbeddingInterface
from src.workflows.query.interfaces.chat_interface import ChatInterface
from src.backends.llm.lmstudio.model_manager import ModelManager
from src.backends.llm.lmstudio.embeddings import EmbeddingService
from src.backends.llm.lmstudio.client import LLMService
from src.backends.llm.lmstudio.cached_embeddings import CachedEmbeddingService
from src import logger


class LMStudioAdapter(ProviderAdapterBase):
    """
    Adapter for LM Studio provider (local HTTP server). Reuses existing client modules.
    """

    def __init__(self, config: Any):
        mm = ModelManager(
            config._lmstudio_api_roots,
            require_live=config.LMSTUDIO_REQUIRE_SERVER,
        )

        # Create base embedding service
        base_embedding_service = EmbeddingService(config, mm)

        # Wrap with cache if enabled (SQLite-backed embedding cache)
        cache_enabled = os.environ.get("RAG_EMBED_CACHE_ENABLED", "false").lower() in ("true", "1", "yes")
        if cache_enabled:
            ttl = int(os.environ.get("RAG_EMBED_CACHE_TTL", "604800"))
            prefix = os.environ.get("RAG_EMBED_CACHE_PREFIX", "embed:")
            embedding = CachedEmbeddingService(
                base_embedding_service,
                enabled=True,
                ttl_seconds=ttl,
                key_prefix=prefix,
            )
        else:
            embedding = base_embedding_service

        chat: ChatInterface = LLMService(config, mm)
        super().__init__(embedding, chat)

    # Embedding cache backed by SQLite control plane
