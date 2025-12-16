"""Data models for cache manager."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class FileMetadata:
    """Metadata for a cached file."""
    file_path: str
    content_hash: str  # SHA256 hash of file content
    mtime: float  # Last modification time
    size: int  # File size in bytes
    last_processed: float  # Timestamp when file was last processed
    chunk_count: int  # Number of chunks generated
    embedding_count: int  # Number of embeddings created
    status: str  # 'processed', 'failed', 'skipped'
    error_message: Optional[str] = None


@dataclass
class DirectoryMetadata:
    """Metadata for a cached directory."""
    dir_path: str
    structure_hash: str  # Hash of directory structure (file names + mtimes)
    file_count: int
    last_scanned: float
    total_size: int  # Total size of all files in bytes


__all__ = ["FileMetadata", "DirectoryMetadata"]
