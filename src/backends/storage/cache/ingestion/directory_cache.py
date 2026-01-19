"""Directory cache operations."""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis

from .redis_operations import RedisOperations


class DirectoryCacheOperations(RedisOperations):
    """Directory-specific cache operations."""


__all__ = ["DirectoryCacheOperations"]
