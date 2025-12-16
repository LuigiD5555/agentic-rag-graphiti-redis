"""Redis-based cache manager for file ingestion tracking."""
import json
import hashlib
from typing import TYPE_CHECKING, Optional, Dict, Any, Set
from dataclasses import dataclass, asdict
from pathlib import Path

if TYPE_CHECKING:
    import redis

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None  # type: ignore

from src.rag.audit import get_logger

log = get_logger(__name__)


@dataclass
class FileMetadata:
    """Metadata for a cached file."""
    file_path: str
    content_hash: str  # SHA256 hash of file content
    mtime: float  # Last modification time
    size: int  # File size in bytes
    last_processed: float  # Timestamp when file was last processed
    chunk_count: int  # Number of chunks generated
    embedding_count: int  # Number of embeddings created
    status: str  # 'processed', 'failed', 'skipped'
    error_message: Optional[str] = None


@dataclass
class DirectoryMetadata:
    """Metadata for a cached directory."""
    dir_path: str
    structure_hash: str  # Hash of directory structure (file names + mtimes)
    file_count: int
    last_scanned: float
    total_size: int  # Total size of all files in bytes


class IngestionCacheManager:
    """Redis-based cache manager for file ingestion.

    Redis is required - if unavailable, the manager will raise an error.
    This ensures predictable behavior and avoids silent performance degradation.
    """

    # Cache key prefixes
    FILE_PREFIX = "ingestion:file:"
    DIR_PREFIX = "ingestion:dir:"
    HASH_PREFIX = "ingestion:hash:"
    STATS_KEY = "ingestion:stats"

    # Default TTL for cache entries (30 days)
    DEFAULT_TTL = 30 * 24 * 60 * 60

    def __init__(self, redis_client: "redis.Redis", ttl: int = DEFAULT_TTL, paranoid_mode: bool = False):
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

        self.redis = redis_client
        self.ttl = ttl
        self.paranoid_mode = paranoid_mode
        self.enabled = True  # Cache is enabled when Redis is available
        log.info(
            "Ingestion cache manager initialized with Redis (paranoid_mode=%s)",
            paranoid_mode
        )

    @classmethod
    def from_settings(cls, settings: Dict[str, Any]) -> "IngestionCacheManager":
        """Create cache manager from settings.

        Raises:
            RuntimeError: If Redis is unavailable or connection fails.
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

        try:
            client = redis.from_url(
                location,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            # Test connection
            client.ping()
            log.info("Connected to Redis cache at %s", location)
            return cls(redis_client=client)
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Redis at {location}: {e}") from e

    def compute_file_hash(self, file_path: str, chunk_size: int = 8192) -> Optional[str]:
        """Compute SHA256 hash of file content."""
        try:
            hasher = hashlib.sha256()
            with open(file_path, 'rb') as f:
                while chunk := f.read(chunk_size):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (OSError, IOError) as e:
            log.debug("Cannot hash file %s: %s", file_path, e)
            return None

    def compute_directory_hash(self, dir_path: str) -> str:
        """Compute hash of directory structure (file names + mtimes)."""
        try:
            files = []
            for entry in Path(dir_path).iterdir():
                if entry.is_file():
                    stat = entry.stat()
                    files.append(f"{entry.name}:{stat.st_mtime}:{stat.st_size}")

            files.sort()
            hash_input = "|".join(files)
            return hashlib.md5(hash_input.encode()).hexdigest()
        except (OSError, IOError) as e:
            log.debug("Cannot hash directory %s: %s", dir_path, e)
            return ""

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

    def is_file_unchanged(self, file_path: str) -> bool:
        """Check if file hasn't changed since last processing.

        Performance optimization:
        - If paranoid_mode=False (default), trust mtime+size for 99.9% accuracy
        - If paranoid_mode=True, always verify content hash (slower but 100% accurate)

        Returns:
            True if file is unchanged and can be skipped.
        """
        try:
            # Get current file stats
            stat = Path(file_path).stat()
            current_mtime = stat.st_mtime
            current_size = stat.st_size

            # Get cached metadata
            cached = self.get_file_metadata(file_path)
            if not cached:
                return False

            # Quick check: mtime and size
            if abs(current_mtime - cached.mtime) > 0.001 or current_size != cached.size:
                return False

            # In paranoid mode, verify content hash even when mtime+size match
            if self.paranoid_mode:
                current_hash = self.compute_file_hash(file_path)
                if current_hash != cached.content_hash:
                    log.warning(
                        "Hash mismatch for %s (mtime unchanged but content differs)",
                        file_path
                    )
                    return False

            # File is unchanged if status is 'processed' and (mtime+size match OR hash matches)
            return cached.status == 'processed'

        except (OSError, IOError):
            return False

    def is_directory_unchanged(self, dir_path: str) -> bool:
        """Check if directory structure hasn't changed."""
        cached = self.get_directory_metadata(dir_path)
        if not cached:
            return False

        current_hash = self.compute_directory_hash(dir_path)
        return current_hash == cached.structure_hash

    def find_files_by_hash(self, content_hash: str) -> Set[str]:
        """Find all files with the same content hash (duplicates)."""
        hash_key = f"{self.HASH_PREFIX}{content_hash}"
        try:
            return set(self.redis.smembers(hash_key))
        except Exception as e:
            log.debug("Redis error getting hash set %s: %s", hash_key, e)
            return set()

    def find_processed_file_by_hash(self, content_hash: str) -> Optional[FileMetadata]:
        """Find first successfully processed file with this content hash.

        Returns metadata of the first file found with status='processed',
        or None if no processed file with this hash exists.
        """
        try:
            files_with_hash = self.find_files_by_hash(content_hash)
            for file_path in files_with_hash:
                metadata = self.get_file_metadata(file_path)
                if metadata and metadata.status == 'processed':
                    return metadata
        except Exception as e:
            log.debug("Error finding processed file by hash %s: %s", content_hash, e)
        return None

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


__all__ = ["IngestionCacheManager", "FileMetadata", "DirectoryMetadata"]