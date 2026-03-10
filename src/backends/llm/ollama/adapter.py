"""
OllamaAdapter — wires OllamaChat, OllamaEmbeddingService, and (optionally)
CachedEmbeddingService into a ProviderAdapterBase.

Activated automatically when PROVIDER=ollama (builtins.py hook already exists).
"""
from __future__ import annotations

import os
import logging

from src.backends.llm.adapters.base import ProviderAdapterBase
from src.backends.llm.ollama.client import OllamaChat
from src.backends.llm.ollama.embeddings import OllamaEmbeddingService
from src.backends.llm.ollama.model_manager import OllamaModelManager
from src.backends.llm.lmstudio.model_manager import detect_model_dimensions

logger = logging.getLogger(__name__)


class OllamaAdapter(ProviderAdapterBase):
    def __init__(self, config) -> None:
        host = getattr(config, "OLLAMA_HOST", "localhost")
        port = getattr(config, "OLLAMA_PORT", 11434)
        base_url = f"http://{host}:{port}"

        chat_model = (getattr(config, "OLLAMA_CHAT_MODEL", "") or "llama3.2").strip()
        embed_model = (getattr(config, "OLLAMA_EMBED_MODEL", "") or "nomic-embed-text").strip()
        require_live = bool(getattr(config, "OLLAMA_REQUIRE_SERVER", False))
        timeout = int(getattr(config, "OLLAMA_REQUEST_TIMEOUT", 120))

        # Auto-detect embedding dimension (reuse LMStudio's known-model table)
        expected_dim = int(getattr(config, "EMBEDDING_DIM", 768))
        detected = detect_model_dimensions(embed_model)
        if detected:
            expected_dim = detected
            logger.info("Ollama: auto-detected embed dim=%d for '%s'", detected, embed_model)

        base_embedding = OllamaEmbeddingService(
            base_url=base_url,
            model_name=embed_model,
            expected_dim=expected_dim,
            require_live=require_live,
            timeout=timeout,
        )

        # Wrap with SQLite cache if RAG_EMBED_CACHE_ENABLED=true (same toggle as LMStudio)
        cache_enabled = os.environ.get("RAG_EMBED_CACHE_ENABLED", "false").lower() in ("true", "1", "yes")
        if cache_enabled:
            from src.backends.llm.lmstudio.cached_embeddings import CachedEmbeddingService
            ttl = int(os.environ.get("RAG_EMBED_CACHE_TTL", "604800"))
            prefix = os.environ.get("RAG_EMBED_CACHE_PREFIX", "embed:")
            embedding = CachedEmbeddingService(base_embedding, enabled=True, ttl_seconds=ttl, key_prefix=prefix)
        else:
            embedding = base_embedding

        chat = OllamaChat(
            base_url=base_url,
            model=chat_model,
            require_live=require_live,
            timeout=timeout,
        )

        super().__init__(embedding, chat)
        logger.info(
            "OllamaAdapter ready (chat=%s, embed=%s, url=%s, cache=%s)",
            chat_model, embed_model, base_url, cache_enabled,
        )
