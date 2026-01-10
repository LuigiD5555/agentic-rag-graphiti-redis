"""Chunk-level tracking for granular ingestion control.

This module implements the ChunkRegistry which provides:
- Deterministic chunk_id generation for idempotency
- Per-chunk ingestion status tracking
- Chunk to file relationship tracking
- Efficient chunk-level retry logic
"""

import hashlib
from typing import TYPE_CHECKING, Optional, Dict, List
from dataclasses import dataclass
from enum import Enum

if TYPE_CHECKING:
    import redis

from src.rag.audit import get_logger

log = get_logger(__name__)


class ChunkStatus(str, Enum):
    """Chunk processing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ChunkMetadata:
    """Metadata for a single chunk."""
    chunk_id: str
    file_id: str
    file_path: str
    chunk_index: int
    status: ChunkStatus
    content_hash: str
    embedding_hash: Optional[str] = None
    vector_id: Optional[str] = None
    created_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    retry_count: int = 0


class ChunkRegistry:
    """Manages chunk-level tracking for ingestion.

    Redis Key Schema:
        chunk:file:{file_id}:meta           HASH - File-level chunking metadata
        chunk:file:{file_id}:chunks         HASH - {chunk_id: status}
        chunk:{chunk_id}:meta               HASH - Detailed chunk metadata
        chunk:index:vector_id               HASH - {vector_id: chunk_id} (reverse lookup)
        chunk:stats                         HASH - Global chunk statistics

    Chunk ID Generation:
        chunk_id = sha256(file_id + chunk_index + content_hash)
        This ensures:
        - Deterministic: Same content → same chunk_id
        - Idempotent: Can safely retry without duplicates
        - Content-aware: Different content → different chunk_id
    """

    # Redis key patterns
    FILE_META_PATTERN = "chunk:file:{file_id}:meta"
    FILE_CHUNKS_PATTERN = "chunk:file:{file_id}:chunks"
    CHUNK_META_PATTERN = "chunk:{chunk_id}:meta"
    VECTOR_INDEX_KEY = "chunk:index:vector_id"
    STATS_KEY = "chunk:stats"

    # Configuration
    DEFAULT_TTL = 30 * 24 * 60 * 60  # 30 days

    def __init__(self, redis_client: "redis.Redis", ttl: int = DEFAULT_TTL):
        """Initialize chunk registry.

        Args:
            redis_client: Redis client instance
            ttl: Time-to-live for chunk data in seconds
        """
        self.redis = redis_client
        self.ttl = ttl
        log.info("ChunkRegistry initialized (TTL=%d seconds)", ttl)

    def generate_chunk_id(
        self,
        file_id: str,
        chunk_index: int,
        content_hash: str
    ) -> str:
        """Generate deterministic chunk ID.

        Args:
            file_id: File identifier (typically content hash)
            chunk_index: Chunk position in file (0-based)
            content_hash: Hash of chunk content

        Returns:
            Deterministic chunk_id
        """
        # Combine file_id, index, and content hash for uniqueness
        data = f"{file_id}:{chunk_index}:{content_hash}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    def compute_content_hash(self, content: str) -> str:
        """Compute hash of chunk content.

        Args:
            content: Chunk text content

        Returns:
            SHA256 hash of content
        """
        return hashlib.sha256(content.encode()).hexdigest()

    def initialize_file_chunking(
        self,
        file_id: str,
        file_path: str,
        total_chunks: int,
        run_id: str,
        chunking_params: Optional[Dict] = None
    ) -> None:
        """Initialize chunking metadata for a file.

        Args:
            file_id: File identifier
            file_path: File path
            total_chunks: Number of chunks created
            run_id: Ingestion run identifier
            chunking_params: Optional chunking parameters (chunk_size, overlap, etc.)
        """
        import json
        import time

        meta_key = self.FILE_META_PATTERN.format(file_id=file_id)

        meta = {
            "file_id": file_id,
            "file_path": file_path,
            "total_chunks": str(total_chunks),
            "run_id": run_id,
            "chunking_params": json.dumps(chunking_params or {}),
            "created_at": str(time.time()),
            "status": "pending"
        }

        self.redis.hset(meta_key, mapping=meta)
        self.redis.expire(meta_key, self.ttl)

        log.debug(
            "Initialized chunking for file %s: %d chunk(s)",
            file_id, total_chunks
        )

    def register_chunk(
        self,
        chunk_id: str,
        file_id: str,
        file_path: str,
        chunk_index: int,
        content_hash: str,
        status: ChunkStatus = ChunkStatus.PENDING
    ) -> None:
        """Register a chunk in the registry.

        Args:
            chunk_id: Chunk identifier
            file_id: Parent file identifier
            file_path: File path
            chunk_index: Chunk position
            content_hash: Hash of chunk content
            status: Initial status
        """
        import time

        # Store chunk metadata
        chunk_key = self.CHUNK_META_PATTERN.format(chunk_id=chunk_id)
        meta = {
            "chunk_id": chunk_id,
            "file_id": file_id,
            "file_path": file_path,
            "chunk_index": str(chunk_index),
            "content_hash": content_hash,
            "status": status.value,
            "created_at": str(time.time()),
            "retry_count": "0"
        }

        self.redis.hset(chunk_key, mapping=meta)
        self.redis.expire(chunk_key, self.ttl)

        # Add to file's chunk list
        chunks_key = self.FILE_CHUNKS_PATTERN.format(file_id=file_id)
        self.redis.hset(chunks_key, chunk_id, status.value)
        self.redis.expire(chunks_key, self.ttl)

        # Update stats
        self.redis.hincrby(self.STATS_KEY, "total_chunks", 1)
        self.redis.hincrby(self.STATS_KEY, f"status_{status.value}", 1)

    def update_chunk_status(
        self,
        chunk_id: str,
        status: ChunkStatus,
        vector_id: Optional[str] = None,
        embedding_hash: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """Update chunk processing status.

        Args:
            chunk_id: Chunk identifier
            status: New status
            vector_id: Optional vector store ID after embedding
            embedding_hash: Optional hash of embedding vector
            error: Optional error message if failed
        """
        import time

        chunk_key = self.CHUNK_META_PATTERN.format(chunk_id=chunk_id)

        # Get current status for stats
        old_status = self.redis.hget(chunk_key, "status")

        updates = {"status": status.value}

        if status == ChunkStatus.COMPLETED:
            updates["completed_at"] = str(time.time())

        if vector_id:
            updates["vector_id"] = vector_id
            # Create reverse index
            self.redis.hset(self.VECTOR_INDEX_KEY, vector_id, chunk_id)

        if embedding_hash:
            updates["embedding_hash"] = embedding_hash

        if error:
            updates["error"] = error

        self.redis.hset(chunk_key, mapping=updates)

        # Update file's chunk list
        file_id = self.redis.hget(chunk_key, "file_id")
        if file_id:
            chunks_key = self.FILE_CHUNKS_PATTERN.format(file_id=file_id)
            self.redis.hset(chunks_key, chunk_id, status.value)

        # Update stats
        if old_status:
            self.redis.hincrby(self.STATS_KEY, f"status_{old_status}", -1)
        self.redis.hincrby(self.STATS_KEY, f"status_{status.value}", 1)

        log.debug("Updated chunk %s status: %s", chunk_id, status.value)

    def increment_retry_count(self, chunk_id: str) -> int:
        """Increment retry counter for a chunk.

        Args:
            chunk_id: Chunk identifier

        Returns:
            New retry count
        """
        chunk_key = self.CHUNK_META_PATTERN.format(chunk_id=chunk_id)
        return self.redis.hincrby(chunk_key, "retry_count", 1)

    def get_chunk_metadata(self, chunk_id: str) -> Optional[ChunkMetadata]:
        """Get chunk metadata.

        Args:
            chunk_id: Chunk identifier

        Returns:
            ChunkMetadata or None if not found
        """
        chunk_key = self.CHUNK_META_PATTERN.format(chunk_id=chunk_id)
        data = self.redis.hgetall(chunk_key)

        if not data:
            return None

        return ChunkMetadata(
            chunk_id=chunk_id,
            file_id=data.get("file_id", ""),
            file_path=data.get("file_path", ""),
            chunk_index=int(data.get("chunk_index", 0)),
            status=ChunkStatus(data.get("status", "pending")),
            content_hash=data.get("content_hash", ""),
            embedding_hash=data.get("embedding_hash"),
            vector_id=data.get("vector_id"),
            created_at=float(data.get("created_at", 0)),
            completed_at=float(data.get("completed_at", 0)) if data.get("completed_at") else None,
            error=data.get("error"),
            retry_count=int(data.get("retry_count", 0))
        )

    def get_file_chunks(self, file_id: str) -> Dict[str, ChunkStatus]:
        """Get all chunks for a file.

        Args:
            file_id: File identifier

        Returns:
            Dictionary of {chunk_id: status}
        """
        chunks_key = self.FILE_CHUNKS_PATTERN.format(file_id=file_id)
        chunks = self.redis.hgetall(chunks_key)

        return {
            chunk_id: ChunkStatus(status)
            for chunk_id, status in chunks.items()
        }

    def get_pending_chunks(self, file_id: str) -> List[str]:
        """Get pending chunks for a file.

        Args:
            file_id: File identifier

        Returns:
            List of pending chunk_ids
        """
        chunks = self.get_file_chunks(file_id)
        return [
            chunk_id
            for chunk_id, status in chunks.items()
            if status == ChunkStatus.PENDING
        ]

    def get_failed_chunks(self, file_id: str) -> List[str]:
        """Get failed chunks for a file.

        Args:
            file_id: File identifier

        Returns:
            List of failed chunk_ids
        """
        chunks = self.get_file_chunks(file_id)
        return [
            chunk_id
            for chunk_id, status in chunks.items()
            if status == ChunkStatus.FAILED
        ]

    def is_file_complete(self, file_id: str) -> bool:
        """Check if all chunks for a file are completed.

        Args:
            file_id: File identifier

        Returns:
            True if all chunks completed
        """
        chunks = self.get_file_chunks(file_id)

        if not chunks:
            return False

        return all(status == ChunkStatus.COMPLETED for status in chunks.values())

    def get_file_progress(self, file_id: str) -> Dict[str, int]:
        """Get ingestion progress for a file.

        Args:
            file_id: File identifier

        Returns:
            Dictionary with progress stats
        """
        chunks = self.get_file_chunks(file_id)

        if not chunks:
            return {
                "total": 0,
                "pending": 0,
                "processing": 0,
                "completed": 0,
                "failed": 0,
                "progress_pct": 0.0
            }

        status_counts = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0
        }

        for status in chunks.values():
            status_counts[status.value] += 1

        total = len(chunks)
        completed = status_counts["completed"]
        progress_pct = (completed / total * 100) if total > 0 else 0.0

        return {
            "total": total,
            "pending": status_counts["pending"],
            "processing": status_counts["processing"],
            "completed": completed,
            "failed": status_counts["failed"],
            "progress_pct": progress_pct
        }

    def lookup_chunk_by_vector_id(self, vector_id: str) -> Optional[str]:
        """Reverse lookup: find chunk_id by vector_id.

        Args:
            vector_id: Vector store identifier

        Returns:
            chunk_id or None if not found
        """
        return self.redis.hget(self.VECTOR_INDEX_KEY, vector_id)

    def get_stats(self) -> Dict[str, int]:
        """Get global chunk statistics.

        Returns:
            Dictionary with chunk stats
        """
        stats = self.redis.hgetall(self.STATS_KEY)

        return {
            "total_chunks": int(stats.get("total_chunks", 0)),
            "status_pending": int(stats.get("status_pending", 0)),
            "status_processing": int(stats.get("status_processing", 0)),
            "status_completed": int(stats.get("status_completed", 0)),
            "status_failed": int(stats.get("status_failed", 0))
        }

    def delete_file_chunks(self, file_id: str) -> None:
        """Delete all chunk data for a file.

        Args:
            file_id: File identifier
        """
        # Get all chunk IDs
        chunks = self.get_file_chunks(file_id)

        # Delete chunk metadata
        for chunk_id in chunks.keys():
            chunk_key = self.CHUNK_META_PATTERN.format(chunk_id=chunk_id)
            self.redis.delete(chunk_key)

        # Delete file metadata
        meta_key = self.FILE_META_PATTERN.format(file_id=file_id)
        chunks_key = self.FILE_CHUNKS_PATTERN.format(file_id=file_id)
        self.redis.delete(meta_key, chunks_key)

        log.info("Deleted chunk data for file: %s", file_id)

    def clear_all(self) -> None:
        """Clear all chunk registry data (use with caution!)."""
        # This is expensive - ideally use key patterns with SCAN
        log.warning("ChunkRegistry.clear_all() not implemented for safety")
        # Would need to scan all chunk:* keys


__all__ = ["ChunkRegistry", "ChunkMetadata", "ChunkStatus"]
