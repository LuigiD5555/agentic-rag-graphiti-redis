"""Chunk-level tracking for ingestion, backed by SQLite control plane."""

import hashlib
import json
import time
from typing import Optional, Dict, List

from src.backends.storage.sqlite.manager import get_sqlite_manager
from src.backends.storage.sqlite import ChunkMetadata, ChunkStatus
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class ChunkRegistry:
    """Manages chunk-level tracking using SQLite."""

    DEFAULT_TTL = 30 * 24 * 60 * 60

    def __init__(self, ttl: int = DEFAULT_TTL):
        self.ttl = ttl
        self.sqlite_manager = get_sqlite_manager()
        self.control_plane = self.sqlite_manager.control_plane
        self.store = self.sqlite_manager.get_chunk_registry_store()

        log.info("ChunkRegistry initialized (SQLite, TTL=%d seconds)", ttl)

    def generate_chunk_id(self, file_id: str, chunk_index: int, content_hash: str) -> str:
        data = f"{file_id}:{chunk_index}:{content_hash}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    def compute_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def initialize_file_chunking(
        self,
        file_id: str,
        file_path: str,
        total_chunks: int,
        run_id: str,
        chunking_params: Optional[Dict] = None,
    ) -> None:
        now_ts = int(time.time())
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO chunk_files
                (file_id, file_path, total_chunks, run_id, chunking_params_json, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    file_path,
                    total_chunks,
                    run_id,
                    json.dumps(chunking_params or {}),
                    now_ts,
                    "pending",
                ),
            )

    def register_chunk(
        self,
        chunk_id: str,
        file_id: str,
        file_path: str,
        chunk_index: int,
        content_hash: str,
        status: ChunkStatus = ChunkStatus.NEW,
    ) -> None:
        now_ts = int(time.time())
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO chunks
                (chunk_id, file_path, chunk_index, chunk_hash, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    file_path,
                    chunk_index,
                    content_hash,
                    status.value,
                    now_ts,
                ),
            )

    def update_chunk_status(
        self,
        chunk_id: str,
        status: ChunkStatus,
        vector_id: Optional[str] = None,
        embedding_hash: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        now_ts = int(time.time())
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                UPDATE chunks
                SET status = ?, vector_id = COALESCE(?, vector_id),
                    updated_at = ?, last_error = ?
                WHERE chunk_id = ?
                """,
                (status.value, vector_id, now_ts, error, chunk_id),
            )

    def increment_retry_count(self, chunk_id: str) -> int:
        now_ts = int(time.time())
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                UPDATE chunks
                SET retry_count = retry_count + 1, updated_at = ?
                WHERE chunk_id = ?
                """,
                (now_ts, chunk_id),
            )
            cursor = conn.execute(
                "SELECT retry_count FROM chunks WHERE chunk_id = ?",
                (chunk_id,),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def get_chunk_metadata(self, chunk_id: str) -> Optional[ChunkMetadata]:
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT chunk_id, file_path, chunk_index, chunk_hash, status,
                       vector_id, retry_count, updated_at, last_error
                FROM chunks WHERE chunk_id = ?
                """,
                (chunk_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return ChunkMetadata(
            chunk_id=row[0],
            file_path=row[1],
            chunk_index=int(row[2]),
            chunk_hash=row[3],
            status=ChunkStatus(row[4]),
            vector_id=row[5],
            retry_count=int(row[6] or 0),
            updated_at=int(row[7]),
            last_error=row[8],
        )

    def _resolve_file_paths(self, file_id: str) -> List[str]:
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT file_path FROM files WHERE file_path = ?",
                (file_id,),
            )
            direct = [row[0] for row in cursor.fetchall()]
            if direct:
                return direct

            cursor = conn.execute(
                "SELECT file_path FROM files WHERE content_hash = ?",
                (file_id,),
            )
            return [row[0] for row in cursor.fetchall()]

    def get_file_chunks(self, file_id: str) -> Dict[str, ChunkStatus]:
        file_paths = self._resolve_file_paths(file_id)
        if not file_paths:
            return {}

        chunks: Dict[str, ChunkStatus] = {}
        with self.control_plane.get_connection() as conn:
            for file_path in file_paths:
                cursor = conn.execute(
                    """
                    SELECT chunk_id, status
                    FROM chunks
                    WHERE file_path = ?
                    """,
                    (file_path,),
                )
                for row in cursor.fetchall():
                    chunks[row[0]] = ChunkStatus(row[1])
        return chunks

    def get_pending_chunks(self, file_id: str) -> List[str]:
        chunks = self.get_file_chunks(file_id)
        return [chunk_id for chunk_id, status in chunks.items() if status == ChunkStatus.NEW]

    def get_failed_chunks(self, file_id: str) -> List[str]:
        chunks = self.get_file_chunks(file_id)
        return [chunk_id for chunk_id, status in chunks.items() if status == ChunkStatus.FAILED]

    def is_file_complete(self, file_id: str) -> bool:
        chunks = self.get_file_chunks(file_id)
        if not chunks:
            return False
        return all(status == ChunkStatus.UPSERTED for status in chunks.values())

    def get_file_progress(self, file_id: str) -> Dict[str, int | float]:
        chunks = self.get_file_chunks(file_id)
        if not chunks:
            return {
                "total": 0,
                "pending": 0,
                "processing": 0,
                "completed": 0,
                "failed": 0,
                "progress_pct": 0.0,
            }

        status_counts = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
        }

        for status in chunks.values():
            if status == ChunkStatus.NEW:
                status_counts["pending"] += 1
            elif status == ChunkStatus.EMBEDDED:
                status_counts["processing"] += 1
            elif status == ChunkStatus.UPSERTED:
                status_counts["completed"] += 1
            elif status == ChunkStatus.FAILED:
                status_counts["failed"] += 1

        total = len(chunks)
        completed = status_counts["completed"]
        progress_pct = (completed / total * 100) if total > 0 else 0.0

        return {
            "total": total,
            "pending": status_counts["pending"],
            "processing": status_counts["processing"],
            "completed": completed,
            "failed": status_counts["failed"],
            "progress_pct": progress_pct,
        }

    def lookup_chunk_by_vector_id(self, vector_id: str) -> Optional[str]:
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT chunk_id FROM chunks WHERE vector_id = ?",
                (vector_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def get_stats(self) -> Dict[str, int]:
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT status, COUNT(*) FROM chunks
                GROUP BY status
                """
            )
            counts = {row[0]: int(row[1]) for row in cursor.fetchall()}

        return {
            "total_chunks": sum(counts.values()),
            "status_pending": counts.get(ChunkStatus.NEW.value, 0),
            "status_processing": counts.get(ChunkStatus.EMBEDDED.value, 0),
            "status_completed": counts.get(ChunkStatus.UPSERTED.value, 0),
            "status_failed": counts.get(ChunkStatus.FAILED.value, 0),
        }

    def delete_file_chunks(self, file_id: str) -> None:
        file_paths = self._resolve_file_paths(file_id)
        if not file_paths:
            return

        with self.control_plane.get_connection() as conn:
            for file_path in file_paths:
                conn.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
                conn.execute("DELETE FROM chunk_files WHERE file_path = ?", (file_path,))

        log.info("Deleted chunk data for file: %s", file_id)

    def clear_all(self) -> None:
        with self.control_plane.get_connection() as conn:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM chunk_files")
        log.warning("Cleared chunk registry data")


__all__ = ["ChunkRegistry", "ChunkMetadata", "ChunkStatus"]
