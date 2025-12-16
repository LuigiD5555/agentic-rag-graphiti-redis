"""File cache operations."""
from typing import TYPE_CHECKING, Optional
from pathlib import Path

if TYPE_CHECKING:
    import redis

from src.rag.audit import get_logger
from .models import FileMetadata
from .redis_operations import RedisOperations
from src.utils.hashing import compute_file_hash

log = get_logger(__name__)


class FileCacheOperations(RedisOperations):
    """File-specific cache operations."""

    def __init__(self, redis_client: "redis.Redis", ttl: int = RedisOperations.DEFAULT_TTL, paranoid_mode: bool = False):
        """Initialize file cache operations.

        Args:
            redis_client: Redis client instance.
            ttl: Time-to-live for cache entries in seconds.
            paranoid_mode: If True, always verify content hash even when mtime+size match.
        """
        super().__init__(redis_client, ttl)
        self.paranoid_mode = paranoid_mode

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
                current_hash = compute_file_hash(file_path)
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


__all__ = ["FileCacheOperations"]
