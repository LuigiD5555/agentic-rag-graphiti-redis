"""Job state repository for idempotence and checkpoint management in SQLite."""

import time
from typing import Optional, Dict, Any
from enum import Enum

from src.backends.storage.sqlite.manager import get_sqlite_manager
from src.workflows.ingestion.jobs.models import IngestionJobMessage, ProcessingDecision
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class JobStatus(Enum):
    """Job status in SQLite."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    FAILED = "FAILED"
    FAILED_FINAL = "FAILED_FINAL"


class JobStateRepository:
    """Repository for job state management in SQLite.
    
    Implements idempotence and checkpoint logic according to specification.
    """
    
    # Default timeout for IN_PROGRESS jobs (30 minutes)
    DEFAULT_TIMEOUT_SECONDS = 30 * 60
    
    # Maximum retry attempts
    MAX_RETRIES = 3
    
    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        """Initialize job state repository.
        
        Args:
            timeout_seconds: Timeout for IN_PROGRESS jobs before they can be retried
        """
        self.timeout_seconds = timeout_seconds
        self.sqlite_manager = get_sqlite_manager()
        self._ensure_tables()
    
    def _ensure_tables(self) -> None:
        """Ensure required tables exist in SQLite."""
        with self.sqlite_manager.control_plane.get_connection() as conn:
            # Create job_state table if not exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_state (
                    file_path TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    error TEXT,
                    metrics TEXT,
                    PRIMARY KEY (file_path, phase, fingerprint)
                )
            """)
            
            # Create runs table if not exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    stats TEXT
                )
            """)
            
            # Create file_metadata table if not exists (for discovery cache)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_metadata (
                    path TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    size INTEGER,
                    mtime INTEGER,
                    last_seen TIMESTAMP,
                    PRIMARY KEY (path, fingerprint)
                )
            """)
            
            # Create chunks table if not exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    chunk_index INTEGER,
                    content TEXT,
                    embedding_vector BLOB,
                    weaviate_id TEXT
                )
            """)
    
    def try_claim(self, job: IngestionJobMessage) -> ProcessingDecision:
        """Execute idempotence gate for a job.
        
        Implements the exact algorithm from specification FASE D.
        
        Returns:
            ProcessingDecision indicating whether to process, skip, or retry
        """
        now_ts = int(time.time())
        
        # Check current state in SQLite
        with self.sqlite_manager.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT status, attempts, started_at 
                FROM job_state 
                WHERE file_path = ? AND phase = ? AND fingerprint = ?
            """, (job.file_path, job.phase.value, job.fingerprint))
            
            row = cursor.fetchone()
        
        # Case A: State = DONE
        if row and row[0] == JobStatus.DONE.value:
            return ProcessingDecision.skip_reason("already_done")
        
        # Case B: State = IN_PROGRESS (valid)
        if row and row[0] == JobStatus.IN_PROGRESS.value:
            started_at = row[2] or 0
            if now_ts - started_at < self.timeout_seconds:
                # Job still in progress, skip
                return ProcessingDecision.skip_reason("in_progress")
            else:
                # Job timed out, can retry
                return ProcessingDecision.retry_reason("timed_out")
        
        # Case C: State = FAILED but retries available
        if row and row[0] in [JobStatus.FAILED.value, JobStatus.FAILED_FINAL.value]:
            attempts = row[1] or 0
            if attempts < self.MAX_RETRIES:
                return ProcessingDecision.retry_reason(f"failed_attempt_{attempts}")
            else:
                return ProcessingDecision.skip_reason("max_retries_exceeded")
        
        # Case D: State does not exist
        # Create new record with IN_PROGRESS status
        with self.sqlite_manager.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT INTO job_state 
                (file_path, phase, fingerprint, status, attempts, started_at)
                VALUES (?, ?, ?, ?, 1, ?)
            """, (
                job.file_path, 
                job.phase.value, 
                job.fingerprint, 
                JobStatus.IN_PROGRESS.value,
                now_ts
            ))
        
        return ProcessingDecision.process("new_job")
    
    def mark_done(self, job: IngestionJobMessage, metrics: Optional[Dict[str, Any]] = None) -> None:
        """Mark job as successfully completed.
        
        Args:
            job: The job that completed
            metrics: Optional metrics to store
        """
        now_ts = int(time.time())
        metrics_json = None
        
        if metrics:
            import json
            metrics_json = json.dumps(metrics)
        
        with self.sqlite_manager.control_plane.get_connection() as conn:
            conn.execute("""
                UPDATE job_state 
                SET status = ?, completed_at = ?, metrics = ?
                WHERE file_path = ? AND phase = ? AND fingerprint = ?
            """, (
                JobStatus.DONE.value,
                now_ts,
                metrics_json,
                job.file_path,
                job.phase.value,
                job.fingerprint
            ))
        
        log.debug("Marked job as DONE: %s %s %s", 
                  job.file_path, job.phase.value, job.fingerprint)
    
    def mark_failed(self, job: IngestionJobMessage, error: str, retryable: bool = True) -> None:
        """Mark job as failed.
        
        Args:
            job: The job that failed
            error: Error message
            retryable: Whether the failure is retryable
        """
        now_ts = int(time.time())
        
        # Get current attempts
        with self.sqlite_manager.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT attempts FROM job_state 
                WHERE file_path = ? AND phase = ? AND fingerprint = ?
            """, (job.file_path, job.phase.value, job.fingerprint))
            
            row = cursor.fetchone()
            current_attempts = (row[0] if row else 0) + 1
        
        # Determine status based on retryable flag and attempts
        if retryable and current_attempts < self.MAX_RETRIES:
            status = JobStatus.FAILED.value
        else:
            status = JobStatus.FAILED_FINAL.value
        
        with self.sqlite_manager.control_plane.get_connection() as conn:
            conn.execute("""
                UPDATE job_state 
                SET status = ?, attempts = ?, error = ?, completed_at = ?
                WHERE file_path = ? AND phase = ? AND fingerprint = ?
            """, (
                status,
                current_attempts,
                error,
                now_ts,
                job.file_path,
                job.phase.value,
                job.fingerprint
            ))
        
        log.debug("Marked job as %s: %s %s %s (attempts=%d)", 
                  status, job.file_path, job.phase.value, job.fingerprint, current_attempts)
    
    def get_status(self, file_path: str, phase: str, fingerprint: str) -> Optional[Dict[str, Any]]:
        """Get current status of a job.
        
        Args:
            file_path: File path
            phase: Job phase
            fingerprint: File fingerprint
            
        Returns:
            Dictionary with status information or None if not found
        """
        with self.sqlite_manager.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT status, attempts, started_at, completed_at, error, metrics
                FROM job_state 
                WHERE file_path = ? AND phase = ? AND fingerprint = ?
            """, (file_path, phase, fingerprint))
            
            row = cursor.fetchone()
            
            if not row:
                return None
            
            result = {
                "status": row[0],
                "attempts": row[1],
                "started_at": row[2],
                "completed_at": row[3],
                "error": row[4],
            }
            
            if row[5]:  # metrics
                import json
                try:
                    result["metrics"] = json.loads(row[5])
                except:
                    result["metrics"] = row[5]
            
            return result
    
    def create_run(self, run_id: str) -> None:
        """Create a new run record.
        
        Args:
            run_id: Run identifier
        """
        now_ts = int(time.time())
        
        with self.sqlite_manager.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT INTO runs (run_id, status, started_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    started_at = excluded.started_at
            """, (run_id, "RUNNING", now_ts))
        
        log.debug("Created run: %s", run_id)
    
    def complete_run(self, run_id: str, stats: Optional[Dict[str, Any]] = None) -> None:
        """Mark a run as completed.
        
        Args:
            run_id: Run identifier
            stats: Optional statistics to store
        """
        now_ts = int(time.time())
        stats_json = None
        
        if stats:
            import json
            stats_json = json.dumps(stats)
        
        with self.sqlite_manager.control_plane.get_connection() as conn:
            conn.execute("""
                UPDATE runs 
                SET status = 'COMPLETED', completed_at = ?, stats = ?
                WHERE run_id = ?
            """, (now_ts, stats_json, run_id))
        
        log.debug("Completed run: %s", run_id)
    
    def update_file_metadata(self, path: str, fingerprint: str, size: int, mtime: int) -> None:
        """Update file metadata for discovery cache.
        
        Args:
            path: File path
            fingerprint: File fingerprint
            size: File size in bytes
            mtime: File modification time
        """
        now_ts = int(time.time())
        
        with self.sqlite_manager.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT INTO file_metadata (path, fingerprint, size, mtime, last_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path, fingerprint) DO UPDATE SET
                    size = excluded.size,
                    mtime = excluded.mtime,
                    last_seen = excluded.last_seen
            """, (path, fingerprint, size, mtime, now_ts))
    
    def get_file_metadata(self, path: str) -> Optional[Dict[str, Any]]:
        """Get file metadata.
        
        Args:
            path: File path
            
        Returns:
            Dictionary with file metadata or None if not found
        """
        with self.sqlite_manager.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT fingerprint, size, mtime, last_seen
                FROM file_metadata 
                WHERE path = ?
                ORDER BY last_seen DESC
                LIMIT 1
            """, (path,))
            
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return {
                "fingerprint": row[0],
                "size": row[1],
                "mtime": row[2],
                "last_seen": row[3]
            }
