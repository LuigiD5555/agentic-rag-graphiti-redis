"""SQLite-backed store for temporal file tracking and tenants."""

import json
import time
from typing import Any, Dict, List, Optional

from src.backends.storage.sqlite.manager import get_sqlite_manager


class TemporalStore:
    """Persist temporal file tracking and tenant metadata in SQLite."""

    def __init__(self, sqlite_manager=None) -> None:
        self.sqlite_manager = sqlite_manager or get_sqlite_manager()
        self.control_plane = self.sqlite_manager.control_plane

    def _now(self) -> int:
        return int(time.time())

    def _purge_expired_temporal_files(self, now_ts: int) -> None:
        with self.control_plane.get_connection() as conn:
            conn.execute(
                "DELETE FROM temporal_files WHERE expires_at < ?",
                (now_ts,),
            )

    def _purge_expired_tenants(self, now_ts: int) -> None:
        with self.control_plane.get_connection() as conn:
            conn.execute(
                "DELETE FROM temporal_tenants WHERE expires_at < ?",
                (now_ts,),
            )

    # ----- Tenant tracking -----
    def ensure_tenant(self, tenant_name: str, ttl_seconds: int) -> None:
        now_ts = self._now()
        expires_at = now_ts + ttl_seconds
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO temporal_tenants (tenant_name, created_at, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(tenant_name) DO UPDATE SET
                    expires_at = excluded.expires_at
                """,
                (tenant_name, now_ts, expires_at),
            )

    def get_tenant_created_at(self, tenant_name: str) -> Optional[int]:
        now_ts = self._now()
        with self.control_plane.get_connection() as conn:
            row = conn.execute(
                "SELECT created_at, expires_at FROM temporal_tenants WHERE tenant_name = ?",
                (tenant_name,),
            ).fetchone()
            if not row:
                return None
            created_at, expires_at = row
            if expires_at < now_ts:
                conn.execute(
                    "DELETE FROM temporal_tenants WHERE tenant_name = ?",
                    (tenant_name,),
                )
                return None
            return int(created_at)

    def list_expired_tenants(self) -> List[str]:
        now_ts = self._now()
        with self.control_plane.get_connection() as conn:
            rows = conn.execute(
                "SELECT tenant_name FROM temporal_tenants WHERE expires_at < ?",
                (now_ts,),
            ).fetchall()
        return [row[0] for row in rows]

    def delete_tenant_record(self, tenant_name: str) -> None:
        with self.control_plane.get_connection() as conn:
            conn.execute(
                "DELETE FROM temporal_tenants WHERE tenant_name = ?",
                (tenant_name,),
            )

    # ----- File uploads -----
    def increment_file_upload(
        self,
        file_hash: str,
        thread_id: str,
        filename: str,
    ) -> Dict[str, Any]:
        now_ts = self._now()
        with self.control_plane.get_connection() as conn:
            row = conn.execute(
                """
                SELECT upload_count, first_uploaded, promoted, pareto_promoted
                FROM file_uploads WHERE file_hash = ?
                """,
                (file_hash,),
            ).fetchone()
            if row:
                upload_count, first_uploaded, promoted, pareto_promoted = row
                upload_count = int(upload_count) + 1
                conn.execute(
                    """
                    UPDATE file_uploads
                    SET upload_count = ?, last_uploaded = ?, filename = ?
                    WHERE file_hash = ?
                    """,
                    (upload_count, now_ts, filename, file_hash),
                )
            else:
                upload_count = 1
                first_uploaded = now_ts
                promoted = 0
                pareto_promoted = 0
                conn.execute(
                    """
                    INSERT INTO file_uploads
                    (file_hash, upload_count, first_uploaded, last_uploaded, filename, promoted, pareto_promoted)
                    VALUES (?, ?, ?, ?, ?, 0, 0)
                    """,
                    (file_hash, upload_count, first_uploaded, now_ts, filename),
                )

            conn.execute(
                """
                INSERT OR IGNORE INTO file_upload_threads (file_hash, thread_id)
                VALUES (?, ?)
                """,
                (file_hash, thread_id),
            )

        return {
            "upload_count": upload_count,
            "first_uploaded": first_uploaded,
            "promoted": int(promoted),
            "pareto_promoted": int(pareto_promoted),
        }

    def get_file_upload_info(self, file_hash: str) -> Optional[Dict[str, Any]]:
        with self.control_plane.get_connection() as conn:
            row = conn.execute(
                """
                SELECT upload_count, first_uploaded, last_uploaded, filename, promoted, pareto_promoted
                FROM file_uploads WHERE file_hash = ?
                """,
                (file_hash,),
            ).fetchone()
            if not row:
                return None

            threads = conn.execute(
                "SELECT thread_id FROM file_upload_threads WHERE file_hash = ?",
                (file_hash,),
            ).fetchall()

        return {
            "upload_count": int(row[0]),
            "first_uploaded": float(row[1]),
            "last_uploaded": float(row[2]),
            "filename": row[3],
            "promoted": str(int(row[4])),
            "pareto_promoted": str(int(row[5])),
            "threads": [t[0] for t in threads],
        }

    def mark_promoted(self, file_hash: str, mode: str) -> None:
        with self.control_plane.get_connection() as conn:
            if mode == "pareto":
                conn.execute(
                    "UPDATE file_uploads SET pareto_promoted = 1 WHERE file_hash = ?",
                    (file_hash,),
                )
                conn.execute(
                    "UPDATE temporal_files SET pareto_promoted = 1 WHERE file_hash = ?",
                    (file_hash,),
                )
            else:
                conn.execute(
                    "UPDATE file_uploads SET promoted = 1 WHERE file_hash = ?",
                    (file_hash,),
                )
                conn.execute(
                    "UPDATE temporal_files SET full_promoted = 1 WHERE file_hash = ?",
                    (file_hash,),
                )

    # ----- Temporal files -----
    def upsert_temporal_file(
        self,
        thread_id: str,
        file_id: str,
        file_hash: str,
        filename: str,
        chunk_ids: List[str],
        ttl_seconds: int,
    ) -> None:
        now_ts = self._now()
        expires_at = now_ts + ttl_seconds
        chunk_ids_json = json.dumps(chunk_ids)
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO temporal_files
                (thread_id, file_id, file_hash, filename, uploaded_at, query_count,
                 pareto_promoted, full_promoted, chunk_ids_json, expires_at)
                VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
                """,
                (thread_id, file_id, file_hash, filename, now_ts, chunk_ids_json, expires_at),
            )

    def get_temporal_file_info(self, thread_id: str, file_id: str) -> Optional[Dict[str, Any]]:
        now_ts = self._now()
        self._purge_expired_temporal_files(now_ts)
        with self.control_plane.get_connection() as conn:
            row = conn.execute(
                """
                SELECT file_hash, filename, uploaded_at, query_count, pareto_promoted,
                       full_promoted, chunk_ids_json, expires_at
                FROM temporal_files
                WHERE thread_id = ? AND file_id = ?
                """,
                (thread_id, file_id),
            ).fetchone()
            if not row:
                return None

            chunk_scores_rows = conn.execute(
                """
                SELECT chunk_id, score FROM chunk_scores
                WHERE thread_id = ? AND file_id = ?
                """,
                (thread_id, file_id),
            ).fetchall()

        if row[7] < now_ts:
            self.delete_temporal_file(thread_id, file_id)
            return None

        return {
            "file_hash": row[0],
            "filename": row[1],
            "uploaded_at": float(row[2]),
            "query_count": int(row[3]),
            "pareto_promoted": str(int(row[4])),
            "full_promoted": str(int(row[5])),
            "chunk_ids": json.loads(row[6]) if row[6] else [],
            "chunk_scores": {r[0]: float(r[1]) for r in chunk_scores_rows},
        }

    def list_temporal_files(self, thread_id: str) -> List[str]:
        now_ts = self._now()
        self._purge_expired_temporal_files(now_ts)
        with self.control_plane.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT file_id FROM temporal_files
                WHERE thread_id = ? AND expires_at >= ?
                """,
                (thread_id, now_ts),
            ).fetchall()
        return [row[0] for row in rows]

    def delete_temporal_file(self, thread_id: str, file_id: str) -> None:
        with self.control_plane.get_connection() as conn:
            conn.execute(
                "DELETE FROM temporal_files WHERE thread_id = ? AND file_id = ?",
                (thread_id, file_id),
            )

    def increment_query_count(self, thread_id: str, file_id: str) -> int:
        now_ts = self._now()
        self._purge_expired_temporal_files(now_ts)
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                UPDATE temporal_files
                SET query_count = query_count + 1
                WHERE thread_id = ? AND file_id = ?
                """,
                (thread_id, file_id),
            )
            row = conn.execute(
                """
                SELECT query_count FROM temporal_files
                WHERE thread_id = ? AND file_id = ?
                """,
                (thread_id, file_id),
            ).fetchone()
        return int(row[0]) if row else 0

    def increment_chunk_score(
        self,
        thread_id: str,
        file_id: str,
        chunk_id: str,
        delta: float,
    ) -> float:
        now_ts = self._now()
        self._purge_expired_temporal_files(now_ts)
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO chunk_scores (thread_id, file_id, chunk_id, score)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(thread_id, file_id, chunk_id) DO UPDATE SET
                    score = score + excluded.score
                """,
                (thread_id, file_id, chunk_id, float(delta)),
            )
            row = conn.execute(
                """
                SELECT score FROM chunk_scores
                WHERE thread_id = ? AND file_id = ? AND chunk_id = ?
                """,
                (thread_id, file_id, chunk_id),
            ).fetchone()
        return float(row[0]) if row else float(delta)

    def get_stats(self) -> Dict[str, Any]:
        now_ts = self._now()
        self._purge_expired_temporal_files(now_ts)
        with self.control_plane.get_connection() as conn:
            unique_files = conn.execute(
                "SELECT COUNT(*) FROM file_uploads",
            ).fetchone()[0]
            temporal_files = conn.execute(
                "SELECT COUNT(*) FROM temporal_files WHERE expires_at >= ?",
                (now_ts,),
            ).fetchone()[0]
            promoted = conn.execute(
                "SELECT COUNT(*) FROM file_uploads WHERE promoted = 1",
            ).fetchone()[0]
        return {
            "unique_files_tracked": int(unique_files),
            "temporal_files_active": int(temporal_files),
            "fully_promoted_files": int(promoted),
        }
