"""Directory cache operations (SQLite-backed)."""

from .sqlite_operations import RedisOperations


class DirectoryCacheOperations(RedisOperations):
    """Directory-specific cache operations."""


__all__ = ["DirectoryCacheOperations"]
