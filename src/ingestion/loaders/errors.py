"""Shared exceptions and helpers for ingestion loaders."""
from __future__ import annotations

import os
from typing import Optional


class LoaderError(Exception):
    """Base class for loader-related exceptions."""


class LoaderFileNotFoundError(LoaderError):
    """Raised when a loader cannot find the file to process."""

    def __init__(self, path: str):
        super().__init__(f"File not found: {path}")
        self.path = path


class LoaderDependencyError(LoaderError):
    """Raised when a loader requires an optional dependency."""

    def __init__(self, dependency: str, detail: Optional[str] = None):
        message = f"Required dependency missing: {dependency}"
        if detail:
            message = f"{message}. {detail}"
        super().__init__(message)
        self.dependency = dependency


class LoaderInvalidFormatError(LoaderError):
    """Raised when a file does not match the expected format."""

    def __init__(self, path: str, expected: str, detail: Optional[str] = None):
        message = f"Invalid format for {path}. Expected: {expected}"
        if detail:
            message = f"{message}. {detail}"
        super().__init__(message)
        self.path = path
        self.expected = expected


def ensure_file_exists(path: str) -> None:
    """Raise a consistent error if the input file does not exist."""
    if not os.path.isfile(path):
        raise LoaderFileNotFoundError(path)


def dependency_missing(dependency: str, detail: Optional[str] = None) -> LoaderDependencyError:
    """Helper to raise dependency errors with consistent messaging."""
    raise LoaderDependencyError(dependency, detail)
