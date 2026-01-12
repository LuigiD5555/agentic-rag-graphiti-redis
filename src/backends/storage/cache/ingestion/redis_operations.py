"""Redis operations for cache manager."""
import json
from typing import TYPE_CHECKING, Optional, Set, Dict, Any
from dataclasses import asdict

if TYPE_CHECKING:
    import redis

from src.workflows.query.audit import get_logger
from .models import FileMetadata, DirectoryMetadata

log = get_logger(__name__)


class RedisOperations:
    """Base class for Redis operations."""

    # Cache key prefixes
    FILE_PREFIX = "ingestion:file:"
    DIR_PREFIX = "ingestion:dir:"
    HASH_PREFIX = "ingestion:hash:"
    STATS_KEY = "ingestion:stats"

    # Default TTL for cache entries (30 days)
    DEFAULT_TTL = 30 * 24 * 60 * 60

    def __init__(self, redis_client: "redis.Redis", ttl: int = DEFAULT_TTL):
        """Initialize Redis operations.

        Args:
            redis_client: Redis client instance.
            ttl: Time-to-live for cache entries in seconds.
        """
        self.redis = redis_client
        self.ttl = ttl

    def get_file_metadata(self, file_path: str) -> Optional[FileMetadata]:
        """Get cached metadata for a file."""
        key = f"{self.FILE_PREFIX}{file_path}"
        try:
            data = self.redis.get(key)
            if data:
                return FileMetadata(**json.loads(data))
        except Exception as e:
            log.debug("Redis get error for %s: %s", key, e)
        return None

    def set_file_metadata(self, metadata: FileMetadata) -> bool:
        """Store file metadata in cache."""
        key = f"{self.FILE_PREFIX}{metadata.file_path}"
        data = json.dumps(asdict(metadata))

        try:
            self.redis.setex(key, self.ttl, data)
            # Also index by content hash for deduplication
            hash_key = f"{self.HASH_PREFIX}{metadata.content_hash}"
            self.redis.sadd(hash_key, metadata.file_path)
            self.redis.expire(hash_key, self.ttl)
            return True
        except Exception as e:
            log.debug("Redis set error for %s: %s", key, e)
            return False

    def get_directory_metadata(self, dir_path: str) -> Optional[DirectoryMetadata]:
        """Get cached metadata for a directory."""
        key = f"{self.DIR_PREFIX}{dir_path}"
        try:
            data = self.redis.get(key)
            if data:
                return DirectoryMetadata(**json.loads(data))
        except Exception as e:
            log.debug("Redis get error for %s: %s", key, e)
        return None

    def set_directory_metadata(self, metadata: DirectoryMetadata) -> bool:
        """Store directory metadata in cache."""
        key = f"{self.DIR_PREFIX}{metadata.dir_path}"
        data = json.dumps(asdict(metadata))

        try:
            self.redis.setex(key, self.ttl, data)
            return True
        except Exception as e:
            log.debug("Redis set error for %s: %s", key, e)
            return False

    def find_files_by_hash(self, content_hash: str) -> Set[str]:
        """Find all files with the same content hash (duplicates)."""
        hash_key = f"{self.HASH_PREFIX}{content_hash}"
        try:
            return set(self.redis.smembers(hash_key))
        except Exception as e:
            log.debug("Redis error getting hash set %s: %s", hash_key, e)
            return set()

    def invalidate_file(self, file_path: str) -> bool:
        """Remove file from cache (force re-processing)."""
        key = f"{self.FILE_PREFIX}{file_path}"
        try:
            # Get metadata to remove from hash index
            cached = self.get_file_metadata(file_path)
            if cached:
                hash_key = f"{self.HASH_PREFIX}{cached.content_hash}"
                self.redis.srem(hash_key, file_path)

            self.redis.delete(key)
            return True
        except Exception as e:
            log.debug("Redis delete error for %s: %s", key, e)
            return False

    def invalidate_directory(self, dir_path: str) -> bool:
        """Remove directory from cache."""
        key = f"{self.DIR_PREFIX}{dir_path}"
        try:
            self.redis.delete(key)
            return True
        except Exception as e:
            log.debug("Redis delete error for %s: %s", key, e)
            return False

    def clear_all(self) -> bool:
        """Clear all ingestion cache entries."""
        try:
            # Use scan to find all keys with our prefixes
            for prefix in [self.FILE_PREFIX, self.DIR_PREFIX, self.HASH_PREFIX]:
                for key in self.redis.scan_iter(match=f"{prefix}*", count=100):
                    self.redis.delete(key)

            self.redis.delete(self.STATS_KEY)
            log.info("Cleared all ingestion cache entries from Redis")
            return True
        except Exception as e:
            log.error("Error clearing Redis cache: %s", e)
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            file_count = sum(1 for _ in self.redis.scan_iter(match=f"{self.FILE_PREFIX}*", count=100))
            dir_count = sum(1 for _ in self.redis.scan_iter(match=f"{self.DIR_PREFIX}*", count=100))

            return {
                'enabled': True,
                'backend': 'redis',
                'cached_files': file_count,
                'cached_directories': dir_count,
            }
        except Exception as e:
            log.debug("Error getting cache stats: %s", e)
            return {
                'enabled': True,
                'backend': 'redis',
                'error': str(e),
            }

    def update_stats(self, **kwargs) -> None:
        """Update global ingestion statistics."""
        try:
            for key, value in kwargs.items():
                self.redis.hincrby(self.STATS_KEY, key, value)
        except Exception as e:
            log.debug("Error updating stats: %s", e)


__all__ = ["RedisOperations"]
