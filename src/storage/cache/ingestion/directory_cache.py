"""Directory cache operations."""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis

from .redis_operations import RedisOperations
from .hash_utils import compute_directory_hash


class DirectoryCacheOperations(RedisOperations):
    """Directory-specific cache operations."""

    def is_directory_unchanged(self, dir_path: str) -> bool:
        """Check if directory structure hasn't changed."""
        cached = self.get_directory_metadata(dir_path)
        if not cached:
            return False

        current_hash = compute_directory_hash(dir_path)
        return current_hash == cached.structure_hash


__all__ = ["DirectoryCacheOperations"]
