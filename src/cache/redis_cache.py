"""Module for Redis-based caching."""
from typing import Optional, cast
import json
import redis
from src import logger
from src.interfaces.cache_interface import CacheServiceProtocol


class CacheService(CacheServiceProtocol):
    """
    Redis-based cache service with JSON serialization and centralized logging.
    """

    def __init__(self, config):
        """
        Initialize the Redis client using host and port from configuration.
        """
        self.client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            decode_responses=True
        )
        logger.info(
            "CacheService initialized with Redis at %s:%s",
            config.REDIS_HOST,
            config.REDIS_PORT
        )

    def get(self, key: str) -> Optional[str]:
        """
        Retrieve raw value from cache (JSON string).
        Caller is responsible for JSON decoding if needed.
        """
        result = self.client.get(key)

        # Force an Optional[str], because decode_responses=True ensures string
        result_str = cast(Optional[str], result)

        if result_str is None:
            logger.debug("Cache miss for key: %s", key)
            return None

        logger.debug("Cache hit for key: %s", key)
        return result_str

    def set(self, key: str, value: object, ttl: int = 3600) -> None:
        """
        Serialize value as JSON and store in cache with TTL.
        """
        try:
            self.client.set(key, json.dumps(value), ex=ttl)
            logger.debug("Cached key '%s' with TTL %d seconds", key, ttl)
        except (TypeError, ValueError) as e:
            logger.error("Failed to cache key '%s': %s", key, e)
