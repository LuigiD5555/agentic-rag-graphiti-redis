"""SQLite-backed operations for ingestion cache (legacy Redis-compatible API)."""

import json
import time
from dataclasses import asdict
from typing import Optional, Set, Dict, Any

from src.workflows.query.audit import get_logger
from src.backends.storage.sqlite.manager import get_sqlite_manager
from .models import FileMetadata, DirectoryMetadata

log = get_logger(__name__)


class RedisOperations:
    """Base class for cache operations (SQLite implementation)."""

    DEFAULT_TTL = 30 * 24 * 60 * 60

    def __init__(self, ttl: int = DEFAULT_TTL):
        self.ttl = ttl
        self.sqlite_manager = get_sqlite_manager()
        self.control_plane = self.sqlite_manager.control_plane

    def _now(self) -> int:
        return int(time.time())

    def _purge_expired(self) -> None:
        now_ts = self._now()
        with self.control_plane.get_connection() as conn:
            conn.execute(
                "DELETE FROM ingestion_file_cache WHERE expires_at <= ?",
                (now_ts,),
            )
            conn.execute(
                "DELETE FROM ingestion_dir_cache WHERE expires_at <= ?",
                (now_ts,),
            )
            conn.execute(
                "DELETE FROM cache_kv WHERE expires_at <= ?",
                (now_ts,),
            )
            conn.execute(
                "DELETE FROM embedding_cache WHERE expires_at <= ?",
                (now_ts,),
            )

    def get_file_metadata(self, file_path: str) -> Optional[FileMetadata]:
        self._purge_expired()
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT file_path, content_hash, mtime, size_bytes, last_processed,
                       chunk_count, embedding_count, status, error_message,
                       ingestion_run_id, scan_run_id, chunk_ids
                FROM ingestion_file_cache
                WHERE file_path = ?
                """,
                (file_path,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return FileMetadata(
                file_path=row[0],
                content_hash=row[1],
                mtime=float(row[2]),
                size=int(row[3]),
                last_processed=float(row[4]),
                chunk_count=int(row[5]),
                embedding_count=int(row[6]),
                status=row[7],
                error_message=row[8],
                ingestion_run_id=row[9],
                scan_run_id=row[10],
                chunk_ids=row[11],
            )

    def set_file_metadata(self, metadata: FileMetadata) -> bool:
        expires_at = self._now() + self.ttl
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_file_cache
                (file_path, content_hash, mtime, size_bytes, last_processed,
                 chunk_count, embedding_count, status, error_message,
                 ingestion_run_id, scan_run_id, chunk_ids, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    mtime = excluded.mtime,
                    size_bytes = excluded.size_bytes,
                    last_processed = excluded.last_processed,
                    chunk_count = excluded.chunk_count,
                    embedding_count = excluded.embedding_count,
                    status = excluded.status,
                    error_message = excluded.error_message,
                    ingestion_run_id = excluded.ingestion_run_id,
                    scan_run_id = excluded.scan_run_id,
                    chunk_ids = excluded.chunk_ids,
                    expires_at = excluded.expires_at
                """,
                (
                    metadata.file_path,
                    metadata.content_hash,
                    float(metadata.mtime),
                    int(metadata.size),
                    float(metadata.last_processed),
                    int(metadata.chunk_count),
                    int(metadata.embedding_count),
                    metadata.status,
                    metadata.error_message,
                    metadata.ingestion_run_id,
                    metadata.scan_run_id,
                    metadata.chunk_ids,
                    expires_at,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO ingestion_hash_index (content_hash, file_path)
                VALUES (?, ?)
                """,
                (metadata.content_hash, metadata.file_path),
            )
        return True

    def get_directory_metadata(self, dir_path: str) -> Optional[DirectoryMetadata]:
        self._purge_expired()
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT dir_path, structure_hash, file_count, last_scanned, total_size
                FROM ingestion_dir_cache
                WHERE dir_path = ?
                """,
                (dir_path,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return DirectoryMetadata(
                dir_path=row[0],
                structure_hash=row[1],
                file_count=int(row[2]),
                last_scanned=float(row[3]),
                total_size=int(row[4]),
            )

    def set_directory_metadata(self, metadata: DirectoryMetadata) -> bool:
        expires_at = self._now() + self.ttl
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_dir_cache
                (dir_path, structure_hash, file_count, last_scanned, total_size, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(dir_path) DO UPDATE SET
                    structure_hash = excluded.structure_hash,
                    file_count = excluded.file_count,
                    last_scanned = excluded.last_scanned,
                    total_size = excluded.total_size,
                    expires_at = excluded.expires_at
                """,
                (
                    metadata.dir_path,
                    metadata.structure_hash,
                    int(metadata.file_count),
                    float(metadata.last_scanned),
                    int(metadata.total_size),
                    expires_at,
                ),
            )
        return True

    def find_files_by_hash(self, content_hash: str) -> Set[str]:
        self._purge_expired()
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT file_path FROM ingestion_hash_index WHERE content_hash = ?",
                (content_hash,),
            )
            return {row[0] for row in cursor.fetchall()}

    def invalidate_file(self, file_path: str) -> bool:
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT content_hash FROM ingestion_file_cache WHERE file_path = ?",
                (file_path,),
            )
            row = cursor.fetchone()
            content_hash = row[0] if row else None
            conn.execute(
                "DELETE FROM ingestion_file_cache WHERE file_path = ?",
                (file_path,),
            )
            if content_hash:
                conn.execute(
                    "DELETE FROM ingestion_hash_index WHERE content_hash = ? AND file_path = ?",
                    (content_hash, file_path),
                )
        return True

    def invalidate_directory(self, dir_path: str) -> bool:
        with self.control_plane.get_connection() as conn:
            conn.execute(
                "DELETE FROM ingestion_dir_cache WHERE dir_path = ?",
                (dir_path,),
            )
        return True

    def clear_all(self) -> bool:
        with self.control_plane.get_connection() as conn:
            conn.execute("DELETE FROM ingestion_file_cache")
            conn.execute("DELETE FROM ingestion_dir_cache")
            conn.execute("DELETE FROM ingestion_hash_index")
        log.info("Cleared all ingestion cache entries from SQLite")
        return True

    def get_stats(self) -> Dict[str, Any]:
        self._purge_expired()
        with self.control_plane.get_connection() as conn:
            file_count = conn.execute(
                "SELECT COUNT(*) FROM ingestion_file_cache"
            ).fetchone()[0]
            dir_count = conn.execute(
                "SELECT COUNT(*) FROM ingestion_dir_cache"
            ).fetchone()[0]

        return {
            "enabled": True,
            "backend": "sqlite",
            "cached_files": int(file_count),
            "cached_directories": int(dir_count),
        }

    def update_stats(self, **kwargs) -> None:
        payload = json.dumps(kwargs or {})
        expires_at = self._now() + self.ttl
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO cache_kv (cache_key, value_json, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    expires_at = excluded.expires_at
                """,
                ("ingestion:stats", payload, expires_at),
            )


__all__ = ["RedisOperations"]
