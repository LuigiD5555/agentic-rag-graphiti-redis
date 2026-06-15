"""Path discovery and filtering utilities.

This module provides utilities for loading exclusion rules from configuration files,
parsing path patterns, and classifying paths for file discovery operations.
"""

import json
import os
import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable

from src.core import Result, emit_error
from src.core.errors import StorageError


DEFAULT_EXCLUDE_FILES: tuple[str, ...] = (".ingestignore",)


def parse_list_env(raw_value: str | None) -> list[str]:
    """Parse list from environment variable.

    Supports multiple formats:
    - JSON array: ["item1", "item2"]
    - JSON object: {"directories": [...], "patterns": [...]}
    - Comma/newline separated: "item1,item2" or "item1\\nitem2"

    Args:
        raw_value: Raw environment variable value.

    Returns:
        List of parsed strings.
    """
    if not raw_value:
        return []

    value = raw_value.strip()
    if not value:
        return []

    if value.startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = []
        else:
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            if isinstance(parsed, dict):
                collected: list[str] = []
                for key in ("directories", "patterns", "paths"):
                    items = parsed.get(key, [])
                    if isinstance(items, list):
                        collected.extend(str(item).strip() for item in items if str(item).strip())
                return collected
            return []

    tokens = [token.strip() for token in re.split(r"[,\n]", value) if token.strip()]
    return tokens


def value_as_list(value: tuple[str, ...] | list[str] | str | None) -> list[str]:
    """Convert various types to list of strings.

    Args:
        value: Value to convert (tuple, list, string, or None).

    Returns:
        List of strings.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return parse_list_env(value)
    return []


def load_excludes_from_files(exclude_file: str | None, *, cwd: str | None = None) -> list[str]:
    """Load exclusion rules from .ingestignore or custom file.

    Args:
        exclude_file: Optional path to a custom exclusion file.
        cwd: Working directory for resolving relative paths.

    Returns:
        List of exclusion patterns.
    """
    entries: list[str] = []

    candidates: list[str] = []
    if exclude_file:
        candidates.append(exclude_file)
    candidates.extend(DEFAULT_EXCLUDE_FILES)

    seen: set[Path] = set()
    base_dir = Path(cwd or os.getcwd())
    for candidate in candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate).expanduser()
        if not candidate_path.is_absolute():
            candidate_path = base_dir / candidate_path
        try_path = candidate_path.resolve()
        if try_path in seen or not try_path.is_file():
            continue
        seen.add(try_path)
        entries.extend(read_exclude_file(try_path).unwrap_or([]))

    return entries


def read_exclude_file(path: Path) -> "Result[list[str], StorageError]":
    """Read and parse exclusion file (JSON or text).

    Args:
        path: Path to the exclusion file.

    Returns:
        Result containing list of exclusion patterns, or StorageError on read failure.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        err = StorageError(f"Cannot read exclude file: {path}", cause=exc)
        emit_error(err, component="path_discovery", operation="read_exclude_file", extra={"path": str(path)})
        return Result.err(err)

    if path.suffix.lower() == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return Result.ok([str(item).strip() for item in parsed if str(item).strip()])
        if isinstance(parsed, dict):
            collected: list[str] = []
            for key in ("directories", "patterns", "paths"):
                items = parsed.get(key, [])
                if isinstance(items, list):
                    collected.extend(str(item).strip() for item in items if str(item).strip())
            return Result.ok(collected)

    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return Result.ok(lines)


def classify_exclude_entries(entries: Iterable[object]) -> tuple[set[str], set[str]]:
    """Classify exclusion entries as directory names or glob patterns.

    Args:
        entries: Iterable of exclusion entries.

    Returns:
        Tuple of (directory_names, glob_patterns).
    """
    dirnames: set[str] = set()
    globs: set[str] = set()

    for entry in entries:
        candidate = str(entry).strip()
        if not candidate:
            continue
        normalized = candidate.replace("\\", "/").strip()
        normalized = normalized.rstrip("/")
        if not normalized:
            continue
        if is_glob_like(normalized) or "/" in normalized:
            globs.add(normalized)
        else:
            # Treat plain tokens as both:
            # - directory names to prune fast during os.walk
            # - basename patterns so users can ignore files like "secrets.txt"
            dirnames.add(normalized)
            globs.add(normalized)

    return dirnames, globs


def is_glob_like(entry: str) -> bool:
    """Check if entry contains glob characters.

    Args:
        entry: Entry to check.

    Returns:
        True if entry contains glob characters (*, ?, [, ]).
    """
    return any(char in entry for char in "*?[]")




def should_preserve_duplicates(
    path: str,
    patterns: Iterable[object],
    *,
    cwd: str | None = None,
) -> bool:
    """Return True if a file path matches any "include duplicates" pattern."""
    base_dir = Path(cwd or os.getcwd()).resolve()
    path_norm = str(Path(path).expanduser().resolve()).replace("\\", "/")
    basename = Path(path_norm).name

    try:
        rel_norm = str(Path(path_norm).resolve().relative_to(base_dir)).replace("\\", "/")
    except Exception:
        rel_norm = ""

    for entry in patterns:
        raw = str(entry).strip()
        if not raw or raw.startswith("#"):
            continue

        if raw.startswith("re:"):
            try:
                if re.search(raw[3:], path_norm) or (rel_norm and re.search(raw[3:], rel_norm)):
                    return True
            except re.error:
                continue
            continue

        normalized = raw.replace("\\", "/").strip()
        if normalized.endswith("/"):
            prefix = normalized.rstrip("/")
            if not prefix:
                continue
            if prefix.startswith("/"):
                if path_norm.startswith(prefix.rstrip("/")):
                    return True
            else:
                if (rel_norm and (rel_norm == prefix or rel_norm.startswith(prefix + "/"))) or (
                    f"/{prefix}/" in path_norm
                ):
                    return True
            continue

        normalized = normalized.rstrip("/")
        if not normalized:
            continue

        if not is_glob_like(normalized) and "/" not in normalized:
            if basename == normalized:
                return True
            continue

        if fnmatch(path_norm, normalized) or (rel_norm and fnmatch(rel_norm, normalized)) or fnmatch(basename, normalized):
            return True

    return False


__all__ = [
    "DEFAULT_EXCLUDE_FILES",
    "classify_exclude_entries",
    "is_glob_like",
    "load_excludes_from_files",
    "parse_list_env",
    "read_exclude_file",
    "should_preserve_duplicates",
    "value_as_list",
]
