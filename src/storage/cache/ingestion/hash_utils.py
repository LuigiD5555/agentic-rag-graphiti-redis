"""Hashing utilities for cache manager."""
import hashlib
from typing import Optional
from pathlib import Path

from src.rag.audit import get_logger

log = get_logger(__name__)


def compute_file_hash(file_path: str, chunk_size: int = 8192) -> Optional[str]:
    """Compute SHA256 hash of file content."""
    try:
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, IOError) as e:
        log.debug("Cannot hash file %s: %s", file_path, e)
        return None


def compute_directory_hash(dir_path: str) -> str:
    """Compute hash of directory structure (file names + mtimes)."""
    try:
        files = []
        for entry in Path(dir_path).iterdir():
            if entry.is_file():
                stat = entry.stat()
                files.append(f"{entry.name}:{stat.st_mtime}:{stat.st_size}")

        files.sort()
        hash_input = "|".join(files)
        return hashlib.md5(hash_input.encode()).hexdigest()
    except (OSError, IOError) as e:
        log.debug("Cannot hash directory %s: %s", dir_path, e)
        return ""


__all__ = ["compute_file_hash", "compute_directory_hash"]
