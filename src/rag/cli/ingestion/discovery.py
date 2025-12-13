from __future__ import annotations

"""File discovery helpers for the ingestion CLI."""

import logging
import os
from pathlib import PurePosixPath
from typing import List, Set, Tuple

from src.rag.cli.options import DiscoveryOptions
from src.utils.decorators import logged, timed


class FileDiscoveryService:
    """Service that walks the filesystem and selects candidate files for ingestion."""

    class _Strategy:
        def allow_dir(self, rel_dirpath: str, dirname: str) -> bool:  # pragma: no cover - interface
            return True

        def allow_file(self, rel_dirpath: str, filename: str) -> bool:  # pragma: no cover - interface
            return True

    class _IgnoreDirsStrategy(_Strategy):
        def __init__(self, excluded: Set[str]):
            self._excluded = excluded

        def allow_dir(self, rel_dirpath: str, dirname: str) -> bool:
            return dirname not in self._excluded

    class _ExtFilterStrategy(_Strategy):
        def __init__(self, allowed_exts: Set[str]):
            self._allowed = allowed_exts

        def allow_file(self, rel_dirpath: str, filename: str) -> bool:
            if not self._allowed:
                return True
            _, ext = os.path.splitext(filename)
            return ext.lower() in self._allowed

    class _GlobExclusionStrategy(_Strategy):
        def __init__(self, patterns: Set[str]):
            self._patterns = patterns

        def allow_dir(self, rel_dirpath: str, dirname: str) -> bool:
            if not self._patterns:
                return True
            relative = dirname if not rel_dirpath else os.path.join(rel_dirpath, dirname)
            return not FileDiscoveryService._matches_any_glob(relative, self._patterns)

        def allow_file(self, rel_dirpath: str, filename: str) -> bool:
            if not self._patterns:
                return True
            relative = filename if not rel_dirpath else os.path.join(rel_dirpath, filename)
            return not FileDiscoveryService._matches_any_glob(relative, self._patterns)

    @logged("Starting file discovery")
    @timed()
    def discover(self, opts: DiscoveryOptions) -> Tuple[List[str], int]:
        """Traverse roots and return candidate file paths and visited directory count."""
        files: List[str] = []
        visited_dirs = 0
        progress_every = getattr(opts, "progress_every", 0)

        for raw_root in opts.roots:
            root = os.path.abspath(raw_root)
            if not os.path.exists(root):
                logging.warning("Root does not exist: %s", root)
                continue

            if os.path.isfile(root):
                rel_file = os.path.basename(root)
                if self._matches_any_glob(rel_file, opts.excluded_globs):
                    continue
                _, ext = os.path.splitext(root)
                if self._is_allowed_ext(ext, opts.allowed_exts):
                    files.append(root)
                continue

            filters = self._build_filters(opts)
            for dirpath, dirnames, filenames in os.walk(root, followlinks=opts.follow_symlinks):
                visited_dirs += 1
                if progress_every and visited_dirs % progress_every == 0:
                    logging.info("Scanning… visited=%d dir(s), current=%s", visited_dirs, dirpath)
                rel_dirpath = os.path.relpath(dirpath, root)
                if rel_dirpath == ".":
                    rel_dirpath = ""

                if rel_dirpath and self._matches_any_glob(rel_dirpath, opts.excluded_globs):
                    dirnames[:] = []
                    continue

                dirnames[:] = [d for d in dirnames if all(s.allow_dir(rel_dirpath, d) for s in filters)]
                for filename in filenames:
                    relative_file = filename if not rel_dirpath else os.path.join(rel_dirpath, filename)
                    if self._matches_any_glob(relative_file, opts.excluded_globs):
                        continue
                    if not all(s.allow_file(rel_dirpath, filename) for s in filters):
                        continue
                    files.append(os.path.join(dirpath, filename))

        files = sorted(set(files))
        return files, visited_dirs

    @staticmethod
    def _matches_any_glob(relative_path: str, patterns: Set[str]) -> bool:
        if not patterns:
            return False

        normalized = relative_path.replace("\\", "/")
        normalized = normalized.lstrip("./")
        normalized = normalized.strip("/")
        candidate = normalized or "."
        candidate_path = PurePosixPath(candidate)
        basename = normalized.rsplit("/", 1)[-1] if normalized else ""
        basename_path = PurePosixPath(basename or ".")

        for pattern in patterns:
            normalized_pattern = pattern.replace("\\", "/").strip()
            if not normalized_pattern:
                normalized_pattern = "."
            normalized_pattern = normalized_pattern.lstrip("./")
            if normalized_pattern.startswith("/"):
                normalized_pattern = normalized_pattern[1:]
            normalized_pattern = normalized_pattern.rstrip("/")
            if not normalized_pattern:
                normalized_pattern = "."
            if candidate_path.match(normalized_pattern):
                return True
            if basename and basename_path.match(normalized_pattern):
                return True
        return False

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
            filters.append(FileDiscoveryService._GlobExclusionStrategy(opts.excluded_globs))
        filters.append(FileDiscoveryService._ExtFilterStrategy(opts.allowed_exts))
        return filters
