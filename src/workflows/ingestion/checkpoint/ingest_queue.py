"""Persistent ingestion queue backed by SQLite.

This module provides IngestQueue with a Redis-compatible API, implemented
on top of the SQLite control plane.
"""

import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from src.backends.storage.sqlite.manager import get_sqlite_manager
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


@dataclass
class IngestJob:
    """Represents a file ingestion job."""
    file_path: str
    run_id: str
    scan_run_id: Optional[str] = None
    options: Optional[Dict[str, Any]] = None
    priority: int = 0
    retry_count: int = 0
    enqueued_at: Optional[float] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None


class IngestQueue:
    """Manages persistent ingestion queue using SQLite."""

    # Configuration
    DEFAULT_CONSUMER_GROUP = "ingest_workers"
    MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 2  # seconds
    CLAIM_MIN_IDLE_TIME = 60000  # 60 seconds in milliseconds

    def __init__(
        self,
        consumer_group: str = DEFAULT_CONSUMER_GROUP,
        max_retries: int = MAX_RETRIES,
    ):
        self.consumer_group = consumer_group
        self.max_retries = max_retries
        self.sqlite_manager = get_sqlite_manager()
        self.control_plane = self.sqlite_manager.control_plane

        log.info(
            "IngestQueue initialized (consumer_group=%s, max_retries=%d)",
            consumer_group,
            max_retries,
        )

    def _register_consumer(self, consumer_name: str) -> None:
        now_ts = int(time.time())
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ingest_consumers
                (consumer_name, last_seen, consumer_group)
                VALUES (?, ?, ?)
                """,
                (consumer_name, now_ts, self.consumer_group),
            )

    def enqueue(
        self,
        file_path: str,
        run_id: str,
        scan_run_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        priority: int = 0,
    ) -> str:
        """Add file to ingestion queue."""
        now_ts = int(time.time())
        job_id = f"job_{now_ts}_{uuid.uuid4().hex[:8]}"

        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO ingest_jobs
                (job_id, run_id, scan_run_id, file_path, options_json,
                 priority, retry_count, status, enqueued_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    run_id,
                    scan_run_id,
                    file_path,
                    json.dumps(options or {}),
                    int(priority),
                    0,
                    "pending",
                    now_ts,
                    now_ts,
                ),
            )

        log.debug("Enqueued job %s for file: %s", job_id, file_path)
        return job_id

    def enqueue_batch(
        self,
        file_paths: List[str],
        run_id: str,
        scan_run_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Enqueue multiple files efficiently."""
        now_ts = int(time.time())
        job_ids = []

        with self.control_plane.get_connection() as conn:
            for file_path in file_paths:
                job_id = f"job_{now_ts}_{uuid.uuid4().hex[:8]}"
                job_ids.append(job_id)
                conn.execute(
                    """
                    INSERT INTO ingest_jobs
                    (job_id, run_id, scan_run_id, file_path, options_json,
                     priority, retry_count, status, enqueued_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        run_id,
                        scan_run_id,
                        file_path,
                        json.dumps(options or {}),
                        0,
                        0,
                        "pending",
                        now_ts,
                        now_ts,
                    ),
                )

        log.info("Enqueued %d file(s) for ingestion (run_id=%s)", len(file_paths), run_id)
        return job_ids

    def _fetch_jobs(self, job_ids: List[str]) -> List[tuple[str, IngestJob]]:
        if not job_ids:
            return []
        placeholders = ",".join("?" for _ in job_ids)
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT job_id, file_path, run_id, scan_run_id, options_json,
                       priority, retry_count, enqueued_at, started_at,
                       completed_at, error
                FROM ingest_jobs
                WHERE job_id IN ({placeholders})
                """,
                job_ids,
            )
            jobs = []
            for row in cursor.fetchall():
                job = IngestJob(
                    file_path=row[1],
                    run_id=row[2],
                    scan_run_id=row[3],
                    options=json.loads(row[4]) if row[4] else None,
                    priority=int(row[5] or 0),
                    retry_count=int(row[6] or 0),
                    enqueued_at=float(row[7]) if row[7] else None,
                    started_at=float(row[8]) if row[8] else None,
                    completed_at=float(row[9]) if row[9] else None,
                    error=row[10],
                )
                jobs.append((row[0], job))
            return jobs

    def dequeue(
        self,
        consumer_name: str,
        count: int = 1,
        block: Optional[int] = None,
    ) -> List[tuple[str, IngestJob]]:
        """Dequeue jobs for processing."""
        self._register_consumer(consumer_name)

        deadline = None
        if block is not None:
            deadline = time.time() + (block / 1000.0)

        while True:
            now_ts = int(time.time())
            with self.control_plane.get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    """
                    SELECT job_id FROM ingest_jobs
                    WHERE status = 'pending' AND enqueued_at <= ?
                    ORDER BY priority DESC, enqueued_at ASC
                    LIMIT ?
                    """,
                    (now_ts, count),
                )
                job_ids = [row[0] for row in cursor.fetchall()]

                if job_ids:
                    placeholders = ",".join("?" for _ in job_ids)
                    conn.execute(
                        f"""
                        UPDATE ingest_jobs
                        SET status = 'processing',
                            started_at = ?,
                            consumer_name = ?,
                            updated_at = ?
                        WHERE job_id IN ({placeholders})
                        """,
                        (now_ts, consumer_name, now_ts, *job_ids),
                    )
                    conn.commit()
                    return self._fetch_jobs(job_ids)

                conn.commit()

            if deadline is None or time.time() >= deadline:
                return []

            time.sleep(0.1)

    def acknowledge(self, job_id: str, success: bool = True, error: Optional[str] = None) -> None:
        """Acknowledge job completion or failure."""
        now_ts = int(time.time())
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT retry_count FROM ingest_jobs WHERE job_id = ?",
                (job_id,),
            )
            row = cursor.fetchone()
            retry_count = int(row[0]) if row else 0

            if success:
                conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET status = 'completed',
                        completed_at = ?,
                        error = NULL,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (now_ts, now_ts, job_id),
                )
                log.debug("Acknowledged successful job: %s", job_id)
                return

            retry_count += 1

            if retry_count >= self.max_retries:
                conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET status = 'dlq',
                        completed_at = ?,
                        retry_count = ?,
                        error = ?,
                        updated_at = ?
                    WHERE job_id = ?
                    """,
                    (now_ts, retry_count, error, now_ts, job_id),
                )
                log.warning("Job %s failed after %d retries, moved to DLQ", job_id, retry_count)
                return

            backoff = self.RETRY_BACKOFF_BASE ** retry_count
            next_available = now_ts + int(backoff)
            conn.execute(
                """
                UPDATE ingest_jobs
                SET status = 'pending',
                    retry_count = ?,
                    error = ?,
                    started_at = NULL,
                    consumer_name = NULL,
                    enqueued_at = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (retry_count, error, next_available, now_ts, job_id),
            )
            log.info(
                "Job %s failed (attempt %d/%d), will retry in %ds",
                job_id,
                retry_count,
                self.max_retries,
                backoff,
            )

    def claim_abandoned(self, consumer_name: str, count: int = 10) -> List[tuple[str, IngestJob]]:
        """Claim abandoned jobs from other consumers."""
        self._register_consumer(consumer_name)
        now_ts = int(time.time())
        min_idle_seconds = int(self.CLAIM_MIN_IDLE_TIME / 1000)
        cutoff = now_ts - min_idle_seconds

        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT job_id FROM ingest_jobs
                WHERE status = 'processing' AND started_at IS NOT NULL AND started_at <= ?
                ORDER BY started_at ASC
                LIMIT ?
                """,
                (cutoff, count),
            )
            job_ids = [row[0] for row in cursor.fetchall()]

            if not job_ids:
                return []

            placeholders = ",".join("?" for _ in job_ids)
            conn.execute(
                f"""
                UPDATE ingest_jobs
                SET consumer_name = ?, started_at = ?, updated_at = ?
                WHERE job_id IN ({placeholders})
                """,
                (consumer_name, now_ts, now_ts, *job_ids),
            )

        return self._fetch_jobs(job_ids)

    def get_stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT status, COUNT(*) FROM ingest_jobs
                GROUP BY status
                """
            )
            counts = {row[0]: int(row[1]) for row in cursor.fetchall()}

        return {
            "total_enqueued": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "processing": counts.get("processing", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("dlq", 0),
        }

    def get_queue_length(self) -> int:
        """Get current queue length."""
        with self.control_plane.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM ingest_jobs WHERE status = 'pending'"
            ).fetchone()
        return int(row[0]) if row else 0

    def get_dlq_length(self) -> int:
        """Get dead letter queue length."""
        with self.control_plane.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM ingest_jobs WHERE status = 'dlq'"
            ).fetchone()
        return int(row[0]) if row else 0

    def list_consumers(self) -> List[Dict[str, Any]]:
        """List active consumers."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT consumer_name, last_seen, consumer_group
                FROM ingest_consumers
                ORDER BY last_seen DESC
                """
            )
            return [
                {
                    "name": row[0],
                    "last_seen": int(row[1]),
                    "consumer_group": row[2],
                }
                for row in cursor.fetchall()
            ]

    def clear_queue(self) -> None:
        """Clear all queue data (use with caution!)."""
        with self.control_plane.get_connection() as conn:
            conn.execute("DELETE FROM ingest_jobs")
            conn.execute("DELETE FROM ingest_consumers")
        log.warning("Cleared ingestion queue data")


__all__ = ["IngestQueue", "IngestJob"]
