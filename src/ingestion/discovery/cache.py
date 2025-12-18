"""Cache management for file discovery."""

import os
import json
import time
import hashlib
from typing import Dict, Optional
from dataclasses import dataclass, asdict

from src.ingestion.options import DiscoveryOptions
from src.storage.cache.ingestion import IngestionCacheManager, DirectoryMetadata
from src.rag.audit import get_logger

log = get_logger(__name__)


@dataclass
class DirectoryScanCache:
    """Cache entry for a scanned directory."""
    mtime: float  # Modification time
    file_count: int  # Number of files found
    files: list[str]  # List of files
    subdirs_hash: str  # Hash of subdirectories structure
    scan_time: float  # When was it scanned
    options_hash: str  # Hash of scan options to detect config changes


class DiscoveryCacheManager:
    """Manages caching for file discovery operations."""

    def __init__(
        self,
        cache_file: Optional[str] = None,
        cache_manager: Optional[IngestionCacheManager] = None
    ):
        # Redis-based cache manager (preferred)
        self.cache_manager = cache_manager

        # Legacy: Cache file for persistent storage (fallback)
        self._cache_file = cache_file or ".file_discovery_cache.json"
        self._dir_cache: Dict[str, DirectoryScanCache] = {}

        # Only load file cache if no Redis cache manager
        if not self.cache_manager:
            self._load_cache()

        # Statistics
        self._cache_hits = 0
        self._cache_misses = 0

    def _load_cache(self) -> None:
        """Load cache from disk."""
        if not os.path.exists(self._cache_file):
            return

        try:
            with open(self._cache_file, 'r') as f:
                data = json.load(f)
                for path, entry in data.items():
                    self._dir_cache[path] = DirectoryScanCache(**entry)
            log.info("Loaded discovery cache with %d entries from %s", len(self._dir_cache), self._cache_file)
        except Exception as e:
            log.warning("Failed to load cache: %s", e)
            self._dir_cache = {}

    def save_cache(self) -> None:
        """Save cache to disk."""
        try:
            data = {path: asdict(entry) for path, entry in self._dir_cache.items()}
            with open(self._cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            log.debug("Saved discovery cache with %d entries", len(self._dir_cache))
        except Exception as e:
            log.warning("Failed to save cache: %s", e)

    def compute_options_hash(self, opts: DiscoveryOptions) -> str:
        """Compute hash of discovery options to detect config changes."""
        config_str = json.dumps({
            'allowed_exts': sorted(opts.allowed_exts) if opts.allowed_exts else [],
            'excluded_dirs': sorted(opts.excluded_dirs) if opts.excluded_dirs else [],
            'excluded_globs': sorted(opts.excluded_globs) if opts.excluded_globs else [],
            'follow_symlinks': opts.follow_symlinks,
        }, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()

    def get_dir_hash(self, dirpath: str) -> str:
        """Fast hash based on directory structure (names + count, not content)."""
        try:
            entries = os.listdir(dirpath)
            # Sort for consistency
            entries.sort()
            hash_input = f"{len(entries)}:{','.join(entries)}"
            return hashlib.md5(hash_input.encode()).hexdigest()
        except (OSError, PermissionError):
            return ""

    def is_dir_unchanged(self, dirpath: str, options_hash: str) -> Optional[DirectoryScanCache]:
        """Check if directory hasn't changed since last scan."""
        # Try Redis cache first
        if self.cache_manager:
            try:
                dir_meta = self.cache_manager.get_directory_metadata(dirpath)
                if dir_meta:
                    # Verify structure hasn't changed
                    current_hash = self.cache_manager.compute_directory_hash(dirpath)
                    if current_hash == dir_meta.structure_hash:
                        # Convert to DirectoryScanCache format
                        return DirectoryScanCache(
                            mtime=0,  # Not used when using structure hash
                            file_count=dir_meta.file_count,
                            files=[],  # Will be populated if needed
                            subdirs_hash=dir_meta.structure_hash,
                            scan_time=dir_meta.last_scanned,
                            options_hash=options_hash
                        )
            except Exception as e:
                log.debug("Error checking Redis cache for directory %s: %s", dirpath, e)

        # Fallback to file-based cache
        if dirpath not in self._dir_cache:
            return None

        cached = self._dir_cache[dirpath]

        # Check if options changed
        if cached.options_hash != options_hash:
            return None

        try:
            # Get current mtime
            stat = os.stat(dirpath)
            current_mtime = stat.st_mtime

            # If mtime hasn't changed, directory likely unchanged
            if abs(current_mtime - cached.mtime) < 0.001:
                # Double-check with structure hash for extra safety
                current_hash = self.get_dir_hash(dirpath)
                if current_hash == cached.subdirs_hash:
                    return cached

        except (OSError, PermissionError):
            pass

        return None

    def cache_directory(
        self,
        dirpath: str,
        files: list[str],
        options_hash: str
    ) -> None:
        """Cache directory scan results."""
        try:
            stat = os.stat(dirpath)
            dir_hash = self.get_dir_hash(dirpath)
            scan_time = time.time()

            # Save to file-based cache
            self._dir_cache[dirpath] = DirectoryScanCache(
                mtime=stat.st_mtime,
                file_count=len(files),
                files=files,
                subdirs_hash=dir_hash,
                scan_time=scan_time,
                options_hash=options_hash
            )

            # Save to Redis cache if available
            if self.cache_manager:
                total_size = sum(
                    os.path.getsize(f) for f in files if os.path.exists(f)
                )
                dir_meta = DirectoryMetadata(
                    dir_path=dirpath,
                    structure_hash=dir_hash,
                    file_count=len(files),
                    last_scanned=scan_time,
                    total_size=total_size
                )
                self.cache_manager.set_directory_metadata(dir_meta)

        except (OSError, PermissionError):
            pass

    def clear_cache(self) -> None:
        """Clear all cached data."""
        # Clear Redis cache
        if self.cache_manager:
            self.cache_manager.clear_all()

        # Clear file-based cache
        self._dir_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        if os.path.exists(self._cache_file):
            os.remove(self._cache_file)
        log.info("Cache cleared")

    def record_hit(self) -> None:
        """Record a cache hit."""
        self._cache_hits += 1

    def record_miss(self) -> None:
        """Record a cache miss."""
        self._cache_misses += 1

    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        stats = {
            'cache_hits': self._cache_hits,
            'cache_misses': self._cache_misses,
            'cached_directories': len(self._dir_cache),
            'hit_rate': (
                self._cache_hits / (self._cache_hits + self._cache_misses) * 100)
                if (self._cache_hits + self._cache_misses) > 0 else 0.0
        }

        # Add Redis cache stats if available
        if self.cache_manager:
            redis_stats = self.cache_manager.get_stats()
            stats['redis'] = redis_stats

        return stats


__all__ = ["DirectoryScanCache", "DiscoveryCacheManager"]
