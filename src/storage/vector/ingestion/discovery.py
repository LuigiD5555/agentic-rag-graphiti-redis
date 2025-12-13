from __future__ import annotations

"""File discovery helpers for ingestion."""

import os
import re
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import List, Set, Tuple

from src.storage.vector.ingestion.options import DiscoveryOptions
from src.rag.audit import get_logger
from src.rag.audit.decorators import logged, timed

log = get_logger(__name__)


class FileDiscoveryService:
    """Service that walks the filesystem and selects candidate files for ingestion."""

    class _Strategy:
        def allow_dir(self, rel_dirpath: str, dirname: str, abs_path: str) -> bool:  # pragma: no cover - interface
            return True

        def allow_file(self, rel_dirpath: str, filename: str, abs_path: str) -> bool:  # pragma: no cover - interface
            return True

    class _IgnoreDirsStrategy(_Strategy):
        def __init__(self, excluded: Set[str]):
            self._excluded = excluded

        def allow_dir(self, rel_dirpath: str, dirname: str, abs_path: str) -> bool:
            return dirname not in self._excluded

    class _ExtFilterStrategy(_Strategy):
        def __init__(self, allowed_exts: Set[str]):
            self._allowed = allowed_exts

        def allow_file(self, rel_dirpath: str, filename: str, abs_path: str) -> bool:
            if not self._allowed:
                return True
            _, ext = os.path.splitext(filename)
            return ext.lower() in self._allowed

    class _GlobExclusionStrategy(_Strategy):
        def __init__(self, patterns: Set[str]):
            self._patterns = patterns

        def allow_dir(self, rel_dirpath: str, dirname: str, abs_path: str) -> bool:
            if not self._patterns:
                return True
            relative = dirname if not rel_dirpath else os.path.join(rel_dirpath, dirname)
            return not FileDiscoveryService._matches_any_glob(relative, self._patterns, absolute_path=abs_path)

        def allow_file(self, rel_dirpath: str, filename: str, abs_path: str) -> bool:
            if not self._patterns:
                return True
            relative = filename if not rel_dirpath else os.path.join(rel_dirpath, filename)
            return not FileDiscoveryService._matches_any_glob(relative, self._patterns, absolute_path=abs_path)

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
                log.warning("Root does not exist: %s", root)
                continue

            if os.path.isfile(root):
                rel_file = os.path.basename(root)
                if self._matches_any_glob(rel_file, opts.excluded_globs, absolute_path=root):
                    continue
                _, ext = os.path.splitext(root)
                if self._is_allowed_ext(ext, opts.allowed_exts):
                    files.append(root)
                continue

            filters = self._build_filters(opts)
            for dirpath, dirnames, filenames in os.walk(root, followlinks=opts.follow_symlinks):
                visited_dirs += 1
                if progress_every and visited_dirs % progress_every == 0:
                    log.info("Scanning… visited=%d dir(s), current=%s", visited_dirs, dirpath)
                rel_dirpath = os.path.relpath(dirpath, root)
                if rel_dirpath == ".":
                    rel_dirpath = ""

                if rel_dirpath and self._matches_any_glob(rel_dirpath, opts.excluded_globs, absolute_path=dirpath):
                    dirnames[:] = []
                    continue

                dirnames[:] = [
                    d
                    for d in dirnames
                    if all(s.allow_dir(rel_dirpath, d, os.path.join(dirpath, d)) for s in filters)
                ]
                for filename in filenames:
                    relative_file = filename if not rel_dirpath else os.path.join(rel_dirpath, filename)
                    abs_file = os.path.join(dirpath, filename)
                    if self._matches_any_glob(relative_file, opts.excluded_globs, absolute_path=abs_file):
                        continue
                    if not all(s.allow_file(rel_dirpath, filename, abs_file) for s in filters):
                        continue
                    files.append(abs_file)

        files = sorted(set(files))
        return files, visited_dirs

    @staticmethod
    def _matches_any_glob(relative_path: str, patterns: Set[str], *, absolute_path: str | None = None) -> bool:
        if not patterns:
            return False

        def _is_glob_like(value: str) -> bool:
            return any(char in value for char in "*?[]")

        normalized = relative_path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.strip("/")
        candidate = normalized or "."
        candidate_path = PurePosixPath(candidate)
        basename = normalized.rsplit("/", 1)[-1] if normalized else ""
        basename_path = PurePosixPath(basename or ".")

        abs_candidate_path: PurePosixPath | None = None
        abs_basename_path: PurePosixPath | None = None
        abs_candidate_str: str | None = None
        abs_basename_str: str | None = None
        if absolute_path:
            abs_normalized = os.path.abspath(absolute_path).replace("\\", "/").rstrip("/") or "/"
            abs_candidate_str = abs_normalized
            abs_candidate_path = PurePosixPath(abs_candidate_str)
            abs_basename_str = abs_candidate_str.rsplit("/", 1)[-1] if abs_candidate_str else ""
            abs_basename_path = PurePosixPath(abs_basename_str or ".")

        for pattern in patterns:
            normalized_pattern = pattern.replace("\\", "/").strip()
            if not normalized_pattern:
                normalized_pattern = "."
            while normalized_pattern.startswith("./"):
                normalized_pattern = normalized_pattern[2:]
            raw_pattern = normalized_pattern.rstrip("/") or "."

            is_abs = raw_pattern.startswith("/") or bool(re.match(r"^[A-Za-z]:/", raw_pattern))
            if is_abs and abs_candidate_path is not None and abs_candidate_str is not None:
                abs_pattern = raw_pattern
                if abs_candidate_path.match(abs_pattern):
                    return True
                if abs_basename_str and abs_basename_path is not None and abs_basename_path.match(abs_pattern):
                    return True
                # Works for both exact paths and glob patterns.
                if fnmatchcase(abs_candidate_str, abs_pattern):
                    return True
                continue

            normalized_pattern = raw_pattern.lstrip("/")
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


__all__ = ["FileDiscoveryService"]
