"""File cache operations (SQLite-backed)."""

from pathlib import Path

from src.core import Result, emit_error
from src.core.errors import CacheError
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

    def is_file_unchanged(self, file_path: str) -> "Result[bool, CacheError]":
        """Check if file hasn't changed since last processing."""
        try:
            stat = Path(file_path).stat()
            current_mtime = stat.st_mtime
            current_size = stat.st_size

            cached = self.get_file_metadata(file_path)
            if not cached:
                return Result.ok(False)

            if abs(current_mtime - cached.mtime) > 0.001 or current_size != cached.size:
                return Result.ok(False)

            if self.paranoid_mode:
                hash_result = compute_file_hash(file_path)
                current_hash = hash_result.unwrap_or(None)
                if current_hash != cached.content_hash:
                    log.warning(
                        "Hash mismatch for %s (mtime unchanged but content differs)",
                        file_path,
                    )
                    return Result.ok(False)

            return Result.ok(cached.status == "processed")

        except (OSError, IOError) as exc:
            err = CacheError(f"Cannot stat file for cache check: {file_path}", cause=exc)
            emit_error(err, component="file_cache", operation="is_file_unchanged", extra={"path": file_path})
            return Result.err(err)

    def find_processed_file_by_hash(self, content_hash: str) -> "Result[FileMetadata | None, CacheError]":
        """Find first successfully processed file with this content hash."""
        try:
            files_with_hash = self.find_files_by_hash(content_hash)
            for file_path in files_with_hash:
                metadata = self.get_file_metadata(file_path)
                if metadata and metadata.status == "processed":
                    return Result.ok(metadata)
            return Result.ok(None)
        except Exception as exc:
            err = CacheError(f"Error finding processed file by hash {content_hash}", cause=exc)
            emit_error(err, component="file_cache", operation="find_processed_file_by_hash", extra={"content_hash": content_hash})
            return Result.err(err)


__all__ = ["FileCacheOperations"]
