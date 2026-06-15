"""Ingestion cache manager backed by SQLite control plane."""

from typing import Dict, Any, Optional

from src.workflows.query.audit import get_logger
from src.utils.hashing import compute_file_hash, compute_directory_hash
from .file_cache import FileCacheOperations
from .directory_cache import DirectoryCacheOperations

log = get_logger(__name__)


class IngestionCacheManager(FileCacheOperations, DirectoryCacheOperations):
    """SQLite-based cache manager for file ingestion."""

    def __init__(
        self,
        ttl: int = FileCacheOperations.DEFAULT_TTL,
        paranoid_mode: bool = False,
    ):
        FileCacheOperations.__init__(self, ttl, paranoid_mode)
        DirectoryCacheOperations.__init__(self, ttl)
        self.enabled = True
        self.paranoid_mode = paranoid_mode
        log.info("Ingestion cache manager initialized with SQLite (paranoid_mode=%s)", paranoid_mode)

    @classmethod
    def from_settings(cls, settings: Dict[str, Any], max_retries: int = 10) -> "IngestionCacheManager":
        """Create cache manager from settings (SQLite only)."""
        _ = max_retries
        paranoid_mode = bool(settings.get("INGEST_PARANOID_MODE", False))
        return cls(paranoid_mode=paranoid_mode)

    # Utility methods
    def compute_file_hash(self, file_path: str, chunk_size: int = 8192):
        return compute_file_hash(file_path, chunk_size)

    def compute_directory_hash(self, dir_path: str):
        return compute_directory_hash(dir_path)


__all__ = ["IngestionCacheManager"]
