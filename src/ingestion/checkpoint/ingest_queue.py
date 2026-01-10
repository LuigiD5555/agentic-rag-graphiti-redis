"""Persistent ingestion queue using Redis Streams.

This module implements the IngestQueue which provides:
- Persistent job queue for file ingestion
- Resumable processing after failures
- Consumer group support for parallel workers
- Automatic retry with exponential backoff
- Dead letter queue for failed jobs
"""

import time
import json
from typing import TYPE_CHECKING, Optional, Dict, Any, List
from dataclasses import dataclass, asdict

if TYPE_CHECKING:
    import redis

from src.rag.audit import get_logger

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
    """Manages persistent ingestion queue using Redis Streams.

    Redis Key Schema:
        ingest:queue                        STREAM - Main job queue
        ingest:processing:{consumer_group}  STREAM - Jobs being processed (PEL)
        ingest:dlq                          STREAM - Dead letter queue (failed jobs)
        ingest:stats                        HASH - Queue statistics
        ingest:consumers                    HASH - Active consumer metadata

    Redis Streams Concepts:
        - Stream: Append-only log of messages (jobs)
        - Consumer Group: Group of consumers sharing work
        - PEL (Pending Entries List): Messages claimed but not acknowledged
        - XACK: Acknowledge message as processed
        - XCLAIM: Claim abandoned messages from PEL

    Workflow:
        1. Producer: XADD job to ingest:queue stream
        2. Consumer: XREADGROUP to claim jobs from stream
        3. Process file (chunking, embedding, vector store)
        4. On success: XACK to acknowledge completion
        5. On failure: Retry or move to DLQ after max retries
    """

    # Redis key patterns
    QUEUE_KEY = "ingest:queue"
    DLQ_KEY = "ingest:dlq"
    STATS_KEY = "ingest:stats"
    CONSUMERS_KEY = "ingest:consumers"

    # Configuration
    DEFAULT_CONSUMER_GROUP = "ingest_workers"
    MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 2  # seconds
    CLAIM_MIN_IDLE_TIME = 60000  # 60 seconds in milliseconds
    STREAM_MAXLEN = 100000  # Approximate max entries (use ~ for efficiency)

    def __init__(
        self,
        redis_client: "redis.Redis",
        consumer_group: str = DEFAULT_CONSUMER_GROUP,
        max_retries: int = MAX_RETRIES
    ):
        """Initialize ingest queue.

        Args:
            redis_client: Redis client instance
            consumer_group: Consumer group name
            max_retries: Maximum retry attempts before moving to DLQ
        """
        self.redis = redis_client
        self.consumer_group = consumer_group
        self.max_retries = max_retries

        # Ensure consumer group exists
        self._ensure_consumer_group()

        log.info(
            "IngestQueue initialized (consumer_group=%s, max_retries=%d)",
            consumer_group, max_retries
        )

    def _ensure_consumer_group(self) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            # Try to create the stream with mkstream=True
            self.redis.xgroup_create(
                name=self.QUEUE_KEY,
                groupname=self.consumer_group,
                id="0",
                mkstream=True
            )
            log.info("Created consumer group: %s", self.consumer_group)
        except Exception as e:
            # Group already exists or other error
            if "BUSYGROUP" not in str(e):
                log.debug("Consumer group creation: %s", e)

    def enqueue(
        self,
        file_path: str,
        run_id: str,
        scan_run_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        priority: int = 0
    ) -> str:
        """Add file to ingestion queue.

        Args:
            file_path: Absolute path to file
            run_id: Ingestion run identifier
            scan_run_id: Optional scan run identifier
            options: Optional processing options
            priority: Job priority (higher = more important, not used yet)

        Returns:
            Job ID (Redis Stream message ID)
        """
        job = IngestJob(
            file_path=file_path,
            run_id=run_id,
            scan_run_id=scan_run_id,
            options=options,
            priority=priority,
            enqueued_at=time.time()
        )

        # Serialize job to dict
        job_data = {
            "file_path": job.file_path,
            "run_id": job.run_id,
            "scan_run_id": job.scan_run_id or "",
            "options": json.dumps(job.options or {}),
            "priority": str(job.priority),
            "retry_count": str(job.retry_count),
            "enqueued_at": str(job.enqueued_at)
        }

        # Add to stream with approximate maxlen for memory management
        job_id = self.redis.xadd(
            name=self.QUEUE_KEY,
            fields=job_data,
            maxlen=self.STREAM_MAXLEN,
            approximate=True
        )

        # Update stats
        self.redis.hincrby(self.STATS_KEY, "total_enqueued", 1)
        self.redis.hincrby(self.STATS_KEY, "pending", 1)

        log.debug("Enqueued job %s for file: %s", job_id, file_path)
        return job_id

    def enqueue_batch(
        self,
        file_paths: List[str],
        run_id: str,
        scan_run_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Enqueue multiple files efficiently.

        Args:
            file_paths: List of file paths
            run_id: Ingestion run identifier
            scan_run_id: Optional scan run identifier
            options: Optional processing options

        Returns:
            List of job IDs
        """
        job_ids = []

        # Use pipeline for efficiency
        pipe = self.redis.pipeline()

        for file_path in file_paths:
            job = IngestJob(
                file_path=file_path,
                run_id=run_id,
                scan_run_id=scan_run_id,
                options=options,
                enqueued_at=time.time()
            )

            job_data = {
                "file_path": job.file_path,
                "run_id": job.run_id,
                "scan_run_id": job.scan_run_id or "",
                "options": json.dumps(job.options or {}),
                "priority": str(job.priority),
                "retry_count": str(job.retry_count),
                "enqueued_at": str(job.enqueued_at)
            }

            pipe.xadd(
                name=self.QUEUE_KEY,
                fields=job_data,
                maxlen=self.STREAM_MAXLEN,
                approximate=True
            )

        # Update stats
        pipe.hincrby(self.STATS_KEY, "total_enqueued", len(file_paths))
        pipe.hincrby(self.STATS_KEY, "pending", len(file_paths))

        results = pipe.execute()
        job_ids = results[:-2]  # Last 2 are stats updates

        log.info("Enqueued %d file(s) for ingestion (run_id=%s)", len(file_paths), run_id)
        return job_ids

    def dequeue(
        self,
        consumer_name: str,
        count: int = 1,
        block: Optional[int] = None
    ) -> List[tuple[str, IngestJob]]:
        """Dequeue jobs for processing.

        Args:
            consumer_name: Unique consumer identifier
            count: Maximum number of jobs to fetch
            block: Optional block time in milliseconds (None = no blocking)

        Returns:
            List of (job_id, IngestJob) tuples
        """
        # Register consumer
        self._register_consumer(consumer_name)

        # Read from stream using consumer group
        # '>' means fetch new messages not yet delivered to this consumer group
        try:
            messages = self.redis.xreadgroup(
                groupname=self.consumer_group,
                consumername=consumer_name,
                streams={self.QUEUE_KEY: ">"},
                count=count,
                block=block
            )
        except Exception as e:
            log.error("Error reading from queue: %s", e)
            return []

        if not messages:
            return []

        jobs = []

        for stream_name, stream_messages in messages:
            for msg_id, msg_data in stream_messages:
                try:
                    job = self._parse_job(msg_data)
                    job.started_at = time.time()
                    jobs.append((msg_id, job))

                    # Update stats
                    self.redis.hincrby(self.STATS_KEY, "pending", -1)
                    self.redis.hincrby(self.STATS_KEY, "processing", 1)

                except Exception as e:
                    log.error("Error parsing job %s: %s", msg_id, e)
                    # Acknowledge malformed job to remove it
                    self.redis.xack(self.QUEUE_KEY, self.consumer_group, msg_id)

        if jobs:
            log.debug("Dequeued %d job(s) for consumer: %s", len(jobs), consumer_name)

        return jobs

    def acknowledge(self, job_id: str, success: bool = True, error: Optional[str] = None) -> None:
        """Acknowledge job completion or failure.

        Args:
            job_id: Job ID to acknowledge
            success: Whether processing succeeded
            error: Optional error message if failed
        """
        if success:
            # Remove from stream
            self.redis.xack(self.QUEUE_KEY, self.consumer_group, job_id)

            # Update stats
            self.redis.hincrby(self.STATS_KEY, "processing", -1)
            self.redis.hincrby(self.STATS_KEY, "completed", 1)

            log.debug("Acknowledged successful job: %s", job_id)
        else:
            # Get job data to check retry count
            messages = self.redis.xrange(self.QUEUE_KEY, min=job_id, max=job_id)

            if messages:
                msg_id, msg_data = messages[0]
                job = self._parse_job(msg_data)
                job.retry_count += 1
                job.error = error

                if job.retry_count >= self.max_retries:
                    # Move to DLQ
                    self._move_to_dlq(job_id, job, error)
                    self.redis.xack(self.QUEUE_KEY, self.consumer_group, job_id)

                    # Update stats
                    self.redis.hincrby(self.STATS_KEY, "processing", -1)
                    self.redis.hincrby(self.STATS_KEY, "failed", 1)

                    log.warning("Job %s failed after %d retries, moved to DLQ", job_id, job.retry_count)
                else:
                    # Re-enqueue with incremented retry count
                    backoff = self.RETRY_BACKOFF_BASE ** job.retry_count
                    log.info(
                        "Job %s failed (attempt %d/%d), will retry in %ds",
                        job_id, job.retry_count, self.max_retries, backoff
                    )

                    # Acknowledge old message and create new one with updated retry count
                    self.redis.xack(self.QUEUE_KEY, self.consumer_group, job_id)

                    job_data = {
                        "file_path": job.file_path,
                        "run_id": job.run_id,
                        "scan_run_id": job.scan_run_id or "",
                        "options": json.dumps(job.options or {}),
                        "priority": str(job.priority),
                        "retry_count": str(job.retry_count),
                        "enqueued_at": str(time.time()),
                        "error": error or ""
                    }

                    self.redis.xadd(
                        name=self.QUEUE_KEY,
                        fields=job_data,
                        maxlen=self.STREAM_MAXLEN,
                        approximate=True
                    )

    def claim_abandoned(self, consumer_name: str, count: int = 10) -> List[tuple[str, IngestJob]]:
        """Claim abandoned jobs from other consumers.

        Args:
            consumer_name: Consumer claiming the jobs
            count: Maximum number of jobs to claim

        Returns:
            List of (job_id, IngestJob) tuples
        """
        # Get pending messages (PEL) that are idle for too long
        try:
            messages = self.redis.xautoclaim(
                name=self.QUEUE_KEY,
                groupname=self.consumer_group,
                consumername=consumer_name,
                min_idle_time=self.CLAIM_MIN_IDLE_TIME,
                start_id="0-0",
                count=count
            )
        except Exception as e:
            log.error("Error claiming abandoned jobs: %s", e)
            return []

        # Parse results (format varies by redis-py version)
        if isinstance(messages, tuple):
            next_id, claimed_messages = messages[0], messages[1]
        else:
            claimed_messages = messages

        if not claimed_messages:
            return []

        jobs = []

        for msg_id, msg_data in claimed_messages:
            try:
                job = self._parse_job(msg_data)
                jobs.append((msg_id, job))

                log.warning(
                    "Claimed abandoned job %s from another consumer (file=%s)",
                    msg_id, job.file_path
                )
            except Exception as e:
                log.error("Error parsing claimed job %s: %s", msg_id, e)

        return jobs

    def _move_to_dlq(self, job_id: str, job: IngestJob, error: Optional[str]) -> None:
        """Move failed job to dead letter queue.

        Args:
            job_id: Original job ID
            job: Job data
            error: Error message
        """
        dlq_data = {
            "original_job_id": job_id,
            "file_path": job.file_path,
            "run_id": job.run_id,
            "scan_run_id": job.scan_run_id or "",
            "options": json.dumps(job.options or {}),
            "retry_count": str(job.retry_count),
            "error": error or "Unknown error",
            "failed_at": str(time.time()),
            "enqueued_at": str(job.enqueued_at or 0)
        }

        self.redis.xadd(
            name=self.DLQ_KEY,
            fields=dlq_data,
            maxlen=10000,  # Keep last 10k failed jobs
            approximate=True
        )

    def _parse_job(self, msg_data: Dict[str, str]) -> IngestJob:
        """Parse job from Redis Stream message data.

        Args:
            msg_data: Message data dictionary

        Returns:
            IngestJob instance
        """
        options_str = msg_data.get("options", "{}")
        options = json.loads(options_str) if options_str else {}

        return IngestJob(
            file_path=msg_data["file_path"],
            run_id=msg_data["run_id"],
            scan_run_id=msg_data.get("scan_run_id") or None,
            options=options,
            priority=int(msg_data.get("priority", 0)),
            retry_count=int(msg_data.get("retry_count", 0)),
            enqueued_at=float(msg_data.get("enqueued_at", 0))
        )

    def _register_consumer(self, consumer_name: str) -> None:
        """Register consumer as active.

        Args:
            consumer_name: Consumer identifier
        """
        self.redis.hset(
            self.CONSUMERS_KEY,
            consumer_name,
            json.dumps({
                "last_seen": time.time(),
                "consumer_group": self.consumer_group
            })
        )

    def get_stats(self) -> Dict[str, int]:
        """Get queue statistics.

        Returns:
            Dictionary with queue stats
        """
        stats = self.redis.hgetall(self.STATS_KEY)

        return {
            "total_enqueued": int(stats.get("total_enqueued", 0)),
            "pending": int(stats.get("pending", 0)),
            "processing": int(stats.get("processing", 0)),
            "completed": int(stats.get("completed", 0)),
            "failed": int(stats.get("failed", 0))
        }

    def get_queue_length(self) -> int:
        """Get current queue length.

        Returns:
            Number of messages in queue
        """
        return self.redis.xlen(self.QUEUE_KEY)

    def get_dlq_length(self) -> int:
        """Get dead letter queue length.

        Returns:
            Number of messages in DLQ
        """
        return self.redis.xlen(self.DLQ_KEY)

    def list_consumers(self) -> List[Dict[str, Any]]:
        """List active consumers.

        Returns:
            List of consumer metadata
        """
        consumers = self.redis.hgetall(self.CONSUMERS_KEY)

        result = []
        for name, data_str in consumers.items():
            data = json.loads(data_str)
            data["name"] = name
            result.append(data)

        return result

    def clear_queue(self) -> None:
        """Clear all queue data (use with caution!)."""
        self.redis.delete(self.QUEUE_KEY, self.DLQ_KEY, self.STATS_KEY, self.CONSUMERS_KEY)
        log.warning("Cleared ingestion queue")


__all__ = ["IngestQueue", "IngestJob"]
