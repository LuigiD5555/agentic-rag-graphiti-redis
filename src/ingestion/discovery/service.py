"""Main file discovery service."""

import os
from typing import List, Set, Tuple, Optional

from src.ingestion.options import DiscoveryOptions
from src.storage.cache.ingestion import IngestionCacheManager
from src.rag.audit import get_logger
from src.rag.audit.decorators import logged, timed

from .cache import DiscoveryCacheManager
from .pattern_matching import PatternMatcher
from .filters import build_filters
from .scanner import DirectoryScanner

log = get_logger(__name__)


class FileDiscoveryService:
    """Service that walks the filesystem and selects candidate files for ingestion."""

    def __init__(
        self,
        cache_file: Optional[str] = None,
        cache_manager: Optional[IngestionCacheManager] = None
    ):
        # Initialize components
        self.cache_mgr = DiscoveryCacheManager(cache_file, cache_manager)
        self.pattern_matcher = PatternMatcher()
        self.scanner = DirectoryScanner(self.cache_mgr, self.pattern_matcher)
        self._last_visited_dirs = 0

    @logged("Starting file discovery")
    @timed()
    def discover(self, opts: DiscoveryOptions, use_cache: bool = True) -> Tuple[List[str], int]:
        """
        Traverse roots and return candidate file paths and visited directory count.

        Priority logic:
        1. If enabled_paths is provided and non-empty, ONLY scan those paths (ignore roots)
        2. Otherwise, scan all roots
        3. In both cases, apply exclusion rules (excluded_dirs, excluded_globs)

        Args:
            opts: Discovery options
            use_cache: Whether to use caching

        Returns:
            Tuple of (list of file paths, number of visited directories)
        """
        files: List[str] = []
        visited_dirs = 0
        progress_every = getattr(opts, "progress_every", 0)

        # Pre-compilation of patterns for reuse
        self.pattern_matcher.precompile_patterns(opts.excluded_globs)

        # Compute options hash for cache validation
        options_hash = self.cache_mgr.compute_options_hash(opts)

        # Preparing filters once
        filters = build_filters(opts, self.pattern_matcher)

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
                if self.pattern_matcher.matches_any_glob(
                    rel_file, opts.excluded_globs, absolute_path=root
                ):
                    continue
                idx = root.rfind('.')
                if idx != -1:
                    ext = root[idx:].lower()
                    if not check_ext or ext in allowed_exts_lower:
                        files.append(root)
                continue

            # Check if the root directory itself is excluded before scanning
            if self.pattern_matcher.matches_any_glob("", opts.excluded_globs, absolute_path=root):
                log.info("Skipping excluded root directory: %s", root)
                continue

            # Optimization: use cached results if available
            if use_cache:
                cached = self.cache_mgr.is_dir_unchanged(root, options_hash)
                if cached:
                    self.cache_mgr.record_hit()
                    files.extend(cached.files)
                    visited_dirs += 1
                    log.info(
                        "OK cache hit for %s: %d files (saved scanning)",
                        root, len(cached.files)
                    )
                    continue
                else:
                    self.cache_mgr.record_miss()

            # Need to scan
            root_files: List[str] = []
            root_visited = self.scanner.scan_directory(
                root, root, filters, opts.excluded_globs,
                opts.follow_symlinks, root_files,
                progress_every, options_hash
            )

            files.extend(root_files)
            visited_dirs += root_visited

        # Save cache to disk
        if use_cache:
            self.cache_mgr.save_cache()
            cache_stats = self.get_cache_stats()
            scan_stats = self.scanner.get_scan_stats()

            log.info(
                "Cache stats: hits=%d, misses=%d, hit_rate=%.1f%%",
                cache_stats['cache_hits'], cache_stats['cache_misses'], cache_stats['hit_rate']
            )
            log.info(
                "Path optimization: skipped_visited=%d, skipped_excluded=%d, tree_nodes=%d",
                scan_stats['paths_skipped_visited'],
                scan_stats['paths_skipped_excluded'],
                scan_stats['path_tree']['total_nodes']
            )

            # Calculate total optimizations
            total_skipped = (
                scan_stats['paths_skipped_visited'] +
                scan_stats['paths_skipped_excluded']
            )
            if total_skipped > 0:
                log.info(
                    "Performance boost: %d path operations avoided via tree optimization",
                    total_skipped
                )

        # Use set for deduplication
        files = list(dict.fromkeys(files))
        files.sort()
        return files, visited_dirs

    @logged("Starting file discovery (streaming)")
    @timed()
    def discover_stream(self, opts: DiscoveryOptions, use_cache: bool = True):
        """
        Traverse roots and yield (directory_path, file_paths) as soon as they are found.

        Returns:
            Generator yielding (directory_path, [file_paths]) tuples.
        """
        visited_dirs = 0
        progress_every = getattr(opts, "progress_every", 0)

        # Pre-compilation of patterns for reuse
        self.pattern_matcher.precompile_patterns(opts.excluded_globs)

        # Compute options hash for cache validation
        options_hash = self.cache_mgr.compute_options_hash(opts)

        # Preparing filters once
        filters = build_filters(opts, self.pattern_matcher)

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

        try:
            for raw_root in paths_to_scan:
                root = os.path.abspath(raw_root)
                if not os.path.exists(root):
                    log.warning("Root does not exist: %s", root)
                    continue

                if os.path.isfile(root):
                    rel_file = os.path.basename(root)
                    if self.pattern_matcher.matches_any_glob(
                        rel_file, opts.excluded_globs, absolute_path=root
                    ):
                        continue
                    idx = root.rfind('.')
                    if idx != -1:
                        ext = root[idx:].lower()
                        if check_ext and ext not in allowed_exts_lower:
                            continue
                    parent = os.path.dirname(root) or os.path.abspath(".")
                    yield parent, [root]
                    continue

                # Check if the root directory itself is excluded before scanning
                if self.pattern_matcher.matches_any_glob("", opts.excluded_globs, absolute_path=root):
                    log.info("Skipping excluded root directory: %s", root)
                    continue

                # Optimization: use cached results if available
                if use_cache:
                    cached = self.cache_mgr.is_dir_unchanged(root, options_hash)
                    if cached:
                        self.cache_mgr.record_hit()
                        visited_dirs += 1
                        yield root, list(cached.files)
                        log.info(
                            "OK cache hit for %s: %d files (saved scanning)",
                            root, len(cached.files)
                        )
                        continue
                    else:
                        self.cache_mgr.record_miss()

                for dirpath, dir_files in self.scanner.scan_directory_stream(
                    root,
                    root,
                    filters,
                    opts.excluded_globs,
                    opts.follow_symlinks,
                    progress_every,
                    options_hash,
                ):
                    yield dirpath, dir_files

                visited_dirs += self.scanner.last_dirs_scanned

        finally:
            self._last_visited_dirs = visited_dirs

            # Save cache to disk
            if use_cache:
                self.cache_mgr.save_cache()
                cache_stats = self.get_cache_stats()
                scan_stats = self.scanner.get_scan_stats()

                log.info(
                    "Cache stats: hits=%d, misses=%d, hit_rate=%.1f%%",
                    cache_stats['cache_hits'], cache_stats['cache_misses'], cache_stats['hit_rate']
                )
                log.info(
                    "Path optimization: skipped_visited=%d, skipped_excluded=%d, tree_nodes=%d",
                    scan_stats['paths_skipped_visited'],
                    scan_stats['paths_skipped_excluded'],
                    scan_stats['path_tree']['total_nodes']
                )

                # Calculate total optimizations
                total_skipped = (
                    scan_stats['paths_skipped_visited'] +
                    scan_stats['paths_skipped_excluded']
                )
                if total_skipped > 0:
                    log.info(
                        "Performance boost: %d path operations avoided via tree optimization",
                        total_skipped
                    )

    def matches_any_glob(
        self,
        relative_path: str,
        patterns: Set[str],
        *,
        absolute_path: str | None = None
    ) -> bool:
        """
        Return True if the candidate path matches any exclusion pattern.

        This method is kept for backward compatibility.
        """
        return self.pattern_matcher.matches_any_glob(
            relative_path, patterns, absolute_path=absolute_path
        )

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self.cache_mgr.clear_cache()
        self.pattern_matcher.clear_cache()
        self.scanner.reset_stats()

    def get_cache_stats(self):
        """Get cache statistics."""
        return self.cache_mgr.get_stats()

    @property
    def last_visited_dirs(self) -> int:
        return self._last_visited_dirs

    def get_optimization_stats(self) -> dict:
        """
        Get comprehensive optimization statistics.

        Returns:
            Dictionary with cache stats, path tree stats, and performance metrics
        """
        cache_stats = self.get_cache_stats()
        scan_stats = self.scanner.get_scan_stats()

        return {
            'cache': cache_stats,
            'path_optimization': {
                'visited_skipped': scan_stats['paths_skipped_visited'],
                'excluded_skipped': scan_stats['paths_skipped_excluded'],
                'total_avoided': (
                    scan_stats['paths_skipped_visited'] +
                    scan_stats['paths_skipped_excluded']
                ),
                'tree_stats': scan_stats['path_tree']
            }
        }


__all__ = ["FileDiscoveryService"]
