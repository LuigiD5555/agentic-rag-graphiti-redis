"""Helpers to load and classify file discovery exclusion rules for ingestion."""
import json
import os
import re
from pathlib import Path
from typing import Iterable


DEFAULT_EXCLUDE_FILES: tuple[str, ...] = (".ingestignore",)


def parse_list_env(raw_value: str | None) -> list[str]:
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
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return parse_list_env(value)
    return []


def load_excludes_from_files(exclude_file: str | None, *, cwd: str | None = None) -> list[str]:
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
        entries.extend(read_exclude_file(try_path))

    return entries


def read_exclude_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    if path.suffix.lower() == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        if isinstance(parsed, dict):
            collected: list[str] = []
            for key in ("directories", "patterns", "paths"):
                items = parsed.get(key, [])
                if isinstance(items, list):
                    collected.extend(str(item).strip() for item in items if str(item).strip())
            return collected

    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


def classify_exclude_entries(entries: Iterable[object]) -> tuple[set[str], set[str]]:
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
    return any(char in entry for char in "*?[]")


__all__ = [
    "DEFAULT_EXCLUDE_FILES",
    "classify_exclude_entries",
    "is_glob_like",
    "load_excludes_from_files",
    "parse_list_env",
    "read_exclude_file",
    "value_as_list",
]
