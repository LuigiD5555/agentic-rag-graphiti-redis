"""Filtering strategies for file discovery."""

from typing import Set


class FilterStrategy:
    """Base strategy for filtering files and directories during discovery."""

    def allow_dir(self, rel_dirpath: str, dirname: str, abs_path: str) -> bool:
        """Determine if a directory should be traversed."""
        return True

    def allow_file(self, rel_dirpath: str, filename: str, abs_path: str) -> bool:
        """Determine if a file should be included in results."""
        return True


class IgnoreDirsStrategy(FilterStrategy):
    """Strategy that excludes specific directory names."""

    def __init__(self, excluded: Set[str]):
        self._excluded = excluded

    def allow_dir(self, rel_dirpath: str, dirname: str, abs_path: str) -> bool:
        return dirname not in self._excluded


class ExtFilterStrategy(FilterStrategy):
    """Strategy that filters files by extension."""

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


class GlobExclusionStrategy(FilterStrategy):
    """Strategy that excludes files and directories based on glob patterns."""

    def __init__(self, patterns: Set[str], pattern_matcher):
        """
        Initialize with glob patterns and a pattern matcher.

        Args:
            patterns: Set of glob patterns to exclude
            pattern_matcher: Object with matches_any_glob method
        """
        self._patterns = patterns
        self._pattern_matcher = pattern_matcher

    def allow_dir(self, rel_dirpath: str, dirname: str, abs_path: str) -> bool:
        if not self._patterns:
            return True
        relative = dirname if not rel_dirpath else f"{rel_dirpath}/{dirname}"
        return not self._pattern_matcher.matches_any_glob(
            relative, self._patterns, absolute_path=abs_path
        )

    def allow_file(self, rel_dirpath: str, filename: str, abs_path: str) -> bool:
        if not self._patterns:
            return True
        relative = filename if not rel_dirpath else f"{rel_dirpath}/{filename}"
        return not self._pattern_matcher.matches_any_glob(
            relative, self._patterns, absolute_path=abs_path
        )


def build_filters(opts, pattern_matcher) -> list[FilterStrategy]:
    """
    Build a list of filter strategies from discovery options.

    Args:
        opts: DiscoveryOptions instance
        pattern_matcher: Object with matches_any_glob method

    Returns:
        List of FilterStrategy instances
    """
    filters: list[FilterStrategy] = []

    if opts.excluded_dirs:
        filters.append(IgnoreDirsStrategy(opts.excluded_dirs))

    if opts.excluded_globs:
        filters.append(GlobExclusionStrategy(opts.excluded_globs, pattern_matcher))

    filters.append(ExtFilterStrategy(opts.allowed_exts))

    return filters


__all__ = [
    "FilterStrategy",
    "IgnoreDirsStrategy",
    "ExtFilterStrategy",
    "GlobExclusionStrategy",
    "build_filters"
]
