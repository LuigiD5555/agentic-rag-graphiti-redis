"""Pattern matching utilities for file discovery."""

import os
import re
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Set, Dict


class PatternMatcher:
    """Handles glob pattern matching for file discovery."""

    def __init__(self):
        # Cache for compiled patterns
        self._pattern_cache: Dict[str, str] = {}
        self._glob_cache: Dict[tuple, bool] = {}

    def precompile_patterns(self, patterns: Set[str]) -> None:
        """Pre-compile regex patterns for reuse."""
        for pattern in patterns:
            if pattern not in self._pattern_cache:
                normalized = str(pattern).replace("\\", "/").strip()
                self._pattern_cache[pattern] = normalized

    def matches_any_glob(
        self,
        relative_path: str,
        patterns: Set[str],
        *,
        absolute_path: str | None = None
    ) -> bool:
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
        self,
        patterns,
        normalized,
        candidate_path,
        basename,
        basename_path,
        abs_candidate_path,
        abs_basename_path,
        abs_candidate_str
    ) -> bool:
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

    def clear_cache(self) -> None:
        """Clear pattern matching caches."""
        self._pattern_cache.clear()
        self._glob_cache.clear()


__all__ = ["PatternMatcher"]
