import os
from typing import Any
from src.backends.llm.adapters.base import ProviderAdapterBase
from src.workflows.query.interfaces.embedding_interface import EmbeddingInterface
from src.workflows.query.interfaces.chat_interface import ChatInterface
from src.backends.llm.lmstudio.model_manager import ModelManager
from src.backends.llm.lmstudio.embeddings import EmbeddingService
from src.backends.llm.lmstudio.client import LLMService
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

        # Wrap with cache if enabled (external cache removed)
        cache_enabled = os.environ.get("RAG_EMBED_CACHE_ENABLED", "false").lower() in ("true", "1", "yes")
        if cache_enabled:
            embedding = base_embedding_service
            logger.warning("Embedding cache disabled (no external cache configured)")
        else:
            embedding = base_embedding_service

        chat: ChatInterface = LLMService(config, mm)
        super().__init__(embedding, chat)

    # Embedding cache backend removed (SQLite-only control plane)
