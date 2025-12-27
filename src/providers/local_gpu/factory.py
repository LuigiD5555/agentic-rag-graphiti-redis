import os
from typing import Optional

from src import logger
from src.providers.lmstudio.cached_embeddings import CachedEmbeddingService
from src.rag.conf import Config
from src.rag.interfaces.embedding_interface import EmbeddingInterface


def build_local_gpu_embedding_service(config: Config) -> EmbeddingInterface:
    """
    Create a LocalGPUEmbeddingService with optional Redis caching.
    """
    # Lazy import so torch/sentence-transformers stay optional unless needed.
    from src.providers.local_gpu.embedding_service import LocalGPUEmbeddingService

    base_service = LocalGPUEmbeddingService(config)

    cache_enabled = os.environ.get("RAG_EMBED_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
    if not cache_enabled:
        logger.info("Embedding cache explicitly disabled via RAG_EMBED_CACHE_ENABLED")
        return base_service

    redis_client = _get_redis_client(config)
    if redis_client is None:
        logger.warning("Redis unavailable, local GPU embeddings will not be cached")
        return base_service

    cache_ttl = int(os.environ.get("RAG_EMBED_CACHE_TTL", "604800"))
    cache_prefix = os.environ.get("RAG_EMBED_CACHE_PREFIX", "embed:")

    wrapped = CachedEmbeddingService(
        embedding_service=base_service,
        redis_client=redis_client,
        enabled=True,
        ttl_seconds=cache_ttl,
        key_prefix=cache_prefix,
    )
    logger.info("Embedding cache enabled with Redis (local GPU embeddings)")
    return wrapped


def _get_redis_client(config: Config):
    try:
        from src.storage.cache.redis_connection import create_redis_client_with_retry
        import redis

        redis_host = getattr(config, "REDIS_HOST", "127.0.0.1")
        redis_port = int(getattr(config, "REDIS_PORT", 6379))
        redis_db = int(os.environ.get("RAG_EMBED_CACHE_DB", "0"))

        logger.info(
            "Attempting to connect to Redis at %s:%d (db=%d) for local GPU embedding cache",
            redis_host,
            redis_port,
            redis_db,
        )
        client = create_redis_client_with_retry(
            host=redis_host,
            port=redis_port,
            decode_responses=False,
            timeout=2,
        )
        # Select database
        client.execute_command('SELECT', redis_db)
        logger.info("Redis connection successful for local GPU embedding cache")
        return client
    except ImportError:
        logger.warning("redis-py not installed, embedding cache unavailable for local GPU embeddings")
        return None
    except Exception as exc:
        logger.warning("Failed to connect to Redis for local GPU embedding cache: %s", exc)
        return None
