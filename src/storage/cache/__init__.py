"""
Cache backends (Redis by default).
"""

from .redis_cache import CacheService

__all__ = ["CacheService"]
