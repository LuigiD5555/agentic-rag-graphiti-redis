"""SQLite connection module."""

from .sqlite_cache import SQLiteCacheService


def get_sqlite_cache_service() -> SQLiteCacheService:
    """Return SQLite-backed cache service."""
    return SQLiteCacheService()


__all__ = ["get_sqlite_cache_service"]
