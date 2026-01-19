"""Main cache manager class with graceful fallback."""
from typing import TYPE_CHECKING, Dict, Any, Optional
import time

if TYPE_CHECKING:
    import redis

try:
    import redis as redis_module
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis_module = None  # type: ignore

from src.conf import settings
from src.workflows.query.audit import get_logger
from .file_cache import FileCacheOperations
from .directory_cache import DirectoryCacheOperations
from src.utils.hashing import compute_file_hash, compute_directory_hash

log = get_logger(__name__)


class NullCacheManager:
    """Null cache manager for when Redis is unavailable."""
    
    def __init__(self):
        self.enabled = False
        log.warning("Using null cache manager (Redis unavailable)")
    
    def get_file_metadata(self, file_path: str):
        """Always return None - no caching."""
        return None
    
    def set_file_metadata(self, file_path: str, metadata):
        """Do nothing - no caching."""
        return True
    
    def get_files_by_hash(self, content_hash: str):
        """Return empty set - no deduplication."""
        return set()
    
    def delete_file_metadata(self, file_path: str):
        """Do nothing."""
        return True
    
    def clear_all(self):
        """Do nothing."""
        return True
    
    def increment_stats(self, **kwargs):
        """Do nothing."""
        pass
    
    def get_stats(self):
        """Return empty stats."""
        return {
            'enabled': False,
            'backend': 'null',
            'cached_files': 0,
            'cached_dirs': 0,
            'error': 'Redis unavailable'
        }


class IngestionCacheManager(FileCacheOperations, DirectoryCacheOperations):
    """Redis-based cache manager for file ingestion with graceful fallback."""

    def __init__(
        self,
        redis_client: Optional["redis.Redis"] = None,
        ttl: int = FileCacheOperations.DEFAULT_TTL,
        paranoid_mode: bool = False
    ):
        """Initialize cache manager with fallback support.

        Args:
            redis_client: Redis client instance (optional - can be None for fallback).
            ttl: Time-to-live for cache entries in seconds.
            paranoid_mode: If True, always verify content hash even when mtime+size match.
        """
        if redis_client is not None:
            # Use Redis directly
            FileCacheOperations.__init__(self, redis_client, ttl, paranoid_mode)
            DirectoryCacheOperations.__init__(self, redis_client, ttl)
            self.enabled = True
            self.null_cache = False
            log.info(
                "Ingestion cache manager initialized with Redis (paranoid_mode=%s)",
                paranoid_mode
            )
        else:
            # Use null cache (no caching)
            self.enabled = False
            self.null_cache = True
            self.null_manager = NullCacheManager()
            log.warning("Redis unavailable, using null cache manager (no caching)")

    @classmethod
    def from_settings(cls, settings: Dict[str, Any], max_retries: int = 10) -> "IngestionCacheManager":
        """Create cache manager from settings with connection retry and graceful fallback.

        Args:
            settings: Configuration dictionary.
            max_retries: Maximum number of connection attempts.

        Returns:
            Cache manager instance (may be in null cache mode if Redis unavailable).
        """
        if not REDIS_AVAILABLE:
            log.warning("redis-py is not installed. Using null cache manager.")
            return cls(redis_client=None)

        cache_config = settings.get("CACHES", {}).get("default", {})
        location = cache_config.get("LOCATION", "").strip()

        # Build Redis URL from centralized settings module
        if not location:
            from src.conf import settings as global_settings
            redis_host = global_settings.REDIS_HOST or "127.0.0.1"
            redis_port = global_settings.REDIS_PORT or 6379
            location = f"redis://{redis_host}:{redis_port}/0"

        from src.conf import settings as global_settings
        redis_password = global_settings.REDIS_PASSWORD or None

        # Retry logic with exponential backoff
        delay = 1.0
        max_delay = 5.0

        for attempt in range(1, max_retries + 1):
            try:
                if attempt == 1:
                    log.info("Connecting to Redis at %s...", location)
                else:
                    log.info(
                        "Attempting to connect to Redis at %s (attempt %d/%d)",
                        location, attempt, max_retries
                    )

                client = redis_module.from_url(
                    location,
                    password=redis_password,
                    decode_responses=True,
                    socket_connect_timeout=3,
                    socket_timeout=3,
                )

                # Test connection
                client.ping()
                log.info("Successfully connected to Redis cache at %s", location)
                return cls(redis_client=client)

            except Exception as e:
                # Handle all Redis connection errors
                error_msg = str(e)
                
                if attempt == max_retries:
                    log.warning(
                        "Failed to connect to Redis at %s after %d attempts. Last error: %s",
                        location, max_retries, error_msg
                    )
                    log.warning("Using null cache manager (Redis unavailable)")
                    return cls(redis_client=None)

                log.warning(
                    "Redis connection attempt %d/%d failed: %s. Retrying in %.1f seconds...",
                    attempt, max_retries, error_msg, delay
                )

                time.sleep(delay)
                delay = min(delay * 2, max_delay)  # Exponential backoff with cap

        # If we get here, all retries failed - use null cache
        log.warning("All Redis connection attempts failed. Using null cache manager.")
        return cls(redis_client=None)

    # Delegate methods to null manager when in null cache mode
    def get_file_metadata(self, file_path: str):
        """Get file metadata with null cache support."""
        if self.null_cache:
            return self.null_manager.get_file_metadata(file_path)
        return super().get_file_metadata(file_path)
    
    def set_file_metadata(self, metadata):
        """Set file metadata with null cache support."""
        if self.null_cache:
            # Convert metadata to simple dict for null cache
            return self.null_manager.set_file_metadata(metadata.file_path, metadata)
        return super().set_file_metadata(metadata)
    
    def find_files_by_hash(self, content_hash: str):
        """Find files by hash with null cache support."""
        if self.null_cache:
            return self.null_manager.get_files_by_hash(content_hash)
        return super().find_files_by_hash(content_hash)
    
    def invalidate_file(self, file_path: str):
        """Invalidate file with null cache support."""
        if self.null_cache:
            return self.null_manager.delete_file_metadata(file_path)
        return super().invalidate_file(file_path)
    
    def clear_all(self):
        """Clear all cache entries with null cache support."""
        if self.null_cache:
            return self.null_manager.clear_all()
        return super().clear_all()
    
    def update_stats(self, **kwargs):
        """Update stats with null cache support."""
        if self.null_cache:
            return self.null_manager.increment_stats(**kwargs)
        return super().update_stats(**kwargs)
    
    def get_stats(self):
        """Get stats with null cache support."""
        if self.null_cache:
            return self.null_manager.get_stats()
        return super().get_stats()

    # Re-expose utility methods for backwards compatibility
    def compute_file_hash(self, file_path: str, chunk_size: int = 8192):
        """Compute SHA256 hash of file content."""
        return compute_file_hash(file_path, chunk_size)

    def compute_directory_hash(self, dir_path: str):
        """Compute hash of directory structure (file names + mtimes)."""
        return compute_directory_hash(dir_path)


__all__ = ["IngestionCacheManager"]
