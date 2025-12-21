"""File and path operation utilities.

This module provides utilities for file metadata extraction, path sorting,
and path validation used across the ingestion pipeline.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from src.rag.audit import get_logger
from src.utils.hashing import generate_hash_presanitized

log = get_logger(__name__)


def gather_file_metadata(path: Optional[str]) -> Dict[str, Any]:
    """Extract file metadata including path, name, extension, size, and modification time.

    Args:
        path: Path to the file.

    Returns:
        Dictionary containing file metadata.
    """
    resolved = str(path or "").strip()
    if not resolved and hasattr(path, "strip"):
        resolved = str(path).strip()

    info: Dict[str, Any] = {
        "file_path": resolved or None,
        "file_name": os.path.basename(resolved) if resolved else None,
        "file_extension": os.path.splitext(resolved)[1].lower() if resolved else None,
        "parent_directory": os.path.dirname(resolved) if resolved else None,
        "file_size_bytes": None,
        "file_modified_at": None,
        "file_id": generate_hash_presanitized(resolved) if resolved else None,
    }

    if resolved and os.path.isfile(resolved):
        try:
            stats = os.stat(resolved)
            info["file_size_bytes"] = stats.st_size
            info["file_modified_at"] = datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            pass

    return info


def sort_paths_by_size_desc(paths: Iterable[str]) -> List[str]:
    """Order paths from smallest to largest file size (ASCENDING).

    This ordering ensures that small files are processed first, which:
    - Provides faster initial progress feedback to users
    - Reduces CPU spikes from processing multiple large files in parallel
    - Improves overall stability when dealing with mixed file sizes

    Ties on size are broken alphabetically (case-insensitive) to ensure
    deterministic processing. Missing/inaccessible files are treated as size 0.

    Args:
        paths: Iterable of file paths to sort.

    Returns:
        List of paths sorted by size (ascending) then alphabetically.
    """
    sizes: dict[str, int] = {}
    for path in paths:
        try:
            sizes[path] = os.path.getsize(path)
        except OSError:
            sizes[path] = 0

    return sorted(
        paths,
        key=lambda p: (sizes[p], p.lower()),  # Changed from (-sizes[p], ...) to (sizes[p], ...)
    )


def should_skip_path(path: str) -> bool:
    """Check if a path should be skipped during ingestion.

    Skips paths that are:
    - Broken symlinks
    - Temporary Office lock files (starting with ~$)
    - Non-existent paths

    Args:
        path: Path to check.

    Returns:
        True if the path should be skipped, False otherwise.
    """
    if os.path.islink(path) and not os.path.exists(path):
        try:
            target = os.readlink(path)
            log.warning("Skipping broken symlink: %s -> %s", path, target)
        except OSError:
            log.warning("Skipping broken symlink: %s", path)
        return True

    basename = os.path.basename(path)
    if basename.strip().startswith("~$"):
        log.info("Skipping temporary Office lock file: %s", path)
        return True

    if not os.path.exists(path):
        log.error("Path does not exist: %s", path)
        return True

    return False


__all__ = [
    "gather_file_metadata",
    "sort_paths_by_size_desc",
    "should_skip_path",
]
