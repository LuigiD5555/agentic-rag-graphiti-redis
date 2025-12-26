"""Directory scanning logic for file discovery."""

import os
import time
from typing import Set

from src.rag.audit import get_logger
from .path_tree import PathTree

log = get_logger(__name__)


class DirectoryScanner:
    """Handles the actual filesystem traversal and file collection."""

    def __init__(self, cache_manager, pattern_matcher):
        """
        Initialize scanner with cache manager and pattern matcher.

        Args:
            cache_manager: DiscoveryCacheManager instance
            pattern_matcher: PatternMatcher instance
        """
        self.cache_manager = cache_manager
        self.pattern_matcher = pattern_matcher
        self.path_tree = PathTree()
        self._scan_stats = {
            'paths_skipped_visited': 0,
            'paths_skipped_excluded': 0,
            'cache_hits_tree': 0
        }
        self._last_dirs_scanned = 0

    def scan_directory(
        self,
        root: str,
        current_path: str,
        filters: list,
        excluded_globs: Set[str],
        follow_symlinks: bool,
        files: list[str],
        progress_every: int,
        options_hash: str
    ) -> int:
        """
        Scan directory recursively with caching support and path tree optimization.

        Args:
            root: Root directory being scanned
            current_path: Current directory path
            filters: List of FilterStrategy instances
            excluded_globs: Set of glob patterns to exclude
            follow_symlinks: Whether to follow symbolic links
            files: List to append discovered files to
            progress_every: Log progress every N directories
            options_hash: Hash of discovery options

        Returns:
            Number of directories scanned
        """
        stack = [(current_path, "")]
        dirs_scanned = 0
        last_progress = time.monotonic()

        while stack:
            dirpath, rel_dirpath = stack.pop()

            # OPTIMIZATION 1: Check if already visited using path tree (O(k) lookup)
            if self.path_tree.is_visited(dirpath):
                self._scan_stats['paths_skipped_visited'] += 1
                log.debug("SKIP already visited: %s", dirpath)
                continue

            # OPTIMIZATION 2: Check tree-based exclusion first (O(k) vs O(n*m) for patterns)
            if rel_dirpath and self.path_tree.is_path_excluded(rel_dirpath):
                self._scan_stats['paths_skipped_excluded'] += 1
                log.debug("SKIP tree exclusion for: %s", dirpath)
                continue

            # OPTIMIZATION 3: Check cache for this specific directory
            cached = self.cache_manager.is_dir_unchanged(dirpath, options_hash)
            if cached:
                self.cache_manager.record_hit()
                self._scan_stats['cache_hits_tree'] += 1
                files.extend(cached.files)
                dirs_scanned += 1
                # Mark as visited in tree
                self.path_tree.mark_visited(dirpath)
                log.debug("OK cache hit for subdirectory: %s", dirpath)
                continue

            self.cache_manager.record_miss()
            dirs_scanned += 1

            # Verify if current directory is excluded by patterns (fallback for dynamic patterns)
            if rel_dirpath and self.pattern_matcher.matches_any_glob(
                rel_dirpath, excluded_globs, absolute_path=dirpath
            ):
                # Add to tree for future quick lookups
                self.path_tree.add_path(rel_dirpath, is_excluded=True)
                self._scan_stats['paths_skipped_excluded'] += 1
                log.debug("SKIP pattern exclusion for: %s (added to tree)", dirpath)
                continue

            # Optimized logging
            now = time.monotonic()
            should_log = (progress_every and dirs_scanned % progress_every == 0) or \
                (not progress_every and (now - last_progress) >= 2.0)

            if should_log:
                log.info(
                    "Scanning... visited=%d dir(s), accepted=%d file(s), current=%s",
                    dirs_scanned, len(files), dirpath
                )
                last_progress = now

            dir_files: list[str] = []

            try:
                # scandir is faster than listdir + multiple stat calls
                with os.scandir(dirpath) as entries:
                    dirs_to_add = []

                    for entry in entries:
                        try:
                            is_dir = entry.is_dir(follow_symlinks=follow_symlinks)

                            if is_dir:
                                # Calculate the new relative path for the subdirectory
                                new_rel = entry.name if not rel_dirpath else f"{rel_dirpath}/{entry.name}"

                                # Check if this subdirectory matches any exclusion patterns
                                if self.pattern_matcher.matches_any_glob(
                                    new_rel, excluded_globs, absolute_path=entry.path
                                ):
                                    log.debug("Skipping excluded subdirectory before scanning: %s", entry.path)
                                    continue

                                # Apply other filters (like excluded_dirs)
                                if all(s.allow_dir(rel_dirpath, entry.name, entry.path) for s in filters):
                                    dirs_to_add.append((entry.path, new_rel))
                            else:
                                # Process file
                                relative_file = entry.name if not rel_dirpath else f"{rel_dirpath}/{entry.name}"

                                if self.pattern_matcher.matches_any_glob(
                                    relative_file, excluded_globs, absolute_path=entry.path
                                ):
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
                self.cache_manager.cache_directory(dirpath, dir_files, options_hash)

                # Mark as visited in path tree
                self.path_tree.mark_visited(dirpath)

            except (OSError, PermissionError) as e:
                log.warning("Cannot access directory %s: %s", dirpath, e)
                continue

        return dirs_scanned

    def scan_directory_stream(
        self,
        root: str,
        current_path: str,
        filters: list,
        excluded_globs: Set[str],
        follow_symlinks: bool,
        progress_every: int,
        options_hash: str,
    ):
        """
        Scan directory recursively and yield (dirpath, files) per directory.

        Yields:
            Tuple of (directory_path, [file_paths]) for each visited directory.
        """
        stack = [(current_path, "")]
        dirs_scanned = 0
        accepted_files = 0
        last_progress = time.monotonic()

        try:
            while stack:
                dirpath, rel_dirpath = stack.pop()

                # OPTIMIZATION 1: Check if already visited using path tree (O(k) lookup)
                if self.path_tree.is_visited(dirpath):
                    self._scan_stats['paths_skipped_visited'] += 1
                    log.debug("SKIP already visited: %s", dirpath)
                    continue

                # OPTIMIZATION 2: Check tree-based exclusion first (O(k) vs O(n*m) for patterns)
                if rel_dirpath and self.path_tree.is_path_excluded(rel_dirpath):
                    self._scan_stats['paths_skipped_excluded'] += 1
                    log.debug("SKIP tree exclusion for: %s", dirpath)
                    continue

                # OPTIMIZATION 3: Check cache for this specific directory
                cached = self.cache_manager.is_dir_unchanged(dirpath, options_hash)
                if cached:
                    self.cache_manager.record_hit()
                    self._scan_stats['cache_hits_tree'] += 1
                    dirs_scanned += 1
                    self.path_tree.mark_visited(dirpath)
                    accepted_files += len(cached.files)
                    yield dirpath, list(cached.files)
                    continue

                self.cache_manager.record_miss()
                dirs_scanned += 1

                # Verify if current directory is excluded by patterns (fallback for dynamic patterns)
                if rel_dirpath and self.pattern_matcher.matches_any_glob(
                    rel_dirpath, excluded_globs, absolute_path=dirpath
                ):
                    # Add to tree for future quick lookups
                    self.path_tree.add_path(rel_dirpath, is_excluded=True)
                    self._scan_stats['paths_skipped_excluded'] += 1
                    log.debug("SKIP pattern exclusion for: %s (added to tree)", dirpath)
                    continue

                # Optimized logging
                now = time.monotonic()
                should_log = (progress_every and dirs_scanned % progress_every == 0) or \
                    (not progress_every and (now - last_progress) >= 2.0)

                if should_log:
                    log.info(
                        "Scanning... visited=%d dir(s), accepted=%d file(s), current=%s",
                        dirs_scanned, accepted_files, dirpath
                    )
                    last_progress = now

                dir_files: list[str] = []

                try:
                    # scandir is faster than listdir + multiple stat calls
                    with os.scandir(dirpath) as entries:
                        dirs_to_add = []

                        for entry in entries:
                            try:
                                is_dir = entry.is_dir(follow_symlinks=follow_symlinks)

                                if is_dir:
                                    # Calculate the new relative path for the subdirectory
                                    new_rel = entry.name if not rel_dirpath else f"{rel_dirpath}/{entry.name}"

                                    # Check if this subdirectory matches any exclusion patterns
                                    if self.pattern_matcher.matches_any_glob(
                                        new_rel, excluded_globs, absolute_path=entry.path
                                    ):
                                        log.debug("Skipping excluded subdirectory before scanning: %s", entry.path)
                                        continue

                                    # Apply other filters (like excluded_dirs)
                                    if all(s.allow_dir(rel_dirpath, entry.name, entry.path) for s in filters):
                                        dirs_to_add.append((entry.path, new_rel))
                                else:
                                    # Process file
                                    relative_file = entry.name if not rel_dirpath else f"{rel_dirpath}/{entry.name}"

                                    if self.pattern_matcher.matches_any_glob(
                                        relative_file, excluded_globs, absolute_path=entry.path
                                    ):
                                        continue

                                    if all(s.allow_file(rel_dirpath, entry.name, entry.path) for s in filters):
                                        dir_files.append(entry.path)

                            except (OSError, PermissionError) as e:
                                log.debug("Error accessing %s: %s", entry.path, e)
                                continue

                        # Add directories to stack (reverse order to maintain alphabetical order)
                        stack.extend(reversed(dirs_to_add))

                    # Cache this directory's results
                    self.cache_manager.cache_directory(dirpath, dir_files, options_hash)

                    # Mark as visited in path tree
                    self.path_tree.mark_visited(dirpath)

                    accepted_files += len(dir_files)
                    yield dirpath, dir_files

                except (OSError, PermissionError) as e:
                    log.warning("Cannot access directory %s: %s", dirpath, e)
                    continue

        finally:
            self._last_dirs_scanned = dirs_scanned

    def get_scan_stats(self) -> dict:
        """Get scanning statistics including path tree optimizations."""
        stats = self._scan_stats.copy()
        stats['path_tree'] = self.path_tree.get_stats()
        return stats

    def reset_stats(self) -> None:
        """Reset scanning statistics."""
        self._scan_stats = {
            'paths_skipped_visited': 0,
            'paths_skipped_excluded': 0,
            'cache_hits_tree': 0
        }
        self.path_tree.clear_visited()
        self._last_dirs_scanned = 0

    @property
    def last_dirs_scanned(self) -> int:
        return self._last_dirs_scanned


__all__ = ["DirectoryScanner"]
