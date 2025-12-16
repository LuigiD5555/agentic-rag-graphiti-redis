"""File discovery helpers for ingestion with intelligent caching."""

import os
import re
import time
import json
import hashlib
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import List, Set, Tuple, Dict, Optional
from dataclasses import dataclass, asdict

from src.rag.ingestion.options import DiscoveryOptions
from src.rag.ingestion.cache_manager import IngestionCacheManager
from src.rag.audit import get_logger
from src.rag.audit.decorators import logged, timed

log = get_logger(__name__)


@dataclass
class DirectoryScanCache:
    """Cache entry for a scanned directory."""
    mtime: float  # Modification time
    file_count: int  # Number of files found
    files: List[str]  # List of files
    subdirs_hash: str  # Hash of subdirectories structure
    scan_time: float  # When was it scanned
    options_hash: str  # Hash of scan options to detect config changes


class FileDiscoveryService:
    """Service that walks the filesystem and selects candidate files for ingestion."""

    def __init__(
        self,
        cache_file: Optional[str] = None,
        cache_manager: Optional[IngestionCacheManager] = None
    ):
        # Cache for compiled patterns
        self._pattern_cache = {}
        self._glob_cache = {}

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

    class _Strategy:
        def allow_dir(self, rel_dirpath: str, dirname: str, abs_path: str) -> bool:
            return True

        def allow_file(self, rel_dirpath: str, filename: str, abs_path: str) -> bool:
            return True

    class _IgnoreDirsStrategy(_Strategy):
        def __init__(self, excluded: Set[str]):
            self._excluded = excluded

        def allow_dir(self, rel_dirpath: str, dirname: str, abs_path: str) -> bool:
            return dirname not in self._excluded

    class _ExtFilterStrategy(_Strategy):
        def __init__(self, allowed_exts: Set[str]):
            self._allowed = allowed_exts
            self._allowed_lower = {ext.lower() for ext in allowed_exts} if allowed_exts else set()

        def allow_file(self, rel_dirpath: str, filename: str, abs_path: str) -> bool:
            if not self._allowed_lower:
                return True
            idx = filename.rfind('.')
            if idx == -1:
                return False
            ext = filename[idx:].lower()
            return ext in self._allowed_lower

    class _GlobExclusionStrategy(_Strategy):
        def __init__(self, patterns: Set[str], service):
            self._patterns = patterns
            self._service = service

        def allow_dir(self, rel_dirpath: str, dirname: str, abs_path: str) -> bool:
            if not self._patterns:
                return True
            relative = dirname if not rel_dirpath else f"{rel_dirpath}/{dirname}"
            return not self._service.matches_any_glob(relative, self._patterns, absolute_path=abs_path)

        def allow_file(self, rel_dirpath: str, filename: str, abs_path: str) -> bool:
            if not self._patterns:
                return True
            relative = filename if not rel_dirpath else f"{rel_dirpath}/{filename}"
            return not self._service.matches_any_glob(relative, self._patterns, absolute_path=abs_path)

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

    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            data = {path: asdict(entry) for path, entry in self._dir_cache.items()}
            with open(self._cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            log.debug("Saved discovery cache with %d entries", len(self._dir_cache))
        except Exception as e:
            log.warning("Failed to save cache: %s", e)

    def _compute_options_hash(self, opts: DiscoveryOptions) -> str:
        """Compute hash of discovery options to detect config changes."""
        config_str = json.dumps({
            'allowed_exts': sorted(opts.allowed_exts) if opts.allowed_exts else [],
            'excluded_dirs': sorted(opts.excluded_dirs) if opts.excluded_dirs else [],
            'excluded_globs': sorted(opts.excluded_globs) if opts.excluded_globs else [],
            'follow_symlinks': opts.follow_symlinks,
        }, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()

    def _get_dir_hash(self, dirpath: str) -> str:
        """Fast hash based on directory structure (names + count, not content)."""
        try:
            entries = os.listdir(dirpath)
            # Sort for consistency
            entries.sort()
            hash_input = f"{len(entries)}:{','.join(entries)}"
            return hashlib.md5(hash_input.encode()).hexdigest()
        except (OSError, PermissionError):
            return ""

    def _is_dir_unchanged(self, dirpath: str, options_hash: str) -> Optional[DirectoryScanCache]:
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
                current_hash = self._get_dir_hash(dirpath)
                if current_hash == cached.subdirs_hash:
                    return cached

        except (OSError, PermissionError):
            pass

        return None

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

    def get_cache_stats(self) -> Dict[str, int]:
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

    @logged("Starting file discovery")
    @timed()
    def discover(self, opts: DiscoveryOptions, use_cache: bool = True) -> Tuple[List[str], int]:
        """Traverse roots and return candidate file paths and visited directory count.

        Priority logic:
        1. If enabled_paths is provided and non-empty, ONLY scan those paths (ignore roots)
        2. Otherwise, scan all roots
        3. In both cases, apply exclusion rules (excluded_dirs, excluded_globs)
        """
        files: List[str] = []
        visited_dirs = 0
        accepted_files = 0
        progress_every = getattr(opts, "progress_every", 0)
        last_progress = time.monotonic()

        # Pre-compilation of patterns for reuse
        self._precompile_patterns(opts.excluded_globs)

        # Compute options hash for cache validation
        options_hash = self._compute_options_hash(opts)

        # Preparing filters once
        filters = self._build_filters(opts)

        # Pre-calculation if allowed extensions is empty
        check_ext = bool(opts.allowed_exts)
        allowed_exts_lower = {ext.lower() for ext in opts.allowed_exts} if opts.allowed_exts else set()

        # Determine which paths to scan based on enabled_paths priority
        paths_to_scan = opts.enabled_paths if opts.enabled_paths else opts.roots

        if opts.enabled_paths:
            log.info(
                "Using enabled paths whitelist (%d paths). Ignoring DOCS_PATHS.",
                len(opts.enabled_paths)
            )
        else:
            log.info("No enabled paths specified. Scanning all DOCS_PATHS (%d roots).", len(opts.roots))

        for raw_root in paths_to_scan:
            root = os.path.abspath(raw_root)
            if not os.path.exists(root):
                log.warning("Root does not exist: %s", root)
                continue

            if os.path.isfile(root):
                rel_file = os.path.basename(root)
                if self.matches_any_glob(rel_file, opts.excluded_globs, absolute_path=root):
                    continue
                idx = root.rfind('.')
                if idx != -1:
                    ext = root[idx:].lower()
                    if not check_ext or ext in allowed_exts_lower:
                        files.append(root)
                continue

            # Check if the root directory itself is excluded before scanning
            if self.matches_any_glob("", opts.excluded_globs, absolute_path=root):
                log.info("Skipping excluded root directory: %s", root)
                continue

            # Optimization: use cached results if available
            if use_cache:
                cached = self._is_dir_unchanged(root, options_hash)
                if cached:
                    self._cache_hits += 1
                    files.extend(cached.files)
                    visited_dirs += 1
                    log.info(
                        "✓ Cache HIT for %s: %d files (saved scanning)",
                        root, len(cached.files)
                    )
                    continue
                else:
                    self._cache_misses += 1

            # Need to scan
            root_files: List[str] = []
            root_visited = self._scan_directory_optimized(
                root, root, filters, opts.excluded_globs,
                opts.follow_symlinks, root_files,
                visited_dirs, accepted_files,
                progress_every, last_progress, options_hash
            )
            
            files.extend(root_files)
            visited_dirs += root_visited
            accepted_files += len(root_files)

        # Save cache to disk
        if use_cache:
            self._save_cache()
            stats = self.get_cache_stats()
            log.info(
                "Cache stats: hits=%d, misses=%d, hit_rate=%.1f%%",
                stats['cache_hits'], stats['cache_misses'], stats['hit_rate']
            )

        # Use set for deduplication
        files = list(dict.fromkeys(files))
        files.sort()
        return files, visited_dirs

    def _scan_directory_optimized(
        self, root, current_path, filters, excluded_globs,
        follow_symlinks, files, visited_dirs, accepted_files,
        progress_every, last_progress, options_hash
    ) -> int:
        """Scan directory with caching support."""
        stack = [(current_path, "")]
        dirs_scanned = 0

        while stack:
            dirpath, rel_dirpath = stack.pop()
            
            # Check cache for this specific directory
            cached = self._is_dir_unchanged(dirpath, options_hash)
            if cached:
                self._cache_hits += 1
                files.extend(cached.files)
                dirs_scanned += 1
                log.debug("✓ Cache hit for subdirectory: %s", dirpath)
                continue
            
            self._cache_misses += 1
            dirs_scanned += 1

            # Verify if current directory is excluded BEFORE processing it
            if rel_dirpath and self.matches_any_glob(rel_dirpath, excluded_globs, absolute_path=dirpath):
                log.debug("Skipping excluded directory: %s", dirpath)
                continue

            # Optimized logging
            now = time.monotonic()
            should_log = (progress_every and dirs_scanned % progress_every == 0) or \
                (not progress_every and (now - last_progress) >= 2.0)

            if should_log:
                log.info(
                    "Scanning… visited=%d dir(s), accepted=%d file(s), current=%s",
                    dirs_scanned, len(files), dirpath
                )
                last_progress = now

            dir_files: List[str] = []
            subdirs: List[str] = []

            try:
                # scandir is faster than listdir + multiple stat calls
                with os.scandir(dirpath) as entries:
                    dirs_to_add = []

                    for entry in entries:
                        try:
                            is_dir = entry.is_dir(follow_symlinks=follow_symlinks)

                            if is_dir:
                                subdirs.append(entry.name)
                                # Calculate the new relative path for the subdirectory
                                new_rel = entry.name if not rel_dirpath else f"{rel_dirpath}/{entry.name}"

                                # Check if this subdirectory matches any exclusion patterns BEFORE adding to stack
                                if self.matches_any_glob(new_rel, excluded_globs, absolute_path=entry.path):
                                    log.debug("Skipping excluded subdirectory before scanning: %s", entry.path)
                                    continue

                                # Apply other filters (like excluded_dirs)
                                if all(s.allow_dir(rel_dirpath, entry.name, entry.path) for s in filters):
                                    dirs_to_add.append((entry.path, new_rel))
                            else:
                                # Process file
                                relative_file = entry.name if not rel_dirpath else f"{rel_dirpath}/{entry.name}"

                                if self.matches_any_glob(relative_file, excluded_globs, absolute_path=entry.path):
                                    continue

                                if all(s.allow_file(rel_dirpath, entry.name, entry.path) for s in filters):
                                    files.append(entry.path)
                                    dir_files.append(entry.path)

                        except (OSError, PermissionError) as e:
                            log.debug("Error accessing %s: %s", entry.path, e)
                            continue

                    # Add directories to stack (reverse order to maintain alphabetical order)
                    stack.extend(reversed(dirs_to_add))

                # Cache this directory's results
                try:
                    stat = os.stat(dirpath)
                    dir_hash = self._get_dir_hash(dirpath)
                    scan_time = time.time()

                    # Save to file-based cache
                    self._dir_cache[dirpath] = DirectoryScanCache(
                        mtime=stat.st_mtime,
                        file_count=len(dir_files),
                        files=dir_files,
                        subdirs_hash=dir_hash,
                        scan_time=scan_time,
                        options_hash=options_hash
                    )

                    # Save to Redis cache if available
                    if self.cache_manager:
                        from src.rag.ingestion.cache_manager import DirectoryMetadata
                        total_size = sum(
                            os.path.getsize(f) for f in dir_files if os.path.exists(f)
                        )
                        dir_meta = DirectoryMetadata(
                            dir_path=dirpath,
                            structure_hash=dir_hash,
                            file_count=len(dir_files),
                            last_scanned=scan_time,
                            total_size=total_size
                        )
                        self.cache_manager.set_directory_metadata(dir_meta)

                except (OSError, PermissionError):
                    pass

            except (OSError, PermissionError) as e:
                log.warning("Cannot access directory %s: %s", dirpath, e)
                continue

        return dirs_scanned

    def _precompile_patterns(self, patterns: Set[str]):
        """Pre-compile regex patterns for reuse."""
        for pattern in patterns:
            if pattern not in self._pattern_cache:
                normalized = str(pattern).replace("\\", "/").strip()
                self._pattern_cache[pattern] = normalized

    def matches_any_glob(self, relative_path: str, patterns: Set[str], *, absolute_path: str | None = None) -> bool:
        """Return True if the candidate path matches any exclusion pattern."""
        if not patterns:
            return False

        # Cache key for optimization
        cache_key = (relative_path, absolute_path, frozenset(patterns))
        if cache_key in self._glob_cache:
            return self._glob_cache[cache_key]

        # Optimized normalization
        normalized = relative_path.replace("\\", "/").lstrip("./").strip("/") or "."
        candidate_path = PurePosixPath(normalized)
        basename = normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized
        basename_path = PurePosixPath(basename or ".")

        abs_candidate_path = None
        abs_basename_path = None
        abs_candidate_str = None

        if absolute_path:
            abs_candidate_str = os.path.abspath(absolute_path).replace("\\", "/").rstrip("/") or "/"
            abs_candidate_path = PurePosixPath(abs_candidate_str)
            abs_basename_str = abs_candidate_str.rsplit("/", 1)[-1]
            abs_basename_path = PurePosixPath(abs_basename_str or ".")

        result = self._match_patterns(
            patterns, normalized, candidate_path, basename, basename_path,
            abs_candidate_path, abs_basename_path, abs_candidate_str
        )

        # Caching Results
        self._glob_cache[cache_key] = result
        return result

    def _match_patterns(
        self, patterns, normalized, candidate_path, basename, basename_path,
        abs_candidate_path, abs_basename_path, abs_candidate_str
    ):
        """Separate matching logic for better performance."""
        for pattern in patterns:
            normalized_pattern = self._pattern_cache.get(pattern, pattern)
            # Only strip ./ prefix for relative paths, NOT for absolute paths
            if not normalized_pattern.startswith("/"):
                normalized_pattern = normalized_pattern.lstrip("./")

            for raw_pattern in self._pattern_variants(normalized_pattern.rstrip("/") or "."):
                is_abs = raw_pattern.startswith("/") or bool(re.match(r"^[A-Za-z]:/", raw_pattern))

                if is_abs and abs_candidate_str:
                    # Direct string comparison for absolute paths (most reliable)
                    if abs_candidate_str == raw_pattern:
                        return True
                    # Check if the candidate path starts with the pattern (prefix match for directories)
                    if abs_candidate_str.startswith(raw_pattern.rstrip("/") + "/"):
                        return True
                    # PurePosixPath.match and fnmatchcase for glob patterns
                    if abs_candidate_path and (
                        abs_candidate_path.match(raw_pattern) or
                        (abs_basename_path and abs_basename_path.match(raw_pattern)) or
                        fnmatchcase(abs_candidate_str, raw_pattern)
                    ):
                        return True
                    continue

                normalized_rel = raw_pattern.lstrip("/") or "."
                if (candidate_path.match(normalized_rel) or
                    (basename and basename_path.match(normalized_rel))):
                    return True

        return False

    @staticmethod
    def _pattern_variants(pattern_value: str):
        """Yield pattern variants - optimized."""
        yield pattern_value

        stripped = pattern_value.rstrip("/")
        if stripped != pattern_value:
            yield stripped

        for suffix in ("/**", "/**/*"):
            if stripped.endswith(suffix):
                base = stripped[:-len(suffix)].rstrip("/")
                if base:
                    yield base

    @staticmethod
    def _is_allowed_ext(ext: str, allowed: Set[str]) -> bool:
        if not allowed:
            return True
        return ext.lower() in allowed

    def _build_filters(self, opts: DiscoveryOptions):
        filters: list[FileDiscoveryService._Strategy] = []
        if opts.excluded_dirs:
            filters.append(FileDiscoveryService._IgnoreDirsStrategy(opts.excluded_dirs))
        if opts.excluded_globs:
            filters.append(FileDiscoveryService._GlobExclusionStrategy(opts.excluded_globs, self))
        filters.append(FileDiscoveryService._ExtFilterStrategy(opts.allowed_exts))
        return filters


__all__ = ["FileDiscoveryService", "DirectoryScanCache"]