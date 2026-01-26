"""File cache operations (SQLite-backed)."""

from pathlib import Path

from src.workflows.query.audit import get_logger
from .models import FileMetadata
from .sqlite_operations import RedisOperations
from src.utils.hashing import compute_file_hash

log = get_logger(__name__)


class FileCacheOperations(RedisOperations):
    """File-specific cache operations."""

    def __init__(self, ttl: int = RedisOperations.DEFAULT_TTL, paranoid_mode: bool = False):
        super().__init__(ttl)
        self.paranoid_mode = paranoid_mode

    def is_file_unchanged(self, file_path: str) -> bool:
        """Check if file hasn't changed since last processing."""
        try:
            stat = Path(file_path).stat()
            current_mtime = stat.st_mtime
            current_size = stat.st_size

            cached = self.get_file_metadata(file_path)
            if not cached:
                return False

            if abs(current_mtime - cached.mtime) > 0.001 or current_size != cached.size:
                return False

            if self.paranoid_mode:
                current_hash = compute_file_hash(file_path)
                if current_hash != cached.content_hash:
                    log.warning(
                        "Hash mismatch for %s (mtime unchanged but content differs)",
                        file_path,
                    )
                    return False

            return cached.status == "processed"

        except (OSError, IOError):
            return False

    def find_processed_file_by_hash(self, content_hash: str) -> FileMetadata | None:
        """Find first successfully processed file with this content hash."""
        try:
            files_with_hash = self.find_files_by_hash(content_hash)
            for file_path in files_with_hash:
                metadata = self.get_file_metadata(file_path)
                if metadata and metadata.status == "processed":
                    return metadata
        except Exception as exc:
            log.debug("Error finding processed file by hash %s: %s", content_hash, exc)
        return None


__all__ = ["FileCacheOperations"]
