"""Redis-based cache manager for file ingestion tracking.

This package provides a modular cache management system with the following components:

- models: Data classes for file and directory metadata
- hash_utils: Utilities for computing file and directory hashes
- redis_operations: Base Redis operations for cache management
- file_cache: File-specific cache operations
- directory_cache: Directory-specific cache operations
- manager: Main IngestionCacheManager class
"""

from .models import FileMetadata, DirectoryMetadata
from .manager import IngestionCacheManager
from src.utils.hashing import compute_file_hash, compute_directory_hash

__all__ = [
    "IngestionCacheManager",
    "FileMetadata",
    "DirectoryMetadata",
    "compute_file_hash",
    "compute_directory_hash",
]
