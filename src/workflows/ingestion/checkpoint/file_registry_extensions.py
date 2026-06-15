"""Extensions to file metadata for checkpoint support (SQLite-backed)."""

import json
import time
from typing import Optional, List, Set

from src.backends.storage.sqlite.manager import get_sqlite_manager
from src.backends.storage.sqlite import FileMetadata, FileStatus
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class FileRegistryExtensions:
    """Extended operations for file tracking with run_id support."""

    def __init__(self):
        self.sqlite_manager = get_sqlite_manager()
        self.control_plane = self.sqlite_manager.control_plane

    def mark_file_seen_in_run(self, file_path: str, run_id: str) -> None:
        now_ts = int(time.time())
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ingest_file_runs
                (run_id, file_path, seen_at)
                VALUES (?, ?, ?)
                """,
                (run_id, file_path, now_ts),
            )

    def get_files_in_run(self, run_id: str) -> Set[str]:
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT file_path FROM ingest_file_runs WHERE run_id = ?",
                (run_id,),
            )
            return {row[0] for row in cursor.fetchall()}

    def get_file_run_history(self, file_path: str, limit: int = 10) -> List[tuple[str, float]]:
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT run_id, seen_at
                FROM ingest_file_runs
                WHERE file_path = ?
                ORDER BY seen_at DESC
                LIMIT ?
                """,
                (file_path, limit),
            )
            return [(row[0], float(row[1])) for row in cursor.fetchall()]

    def update_file_with_run_info(
        self,
        file_path: str,
        scan_run_id: Optional[str] = None,
        ingestion_run_id: Optional[str] = None,
        chunk_ids: Optional[List[str]] = None,
    ) -> bool:
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM files WHERE file_path = ?",
                (file_path,),
            )
            if not cursor.fetchone():
                log.warning("Cannot update file %s: metadata not found", file_path)
                return False

            updates = []
            params = []

            if scan_run_id:
                updates.append("scan_run_id = ?")
                params.append(scan_run_id)

            if ingestion_run_id:
                updates.append("ingestion_run_id = ?")
                params.append(ingestion_run_id)

            if chunk_ids is not None:
                updates.append("chunk_ids_json = ?")
                params.append(json.dumps(chunk_ids))

            if not updates:
                return True

            updates.append("updated_at = ?")
            params.append(int(time.time()))
            params.append(file_path)

            conn.execute(
                f"""
                UPDATE files
                SET {', '.join(updates)}
                WHERE file_path = ?
                """,
                params,
            )
        return True

    def get_file_chunk_ids(self, file_path: str) -> List[str]:
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT chunk_ids_json FROM files WHERE file_path = ?",
                (file_path,),
            )
            row = cursor.fetchone()
            if not row or not row[0]:
                return []
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return [c for c in str(row[0]).split(",") if c]

    def find_deleted_files(self, previous_run_id: str, current_run_id: str) -> Set[str]:
        previous_files = self.get_files_in_run(previous_run_id)
        current_files = self.get_files_in_run(current_run_id)
        deleted = previous_files - current_files

        if deleted:
            log.info(
                "Detected %d deleted file(s) (not in %s but in %s)",
                len(deleted),
                current_run_id,
                previous_run_id,
            )

        return deleted

    def mark_files_for_deletion(self, file_paths: Set[str]) -> int:
        if not file_paths:
            return 0

        now_ts = int(time.time())
        with self.control_plane.get_connection() as conn:
            placeholders = ",".join("?" for _ in file_paths)
            params = [FileStatus.DELETED.value, now_ts, *file_paths]
            conn.execute(
                f"""
                UPDATE files
                SET status = ?, updated_at = ?
                WHERE file_path IN ({placeholders})
                """,
                params,
            )
        log.info("Marked %d file(s) as deleted in cache", len(file_paths))
        return len(file_paths)

    def get_files_by_scan_run(self, scan_run_id: str) -> List[str]:
        return list(self.get_files_in_run(scan_run_id))

    def _row_to_metadata(self, row) -> FileMetadata:
        return FileMetadata(
            file_path=row[0],
            mtime_ns=int(row[1]),
            size_bytes=int(row[2]),
            content_hash=row[3],
            fingerprint_hash=row[4],
            status=FileStatus(row[5]),
            run_id_last=row[6],
            updated_at=int(row[7]),
            last_error=row[8],
            scan_run_id=row[9],
            ingestion_run_id=row[10],
            chunk_ids_json=row[11],
        )

    def get_files_by_ingestion_run(self, ingestion_run_id: str) -> List[FileMetadata]:
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT file_path, mtime_ns, size_bytes, content_hash,
                       fingerprint_hash, status, run_id_last, updated_at,
                       last_error, scan_run_id, ingestion_run_id, chunk_ids_json
                FROM files
                WHERE ingestion_run_id = ?
                """,
                (ingestion_run_id,),
            )
            return [self._row_to_metadata(row) for row in cursor.fetchall()]


__all__ = ["FileRegistryExtensions"]
