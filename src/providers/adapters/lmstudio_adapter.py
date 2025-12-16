import os
from src.providers.adapters.base import ProviderAdapterBase
from src.rag.interfaces.embedding_interface import EmbeddingInterface
from src.rag.interfaces.chat_interface import ChatInterface
from src.providers.lmstudio.model_manager import ModelManager
from src.providers.lmstudio.embeddings import EmbeddingService
from src.providers.lmstudio.cached_embeddings import CachedEmbeddingService
from src.providers.lmstudio.client import LLMService
from src.rag.conf import Config
from src import logger


class LMStudioAdapter(ProviderAdapterBase):
    """
    Adapter for LM Studio provider (local HTTP server). Reuses existing client modules.
    """

    def __init__(self, config: Config):
        mm = ModelManager(
            config._lmstudio_api_roots,
            require_live=config.LMSTUDIO_REQUIRE_SERVER,
        )

        # Create base embedding service
        base_embedding_service = EmbeddingService(config, mm)

        # Wrap with cache if enabled
        cache_enabled = os.environ.get("RAG_EMBED_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
        if cache_enabled:
            try:
                # Try to get Redis client
                redis_client = self._get_redis_client(config)
                if redis_client is not None:
                    cache_ttl = int(os.environ.get("RAG_EMBED_CACHE_TTL", "604800"))  # 7 days default
                    cache_prefix = os.environ.get("RAG_EMBED_CACHE_PREFIX", "embed:")

                    embedding: EmbeddingInterface = CachedEmbeddingService(
                        embedding_service=base_embedding_service,
                        redis_client=redis_client,
                        enabled=True,
                        ttl_seconds=cache_ttl,
                        key_prefix=cache_prefix,
                    )
                    logger.info("Embedding cache enabled with Redis")
                else:
                    embedding = base_embedding_service
                    logger.warning("Redis unavailable, embedding cache disabled")
            except Exception as e:
                embedding = base_embedding_service
                logger.warning("Failed to initialize embedding cache: %s", e)
        else:
            embedding = base_embedding_service
            logger.info("Embedding cache explicitly disabled via RAG_EMBED_CACHE_ENABLED")

        chat: ChatInterface = LLMService(config, mm)
        super().__init__(embedding, chat)

    def _get_redis_client(self, config: Config):
        """
        Get Redis client if available, return None otherwise.
        """
        try:
            import redis

            redis_host = getattr(config, "REDIS_HOST", "127.0.0.1")
            redis_port = int(getattr(config, "REDIS_PORT", 6379))
            redis_db = int(os.environ.get("RAG_EMBED_CACHE_DB", "0"))

            client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                decode_responses=False,  # We'll handle encoding ourselves
                socket_connect_timeout=2,
                socket_timeout=2,
            )

            # Test connection
            client.ping()
            return client

        except ImportError:
            logger.warning("redis-py not installed, embedding cache unavailable")
            return None
        except Exception as e:
            logger.debug("Redis connection failed: %s", e)
            return None
