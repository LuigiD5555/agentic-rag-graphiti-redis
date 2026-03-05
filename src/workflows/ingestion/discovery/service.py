"""Main file discovery service."""

import os
from typing import List, Set, Tuple, Optional

from src.workflows.ingestion.options import DiscoveryOptions
from src.backends.storage.cache.ingestion import IngestionCacheManager
from src.workflows.query.audit import get_logger
from src.workflows.query.audit.decorators import logged, timed

from .cache import DiscoveryCacheManager
from .pattern_matching import PatternMatcher
from .filters import build_filters
from .scanner import DirectoryScanner
from .score_cache import compute_exts_hash

log = get_logger(__name__)


class FileDiscoveryService:
    """Service that walks the filesystem and selects candidate files for ingestion."""

    def __init__(
        self,
        cache_file: Optional[str] = None,
        cache_manager: Optional[IngestionCacheManager] = None,
        scan_checkpointer=None
    ):
        self.cache_mgr = DiscoveryCacheManager(cache_file, cache_manager)
        self.pattern_matcher = PatternMatcher()
        # Compute once per discovery session so all scan methods share the same hash
        try:
            import src.settings as _settings
            _exts_hash = compute_exts_hash(_settings)
        except Exception:
            _exts_hash = ""
        self.scanner = DirectoryScanner(
            self.cache_mgr, self.pattern_matcher, scan_checkpointer, exts_hash=_exts_hash
        )
        self._last_visited_dirs = 0
        self.scan_checkpointer = scan_checkpointer

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

        self.pattern_matcher.precompile_patterns(opts.excluded_globs)

        options_hash = self.cache_mgr.compute_options_hash(opts)

        filters = build_filters(opts, self.pattern_matcher)

        check_ext = bool(opts.allowed_exts)
        allowed_exts_lower = {ext.lower() for ext in opts.allowed_exts} if opts.allowed_exts else set()

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

            if self.pattern_matcher.matches_any_glob("", opts.excluded_globs, absolute_path=root):
                log.info("Skipping excluded root directory: %s", root)
                continue

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

            root_files: List[str] = []
            root_visited = self.scanner.scan_directory(
                root, root, filters, opts.excluded_globs,
                opts.follow_symlinks, root_files,
                progress_every, options_hash
            )

            files.extend(root_files)
            visited_dirs += root_visited

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
            sc_files = scan_stats.get('score_cache_file_skipped', 0)
            sc_dirs = scan_stats.get('score_cache_dir_skipped', 0)
            sc_partial = scan_stats.get('score_cache_dir_partial', 0)
            if sc_files or sc_dirs or sc_partial:
                log.info(
                    "Score cache: %d files skipped, %d dirs skipped, %d dirs partial",
                    sc_files, sc_dirs, sc_partial
                )

            total_skipped = (
                scan_stats['paths_skipped_visited'] +
                scan_stats['paths_skipped_excluded']
            )
            if total_skipped > 0:
                log.info(
                    "Performance boost: %d path operations avoided via tree optimization",
                    total_skipped
                )

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

        self.pattern_matcher.precompile_patterns(opts.excluded_globs)

        options_hash = self.cache_mgr.compute_options_hash(opts)

        filters = build_filters(opts, self.pattern_matcher)

        check_ext = bool(opts.allowed_exts)
        allowed_exts_lower = {ext.lower() for ext in opts.allowed_exts} if opts.allowed_exts else set()

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

                if self.pattern_matcher.matches_any_glob("", opts.excluded_globs, absolute_path=root):
                    log.info("Skipping excluded root directory: %s", root)
                    continue

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
                sc_files = scan_stats.get('score_cache_file_skipped', 0)
                sc_dirs = scan_stats.get('score_cache_dir_skipped', 0)
                sc_partial = scan_stats.get('score_cache_dir_partial', 0)
                if sc_files or sc_dirs or sc_partial:
                    log.info(
                        "Score cache: %d files skipped, %d dirs skipped, %d dirs partial",
                        sc_files, sc_dirs, sc_partial
                    )

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

    @logged("Starting resumable file discovery")
    @timed()
    def discover_resumable(
        self,
        opts: DiscoveryOptions,
        scan_run_id: Optional[str] = None,
        use_cache: bool = True
    ) -> Tuple[List[str], int, str]:
        """
        Traverse roots with checkpoint support for resumable scanning.

        Args:
            opts: Discovery options
            scan_run_id: Optional run_id to resume (None = new run)
            use_cache: Whether to use caching

        Returns:
            Tuple of (list of file paths, number of visited directories, run_id)
        """
        if not self.scan_checkpointer:
            log.warning("No scan checkpointer available, falling back to regular discovery")
            files, visited = self.discover(opts, use_cache)
            return files, visited, ""

        discovered_files: List[str] = []
        visited_dirs = 0
        progress_every = getattr(opts, "progress_every", 0)

        self.pattern_matcher.precompile_patterns(opts.excluded_globs)

        options_hash = self.cache_mgr.compute_options_hash(opts)

        filters = build_filters(opts, self.pattern_matcher)

        check_ext = bool(opts.allowed_exts)
        allowed_exts_lower = {ext.lower() for ext in opts.allowed_exts} if opts.allowed_exts else set()

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
                        discovered_files.append(root)
                continue

            if self.pattern_matcher.matches_any_glob("", opts.excluded_globs, absolute_path=root):
                log.info("Skipping excluded root directory: %s", root)
                continue

            if use_cache:
                cached = self.cache_mgr.is_dir_unchanged(root, options_hash)
                if cached:
                    self.cache_mgr.record_hit()
                    discovered_files.extend(cached.files)
                    visited_dirs += 1
                    log.info(
                        "OK cache hit for %s: %d files (saved scanning)",
                        root, len(cached.files)
                    )
                    continue
                else:
                    self.cache_mgr.record_miss()

            root_files: List[str] = []
            root_visited, new_scan_run_id = self.scanner.scan_directory_resumable(
                root, filters, opts.excluded_globs,
                opts.follow_symlinks, root_files,
                progress_every, options_hash, scan_run_id
            )

            discovered_files.extend(root_files)
            visited_dirs += root_visited
            scan_run_id = new_scan_run_id  # Update run_id for subsequent roots

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

            total_skipped = (
                scan_stats['paths_skipped_visited'] +
                scan_stats['paths_skipped_excluded']
            )
            if total_skipped > 0:
                log.info(
                    "Performance boost: %d path operations avoided via tree optimization",
                    total_skipped
                )

        discovered_files = list(dict.fromkeys(discovered_files))
        discovered_files.sort()
        return discovered_files, visited_dirs, scan_run_id or ""


__all__ = ["FileDiscoveryService"]
