"""Directory scanning logic for file discovery."""

import os
import time
from typing import Set, Optional

from src.workflows.query.audit import get_logger
from .path_tree import PathTree

log = get_logger(__name__)


class DirectoryScanner:
    """Handles the actual filesystem traversal and file collection."""

    def __init__(self, cache_manager, pattern_matcher, scan_checkpointer=None):
        """
        Initialize scanner with cache manager and pattern matcher.

        Args:
            cache_manager: DiscoveryCacheManager instance
            pattern_matcher: PatternMatcher instance
            scan_checkpointer: Optional ScanCheckpointer for resumable scanning
        """
        self.cache_manager = cache_manager
        self.pattern_matcher = pattern_matcher
        self.scan_checkpointer = scan_checkpointer
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

    def scan_directory_resumable(
        self,
        root: str,
        filters: list,
        excluded_globs: Set[str],
        follow_symlinks: bool,
        files: list[str],
        progress_every: int,
        options_hash: str,
        run_id: Optional[str] = None
    ) -> tuple[int, str]:
        """
        Scan directory with resumable checkpoint support.

        This method uses ScanCheckpointer to enable resuming after interruptions.

        Args:
            root: Root directory to scan
            filters: List of FilterStrategy instances
            excluded_globs: Set of glob patterns to exclude
            follow_symlinks: Whether to follow symbolic links
            files: List to append discovered files to
            progress_every: Log progress every N directories
            options_hash: Hash of discovery options
            run_id: Optional run_id to resume (None = new run)

        Returns:
            Tuple of (dirs_scanned, run_id)
        """
        if not self.scan_checkpointer:
            log.warning("scan_directory_resumable called but no checkpointer available, using regular scan")
            dirs = self.scan_directory(
                root, root, filters, excluded_globs, follow_symlinks,
                files, progress_every, options_hash
            )
            return dirs, ""

        # Resume or start new run
        if run_id:
            scan_run = self.scan_checkpointer.resume_run(run_id)
            if not scan_run:
                log.error("Cannot resume run %s, starting new run", run_id)
                run_id = self.scan_checkpointer.start_new_run([root], options_hash)
        else:
            run_id = self.scan_checkpointer.start_new_run([root], options_hash)

        log.info("Starting resumable scan (run_id=%s)", run_id)

        dirs_scanned = 0
        last_progress = time.monotonic()
        processed_in_batch = 0
        BATCH_SIZE = 100  # Save progress every N directories

        try:
            while True:
                # Pop next directory from checkpoint queue
                dirpath = self.scan_checkpointer.pop_pending_directory(run_id)
                if not dirpath:
                    # Queue empty, scanning complete
                    break

                # Calculate relative path from root
                rel_dirpath = os.path.relpath(dirpath, root) if dirpath != root else ""

                # Check if already visited (idempotency)
                if self.scan_checkpointer.is_directory_visited(run_id, dirpath):
                    log.debug("SKIP already visited (checkpoint): %s", dirpath)
                    continue

                # OPTIMIZATION: Check tree-based exclusion
                if rel_dirpath and self.path_tree.is_path_excluded(rel_dirpath):
                    self._scan_stats['paths_skipped_excluded'] += 1
                    log.debug("SKIP tree exclusion for: %s", dirpath)
                    self.scan_checkpointer.mark_directory_visited(run_id, dirpath)
                    continue

                # OPTIMIZATION: Check cache
                cached = self.cache_manager.is_dir_unchanged(dirpath, options_hash)
                if cached:
                    self.cache_manager.record_hit()
                    self._scan_stats['cache_hits_tree'] += 1
                    files.extend(cached.files)
                    self.scan_checkpointer.add_discovered_files(run_id, cached.files)
                    dirs_scanned += 1
                    processed_in_batch += 1
                    self.scan_checkpointer.mark_directory_visited(run_id, dirpath)
                    log.debug("OK cache hit for subdirectory: %s", dirpath)
                    continue

                self.cache_manager.record_miss()
                dirs_scanned += 1
                processed_in_batch += 1

                # Verify if current directory is excluded by patterns
                if rel_dirpath and self.pattern_matcher.matches_any_glob(
                    rel_dirpath, excluded_globs, absolute_path=dirpath
                ):
                    self.path_tree.add_path(rel_dirpath, is_excluded=True)
                    self._scan_stats['paths_skipped_excluded'] += 1
                    log.debug("SKIP pattern exclusion for: %s (added to tree)", dirpath)
                    self.scan_checkpointer.mark_directory_visited(run_id, dirpath)
                    continue

                # Optimized logging
                now = time.monotonic()
                should_log = (progress_every and dirs_scanned % progress_every == 0) or \
                    (not progress_every and (now - last_progress) >= 2.0)

                if should_log:
                    pending_count = self.scan_checkpointer.get_pending_count(run_id)
                    log.info(
                        "Scanning... visited=%d dir(s), accepted=%d file(s), pending=%d, current=%s",
                        dirs_scanned, len(files), pending_count, dirpath
                    )
                    last_progress = now

                dir_files: list[str] = []
                subdirs_to_add = []

                try:
                    # scandir is faster than listdir
                    with os.scandir(dirpath) as entries:
                        for entry in entries:
                            try:
                                is_dir = entry.is_dir(follow_symlinks=follow_symlinks)

                                if is_dir:
                                    # Calculate relative path for subdirectory
                                    new_rel = entry.name if not rel_dirpath else f"{rel_dirpath}/{entry.name}"

                                    # Check if subdirectory matches exclusion patterns
                                    if self.pattern_matcher.matches_any_glob(
                                        new_rel, excluded_globs, absolute_path=entry.path
                                    ):
                                        log.debug("Skipping excluded subdirectory: %s", entry.path)
                                        continue

                                    # Apply other filters
                                    if all(s.allow_dir(rel_dirpath, entry.name, entry.path) for s in filters):
                                        subdirs_to_add.append((entry.path, new_rel))
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

                    # Cache this directory's results
                    self.cache_manager.cache_directory(dirpath, dir_files, options_hash)

                    # Add subdirectories to checkpoint queue
                    if subdirs_to_add:
                        # Extract just the directory paths from the tuples
                        dir_paths = [dir_path for dir_path, _ in subdirs_to_add]
                        self.scan_checkpointer.push_pending_directories(run_id, dir_paths)

                    # Add discovered files to checkpoint
                    if dir_files:
                        self.scan_checkpointer.add_discovered_files(run_id, dir_files)

                    # Mark directory as visited
                    self.scan_checkpointer.mark_directory_visited(run_id, dirpath)

                    # Save progress periodically
                    if processed_in_batch >= BATCH_SIZE:
                        self.scan_checkpointer.update_stats(
                            run_id,
                            dirs_visited_delta=processed_in_batch,
                            files_found_delta=len(dir_files)
                        )
                        processed_in_batch = 0

                except (OSError, PermissionError) as e:
                    log.warning("Cannot access directory %s: %s", dirpath, e)
                    self.scan_checkpointer.mark_directory_visited(run_id, dirpath)
                    continue

            # Final stats update
            if processed_in_batch > 0:
                self.scan_checkpointer.update_stats(
                    run_id,
                    dirs_visited_delta=processed_in_batch,
                    files_found_delta=0
                )

            # Mark run as completed
            self.scan_checkpointer.complete_run(run_id, status="completed")
            log.info("Scan run %s completed successfully (dirs=%d, files=%d)", run_id, dirs_scanned, len(files))

        except Exception as e:
            log.error("Scan interrupted: %s", e)
            self.scan_checkpointer.complete_run(run_id, status="interrupted")
            raise

        return dirs_scanned, run_id


__all__ = ["DirectoryScanner"]
