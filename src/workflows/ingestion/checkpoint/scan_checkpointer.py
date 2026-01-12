"""Resumable directory scanning using Redis-backed checkpoints.

This module implements the ScanCheckpointer which enables:
- Resumable directory scanning after interruptions
- Persistent queue of pending directories in Redis
- Tracking of visited directories to avoid re-scanning
- run_id based isolation for multiple concurrent scans
"""

import time
import uuid
from typing import TYPE_CHECKING, Optional, Set, Dict, Any
from dataclasses import dataclass

if TYPE_CHECKING:
    import redis

from src.workflows.query.audit import get_logger

log = get_logger(__name__)


@dataclass
class ScanRun:
    """Metadata for a scan run."""
    run_id: str
    root_paths: list[str]
    options_hash: str
    started_at: float
    status: str  # 'running', 'completed', 'failed', 'interrupted'
    dirs_scanned: int = 0
    files_found: int = 0
    last_updated: Optional[float] = None


class ScanCheckpointer:
    """Manages resumable directory scanning with Redis-backed persistence.

    Redis Key Schema:
        scan:run:{run_id}:pending       LIST - Queue of pending directories
        scan:run:{run_id}:visited       SET - Set of visited directory paths
        scan:run:{run_id}:files         LIST - Discovered file paths (chunked)
        scan:run:{run_id}:meta          HASH - Run metadata (status, stats, etc.)
        scan:runs:active                ZSET - Active runs sorted by start time

    Workflow:
        1. Start new run or resume existing: get run_id
        2. Push root directories to pending queue
        3. Pop directories from queue, scan them
        4. Mark directories as visited
        5. Push subdirectories to pending queue
        6. Repeat until queue is empty
        7. Mark run as completed
    """

    # Redis key patterns
    PENDING_KEY_PATTERN = "scan:run:{run_id}:pending"
    VISITED_KEY_PATTERN = "scan:run:{run_id}:visited"
    FILES_KEY_PATTERN = "scan:run:{run_id}:files"
    META_KEY_PATTERN = "scan:run:{run_id}:meta"
    ACTIVE_RUNS_KEY = "scan:runs:active"

    # Configuration
    DEFAULT_TTL = 7 * 24 * 60 * 60  # 7 days
    FILES_CHUNK_SIZE = 1000  # Write files in chunks to avoid huge lists

    def __init__(self, redis_client: "redis.Redis", ttl: int = DEFAULT_TTL):
        """Initialize checkpointer with Redis client.

        Args:
            redis_client: Redis client instance
            ttl: Time-to-live for checkpoint data in seconds
        """
        self.redis = redis_client
        self.ttl = ttl
        log.info("ScanCheckpointer initialized (TTL=%d seconds)", ttl)

    def start_new_run(
        self,
        root_paths: list[str],
        options_hash: str,
        run_id: Optional[str] = None
    ) -> str:
        """Start a new scan run.

        Args:
            root_paths: List of root directories to scan
            options_hash: Hash of discovery options (for cache validation)
            run_id: Optional explicit run_id (useful for resuming)

        Returns:
            The run_id for this scan
        """
        if not run_id:
            run_id = f"scan_{uuid.uuid4().hex[:12]}_{int(time.time())}"

        now = time.time()

        # Initialize metadata
        meta = {
            "run_id": run_id,
            "root_paths": ",".join(root_paths),
            "options_hash": options_hash,
            "started_at": str(now),
            "status": "running",
            "dirs_scanned": "0",
            "files_found": "0",
            "last_updated": str(now)
        }

        meta_key = self.META_KEY_PATTERN.format(run_id=run_id)
        pending_key = self.PENDING_KEY_PATTERN.format(run_id=run_id)

        # Store metadata
        self.redis.hset(meta_key, mapping=meta)
        self.redis.expire(meta_key, self.ttl)

        # Initialize pending queue with root directories
        if root_paths:
            # Each entry: "dirpath|rel_dirpath"
            entries = [f"{path}|" for path in root_paths]
            self.redis.rpush(pending_key, *entries)
            self.redis.expire(pending_key, self.ttl)

        # Add to active runs
        self.redis.zadd(self.ACTIVE_RUNS_KEY, {run_id: now})
        self.redis.expire(self.ACTIVE_RUNS_KEY, self.ttl)

        log.info(
            "Started scan run %s with %d root path(s): %s",
            run_id, len(root_paths), root_paths
        )

        return run_id

    def resume_run(self, run_id: str) -> Optional[ScanRun]:
        """Resume an interrupted scan run.

        Args:
            run_id: The run to resume

        Returns:
            ScanRun metadata if run exists and can be resumed, None otherwise
        """
        meta_key = self.META_KEY_PATTERN.format(run_id=run_id)
        meta = self.redis.hgetall(meta_key)

        if not meta:
            log.warning("Cannot resume run %s: metadata not found", run_id)
            return None

        status = meta.get("status", "unknown")
        if status == "completed":
            log.info("Run %s already completed", run_id)
            return None

        # Update status to running
        self.redis.hset(meta_key, "status", "running")
        self.redis.hset(meta_key, "last_updated", str(time.time()))

        scan_run = ScanRun(
            run_id=run_id,
            root_paths=meta.get("root_paths", "").split(","),
            options_hash=meta.get("options_hash", ""),
            started_at=float(meta.get("started_at", 0)),
            status="running",
            dirs_scanned=int(meta.get("dirs_scanned", 0)),
            files_found=int(meta.get("files_found", 0)),
            last_updated=float(meta.get("last_updated", 0))
        )

        log.info(
            "Resumed scan run %s (dirs_scanned=%d, files_found=%d)",
            run_id, scan_run.dirs_scanned, scan_run.files_found
        )

        return scan_run

    def pop_pending_directory(self, run_id: str) -> Optional[tuple[str, str]]:
        """Pop next pending directory from queue.

        Args:
            run_id: The scan run

        Returns:
            Tuple of (dirpath, rel_dirpath) or None if queue is empty
        """
        pending_key = self.PENDING_KEY_PATTERN.format(run_id=run_id)
        entry = self.redis.lpop(pending_key)

        if not entry:
            return None

        # Parse "dirpath|rel_dirpath"
        parts = entry.split("|", 1)
        dirpath = parts[0]
        rel_dirpath = parts[1] if len(parts) > 1 else ""

        return dirpath, rel_dirpath

    def push_pending_directories(
        self,
        run_id: str,
        directories: list[tuple[str, str]]
    ) -> None:
        """Add subdirectories to pending queue.

        Args:
            run_id: The scan run
            directories: List of (dirpath, rel_dirpath) tuples
        """
        if not directories:
            return

        pending_key = self.PENDING_KEY_PATTERN.format(run_id=run_id)

        # Format entries as "dirpath|rel_dirpath"
        entries = [f"{dirpath}|{rel_dirpath}" for dirpath, rel_dirpath in directories]

        self.redis.rpush(pending_key, *entries)
        self.redis.expire(pending_key, self.ttl)

    def mark_directory_visited(self, run_id: str, dirpath: str) -> None:
        """Mark a directory as visited.

        Args:
            run_id: The scan run
            dirpath: Directory path to mark as visited
        """
        visited_key = self.VISITED_KEY_PATTERN.format(run_id=run_id)
        self.redis.sadd(visited_key, dirpath)
        self.redis.expire(visited_key, self.ttl)

    def is_directory_visited(self, run_id: str, dirpath: str) -> bool:
        """Check if directory has been visited.

        Args:
            run_id: The scan run
            dirpath: Directory path to check

        Returns:
            True if directory was already visited
        """
        visited_key = self.VISITED_KEY_PATTERN.format(run_id=run_id)
        return bool(self.redis.sismember(visited_key, dirpath))

    def add_discovered_files(self, run_id: str, file_paths: list[str]) -> None:
        """Add discovered files to the run's file list.

        Args:
            run_id: The scan run
            file_paths: List of file paths discovered
        """
        if not file_paths:
            return

        files_key = self.FILES_KEY_PATTERN.format(run_id=run_id)

        # Write in chunks to avoid huge single operations
        for i in range(0, len(file_paths), self.FILES_CHUNK_SIZE):
            chunk = file_paths[i:i + self.FILES_CHUNK_SIZE]
            self.redis.rpush(files_key, *chunk)

        self.redis.expire(files_key, self.ttl)

    def get_discovered_files(self, run_id: str) -> list[str]:
        """Get all discovered files for a run.

        Args:
            run_id: The scan run

        Returns:
            List of file paths
        """
        files_key = self.FILES_KEY_PATTERN.format(run_id=run_id)
        return self.redis.lrange(files_key, 0, -1)

    def update_stats(
        self,
        run_id: str,
        dirs_scanned: Optional[int] = None,
        files_found: Optional[int] = None
    ) -> None:
        """Update scan statistics.

        Args:
            run_id: The scan run
            dirs_scanned: Number of directories scanned (incremental)
            files_found: Number of files found (incremental)
        """
        meta_key = self.META_KEY_PATTERN.format(run_id=run_id)

        updates = {"last_updated": str(time.time())}

        if dirs_scanned is not None:
            # Increment counter
            current = int(self.redis.hget(meta_key, "dirs_scanned") or 0)
            updates["dirs_scanned"] = str(current + dirs_scanned)

        if files_found is not None:
            current = int(self.redis.hget(meta_key, "files_found") or 0)
            updates["files_found"] = str(current + files_found)

        self.redis.hset(meta_key, mapping=updates)

    def complete_run(self, run_id: str, status: str = "completed") -> None:
        """Mark scan run as completed or failed.

        Args:
            run_id: The scan run
            status: Final status ('completed', 'failed', 'interrupted')
        """
        meta_key = self.META_KEY_PATTERN.format(run_id=run_id)

        self.redis.hset(meta_key, mapping={
            "status": status,
            "last_updated": str(time.time()),
            "completed_at": str(time.time())
        })

        # Remove from active runs
        self.redis.zrem(self.ACTIVE_RUNS_KEY, run_id)

        log.info("Scan run %s marked as %s", run_id, status)

    def get_run_metadata(self, run_id: str) -> Optional[ScanRun]:
        """Get metadata for a scan run.

        Args:
            run_id: The scan run

        Returns:
            ScanRun metadata or None if not found
        """
        meta_key = self.META_KEY_PATTERN.format(run_id=run_id)
        meta = self.redis.hgetall(meta_key)

        if not meta:
            return None

        return ScanRun(
            run_id=run_id,
            root_paths=meta.get("root_paths", "").split(","),
            options_hash=meta.get("options_hash", ""),
            started_at=float(meta.get("started_at", 0)),
            status=meta.get("status", "unknown"),
            dirs_scanned=int(meta.get("dirs_scanned", 0)),
            files_found=int(meta.get("files_found", 0)),
            last_updated=float(meta.get("last_updated", 0))
        )

    def get_pending_count(self, run_id: str) -> int:
        """Get number of pending directories.

        Args:
            run_id: The scan run

        Returns:
            Number of directories in pending queue
        """
        pending_key = self.PENDING_KEY_PATTERN.format(run_id=run_id)
        return self.redis.llen(pending_key)

    def list_active_runs(self) -> list[str]:
        """List all active scan runs.

        Returns:
            List of run_ids sorted by start time
        """
        return self.redis.zrange(self.ACTIVE_RUNS_KEY, 0, -1)

    def cleanup_run(self, run_id: str) -> None:
        """Delete all data for a scan run.

        Args:
            run_id: The scan run to clean up
        """
        keys = [
            self.PENDING_KEY_PATTERN.format(run_id=run_id),
            self.VISITED_KEY_PATTERN.format(run_id=run_id),
            self.FILES_KEY_PATTERN.format(run_id=run_id),
            self.META_KEY_PATTERN.format(run_id=run_id)
        ]

        self.redis.delete(*keys)
        self.redis.zrem(self.ACTIVE_RUNS_KEY, run_id)

        log.info("Cleaned up scan run %s", run_id)


__all__ = ["ScanCheckpointer", "ScanRun"]
