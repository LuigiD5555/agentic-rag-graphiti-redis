"""Cache backends (SQLite-only control plane, no external cache)."""

from typing import Any, Optional

from src.workflows.query.interfaces.cache_interface import CacheServiceProtocol


class NullCacheService(CacheServiceProtocol):
    """No-op cache implementation."""

    def get(self, key: str) -> Optional[str]:
        return None

    def set(self, key: str, value: object, ttl: int = 3600) -> None:
        return None


def get_cache(config: Any, alias: str = "default") -> CacheServiceProtocol:
    """Return a no-op cache service."""
    return NullCacheService()


__all__ = ["get_cache", "NullCacheService"]

# Re-export ingestion cache components for convenience
from .ingestion import (  # noqa: E402
    IngestionCacheManager,
    FileMetadata,
    DirectoryMetadata,
    compute_file_hash,
    compute_directory_hash,
)

__all__ += [
    "IngestionCacheManager",
    "FileMetadata",
    "DirectoryMetadata",
    "compute_file_hash",
    "compute_directory_hash",
]
