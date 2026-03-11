"""Hashing utilities for files, directories, and text.

This module provides consistent hashing functions used across the codebase
for cache management, content deduplication, and file identification.
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional

from src.core import Result, emit_error
from src.core.errors import StorageError

try:
    from src.workflows.query.audit import get_logger
except Exception:  # pragma: no cover - fallback for minimal containers
    def get_logger(name: str | None = None) -> logging.Logger:
        return logging.getLogger(name or "rag")

log = get_logger(__name__)


def compute_file_hash(file_path: str, chunk_size: int = 8192) -> "Result[str, StorageError]":
    """Compute SHA256 hash of file content.

    Args:
        file_path: Path to the file to hash.
        chunk_size: Size of chunks to read at a time (default 8192 bytes).

    Returns:
        Result containing hexadecimal SHA256 digest, or StorageError if file cannot be read.
    """
    try:
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return Result.ok(hasher.hexdigest())
    except (OSError, IOError) as exc:
        err = StorageError(f"Cannot hash file: {file_path}", cause=exc)
        emit_error(err, component="hashing", operation="compute_file_hash", extra={"path": file_path})
        return Result.err(err)


def compute_directory_hash(dir_path: str) -> "Result[str, StorageError]":
    """Compute hash of directory structure (file names + mtimes).

    Args:
        dir_path: Path to the directory to hash.

    Returns:
        Result containing MD5 hash of directory structure, or StorageError on failure.
    """
    try:
        files = []
        for entry in Path(dir_path).iterdir():
            if entry.is_file():
                stat = entry.stat()
                files.append(f"{entry.name}:{stat.st_mtime}:{stat.st_size}")

        files.sort()
        hash_input = "|".join(files)
        return Result.ok(hashlib.md5(hash_input.encode()).hexdigest())
    except (OSError, IOError) as exc:
        err = StorageError(f"Cannot hash directory: {dir_path}", cause=exc)
        emit_error(err, component="hashing", operation="compute_directory_hash", extra={"path": dir_path})
        return Result.err(err)


def generate_hash(text: str) -> str:
    """Generate a stable SHA-256 hash for the given text.

    This function sanitizes the text before hashing to ensure consistency.
    For text that is already sanitized, use generate_hash_presanitized() instead.

    Args:
        text: Input text to hash.

    Returns:
        Hexadecimal SHA-256 digest of the sanitized text.
    """
    from .text import sanitize_text

    sanitized = sanitize_text(text)
    return hashlib.sha256(sanitized.encode("utf-8")).hexdigest()


def generate_hash_presanitized(text: str) -> str:
    """Generate a stable SHA-256 hash for already-sanitized text.

    This version skips the sanitize_text() call, assuming the input
    has already been sanitized. Use this to avoid redundant sanitization.

    Args:
        text: Pre-sanitized input text.

    Returns:
        Hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "compute_file_hash",
    "compute_directory_hash",
    "generate_hash",
    "generate_hash_presanitized",
]
