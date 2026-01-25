"""Resumable directory scanning using SQLite-backed checkpoints."""

from dataclasses import dataclass
import time
from typing import List, Optional, Dict, Any

from src.backends.storage.sqlite.manager import get_sqlite_manager
from src.backends.storage.sqlite import ScanRunStatus
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


@dataclass
class ScanRun:
    """Represents a scan run and its persisted state."""
    run_id: str
    root_paths: List[str]
    options_hash: str
    status: ScanRunStatus
    started_at: int
    updated_at: int
    dirs_visited: int = 0
    files_found: int = 0
    last_error: Optional[str] = None
    pending_dirs: Optional[List[str]] = None
    visited_dirs: Optional[List[str]] = None
    discovered_files: Optional[List[str]] = None


class ScanCheckpointer:
    """SQLite-backed checkpointer for resumable directory scans."""

    def __init__(self, ttl: int = 30 * 24 * 60 * 60):
        self.ttl = ttl
        self.sqlite_manager = get_sqlite_manager()
        self.store = self.sqlite_manager.get_scan_checkpoint_store()

    def start_new_run(self, root_paths: List[str], options_hash: str) -> str:
        now_ts = int(time.time())
        run_id = self.store.create_run(root_paths, options_hash, now_ts)
        for root in root_paths:
            self.store.enqueue_dir(run_id, root, now_ts)
        self.store.set_run_status(run_id, ScanRunStatus.RUNNING, now_ts)
        return run_id

    def resume_run(self, run_id: str) -> Optional[ScanRun]:
        try:
            data = self.store.resume_run(run_id)
        except Exception as exc:
            log.warning("Failed to resume scan run %s: %s", run_id, exc)
            return None

        return ScanRun(
            run_id=data["run_id"],
            root_paths=data.get("root_paths", []),
            options_hash=data.get("options_hash", ""),
            status=data.get("status", ScanRunStatus.NEW),
            started_at=int(data.get("started_at", 0)),
            updated_at=int(data.get("updated_at", 0)),
            dirs_visited=int(data.get("dirs_visited", 0)),
            files_found=int(data.get("files_found", 0)),
            last_error=data.get("last_error"),
            pending_dirs=data.get("pending_dirs", []),
            visited_dirs=data.get("visited_dirs", []),
            discovered_files=data.get("discovered_files", []),
        )

    def complete_run(self, run_id: str, status: str = "completed") -> None:
        now_ts = int(time.time())
        status_value = ScanRunStatus.COMPLETED if status == "completed" else ScanRunStatus.CANCELLED
        if status == "failed":
            status_value = ScanRunStatus.FAILED
        self.store.set_run_status(run_id, status_value, now_ts)

    def list_runs(self) -> List[Dict[str, Any]]:
        with self.sqlite_manager.control_plane.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT run_id, root_paths_json, options_hash, status, started_at, updated_at,
                       dirs_visited, files_found, last_error
                FROM scan_runs
                ORDER BY started_at DESC
                """
            ).fetchall()

        runs = []
        for row in rows:
            runs.append(
                {
                    "run_id": row[0],
                    "root_paths": row[1],
                    "options_hash": row[2],
                    "status": row[3],
                    "created_at": int(row[4]),
                    "updated_at": int(row[5]),
                    "dirs_visited": int(row[6]),
                    "files_found": int(row[7]),
                    "last_error": row[8],
                }
            )
        return runs

    def push_pending_directories(self, run_id: str, dirs: List[str]) -> None:
        now_ts = int(time.time())
        for dir_path in dirs:
            self.store.enqueue_dir(run_id, dir_path, now_ts)

    def pop_pending_directory(self, run_id: str) -> Optional[str]:
        return self.store.dequeue_dir(run_id)

    def is_directory_visited(self, run_id: str, dir_path: str) -> bool:
        with self.sqlite_manager.control_plane.get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM scan_visited WHERE run_id = ? AND dir_path = ?",
                (run_id, dir_path),
            ).fetchone()
        return bool(row)

    def mark_directory_visited(self, run_id: str, dir_path: str) -> None:
        self.store.mark_visited(run_id, dir_path, int(time.time()))

    def add_discovered_files(self, run_id: str, files: List[str]) -> None:
        now_ts = int(time.time())
        for file_path in files:
            self.store.add_found_file(run_id, file_path, now_ts)

    def get_pending_count(self, run_id: str) -> int:
        with self.sqlite_manager.control_plane.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM scan_pending WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def get_visited_directories(self, run_id: str) -> List[str]:
        with self.sqlite_manager.control_plane.get_connection() as conn:
            rows = conn.execute(
                "SELECT dir_path FROM scan_visited WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        return [row[0] for row in rows]

    def get_discovered_files(self, run_id: str) -> List[str]:
        with self.sqlite_manager.control_plane.get_connection() as conn:
            rows = conn.execute(
                "SELECT file_path FROM scan_files WHERE run_id = ? ORDER BY seq",
                (run_id,),
            ).fetchall()
        return [row[0] for row in rows]

    def update_stats(self, run_id: str, dirs_visited_delta: int = 0, files_found_delta: int = 0) -> None:
        if dirs_visited_delta == 0 and files_found_delta == 0:
            return
        now_ts = int(time.time())
        with self.sqlite_manager.control_plane.get_connection() as conn:
            conn.execute(
                """
                UPDATE scan_runs
                SET dirs_visited = dirs_visited + ?,
                    files_found = files_found + ?,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (dirs_visited_delta, files_found_delta, now_ts, run_id),
            )


__all__ = ["ScanCheckpointer", "ScanRun"]
