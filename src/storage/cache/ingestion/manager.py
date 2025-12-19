"""Main cache manager class."""
from typing import TYPE_CHECKING, Dict, Any
import time

if TYPE_CHECKING:
    import redis

try:
    import redis as redis_module
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis_module = None  # type: ignore

from src.rag.audit import get_logger
from .file_cache import FileCacheOperations
from .directory_cache import DirectoryCacheOperations
from src.utils.hashing import compute_file_hash, compute_directory_hash

log = get_logger(__name__)


class IngestionCacheManager(FileCacheOperations, DirectoryCacheOperations):
    """Redis-based cache manager for file ingestion.

    Redis is required - if unavailable, the manager will raise an error.
    This ensures predictable behavior and avoids silent performance degradation.
    """

    def __init__(self, redis_client: "redis.Redis", ttl: int = FileCacheOperations.DEFAULT_TTL, paranoid_mode: bool = False):
        """Initialize cache manager.

        Args:
            redis_client: Redis client instance (required).
            ttl: Time-to-live for cache entries in seconds.
            paranoid_mode: If True, always verify content hash even when mtime+size match.
                         If False (default), trust mtime+size for better performance.

        Raises:
            TypeError: If redis_client is None.
        """
        if redis_client is None:
            raise TypeError("Redis client is required. Cannot initialize cache without Redis.")

        FileCacheOperations.__init__(self, redis_client, ttl, paranoid_mode)
        DirectoryCacheOperations.__init__(self, redis_client, ttl)

        self.enabled = True  # Cache is enabled when Redis is available
        log.info(
            "Ingestion cache manager initialized with Redis (paranoid_mode=%s)",
            paranoid_mode
        )

    @classmethod
    def from_settings(cls, settings: Dict[str, Any], max_retries: int = 10) -> "IngestionCacheManager":
        """Create cache manager from settings with connection retry logic.

        Args:
            settings: Configuration dictionary.
            max_retries: Maximum number of connection attempts.

        Raises:
            RuntimeError: If Redis is unavailable or connection fails after retries.
        """
        if not REDIS_AVAILABLE:
            raise RuntimeError("redis-py is not installed. Install it with: pip install redis")

        cache_config = settings.get("CACHES", {}).get("default", {})
        location = cache_config.get("LOCATION", "").strip()

        # Build Redis URL from config or environment
        if not location:
            import os
            redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
            redis_port = os.getenv("REDIS_PORT", "6379")
            location = f"redis://{redis_host}:{redis_port}/0"

        # Retry logic with exponential backoff
        delay = 1.0
        max_delay = 30.0
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                log.info(
                    "Attempting to connect to Redis at %s (attempt %d/%d)",
                    location, attempt, max_retries
                )

                client = redis_module.from_url(
                    location,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )

                # Test connection
                client.ping()
                log.info("Successfully connected to Redis cache at %s", location)
                return cls(redis_client=client)

            except Exception as e:
                last_error = e

                if attempt == max_retries:
                    log.error(
                        "Failed to connect to Redis at %s after %d attempts. Last error: %s",
                        location, max_retries, e
                    )
                    break

                log.warning(
                    "Redis connection attempt %d/%d failed: %s. Retrying in %.1f seconds...",
                    attempt, max_retries, e, delay
                )

                time.sleep(delay)
                delay = min(delay * 2, max_delay)  # Exponential backoff with cap

        # If we get here, all retries failed
        raise RuntimeError(
            f"Failed to connect to Redis at {location} after {max_retries} attempts. "
            f"Last error: {last_error}"
        ) from last_error

    # Re-expose utility methods for backwards compatibility
    def compute_file_hash(self, file_path: str, chunk_size: int = 8192):
        """Compute SHA256 hash of file content."""
        return compute_file_hash(file_path, chunk_size)

    def compute_directory_hash(self, dir_path: str):
        """Compute hash of directory structure (file names + mtimes)."""
        return compute_directory_hash(dir_path)


__all__ = ["IngestionCacheManager"]
