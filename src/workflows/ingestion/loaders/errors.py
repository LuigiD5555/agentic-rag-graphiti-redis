"""Loader exceptions — re-exported from the canonical domain hierarchy.

All loader exception classes now live in ``src.core.errors``.
This module re-exports them so existing imports keep working unchanged.
"""

import os
from src.core.errors import (
    LoaderError,
    LoaderFileNotFoundError,
    LoaderDependencyError,
    LoaderInvalidFormatError,
    LoaderUnreadableTextError,
)

__all__ = [
    "LoaderError",
    "LoaderFileNotFoundError",
    "LoaderDependencyError",
    "LoaderInvalidFormatError",
    "LoaderUnreadableTextError",
    "ensure_file_exists",
    "dependency_missing",
]


def ensure_file_exists(path: str) -> None:
    """Raise LoaderFileNotFoundError if the file does not exist."""
    if not os.path.isfile(path):
        raise LoaderFileNotFoundError(path)


def dependency_missing(dependency: str, detail: str | None = None) -> LoaderDependencyError:
    """Raise LoaderDependencyError with consistent messaging."""
    raise LoaderDependencyError(dependency, detail)
