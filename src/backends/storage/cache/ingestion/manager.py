"""Ingestion cache manager (SQLite-only, no external cache)."""

from typing import Dict, Any, Optional

from src.workflows.query.audit import get_logger
from src.utils.hashing import compute_file_hash, compute_directory_hash

log = get_logger(__name__)


class IngestionCacheManager:
    """No-op cache manager to keep ingestion pipeline interfaces stable."""

    def __init__(
        self,
        enabled: bool = False,
        paranoid_mode: bool = False,
    ):
        self.enabled = enabled
        self.paranoid_mode = paranoid_mode

    @classmethod
    def from_settings(cls, settings: Dict[str, Any], max_retries: int = 10) -> "IngestionCacheManager":
        """Create cache manager from settings (always returns disabled cache)."""
        log.info("External cache disabled; using SQLite control plane only")
        return cls(enabled=False)

    # File cache operations (no-op)
    def get_file_metadata(self, file_path: str):
        return None

    def set_file_metadata(self, metadata) -> bool:
        return False

    def find_processed_file_by_hash(self, content_hash: str):
        return None

    def is_file_unchanged(self, file_path: str) -> bool:
        return False

    def invalidate_file(self, file_path: str) -> bool:
        return True

    # Directory cache operations (no-op)
    def get_directory_metadata(self, dir_path: str):
        return None

    def set_directory_metadata(self, metadata) -> bool:
        return False

    def clear_all(self) -> bool:
        return True

    def update_stats(self, **kwargs):
        return None

    def get_stats(self) -> Dict[str, Any]:
        return {
            "enabled": False,
            "backend": "null",
            "cached_files": 0,
            "cached_dirs": 0,
        }

    # Utility methods
    def compute_file_hash(self, file_path: str, chunk_size: int = 8192):
        return compute_file_hash(file_path, chunk_size)

    def compute_directory_hash(self, dir_path: str):
        return compute_directory_hash(dir_path)


__all__ = ["IngestionCacheManager"]
