"""RabbitMQ-based ingestion queue with SQLite idempotence gating.

This module implements the RabbitMQIngestQueue which provides:
- Persistent job queue using RabbitMQ
- Integration with SQLite control plane for idempotence
- Worker gate logic based on SQLite status
- Automatic retry with exponential backoff
- Dead letter queue for failed jobs
- Consumer group support for parallel workers

Worker execution rule (idempotence gate):
1) Read relevant SQLite row(s) (file/chunk).
2) If already complete for that phase → ACK and exit.
3) Else execute the side-effect.
4) Update SQLite status.
5) ACK.
6) On failure:
   - increment retry_count
   - if under max retries: NACK or publish to retry queue
   - else: publish to DLQ and mark FAILED
"""

import json
import time
import uuid
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from src.messaging.broker import get_broker
from src.messaging.models.message import Message, MessagePayload
from src.backends.storage.sqlite.manager import get_sqlite_manager
from src.backends.storage.sqlite.repositories import ProcessingDecision, FileStatus, ChunkStatus
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class IngestionPhase(Enum):
    """Ingestion processing phases."""
    EXTRACT = "EXTRACT"
    CHUNK = "CHUNK"
    EMBED = "EMBED"
    UPSERT = "UPSERT"
    FINALIZE = "FINALIZE"


@dataclass
class IngestionJob:
    """Represents an ingestion job for RabbitMQ."""
    job_id: str
    phase: IngestionPhase
    run_id: str
    file_path: str
    chunk_id: Optional[str] = None
    attempt: int = 0
    options: Optional[Dict[str, Any]] = None
    created_at: float = 0.0
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary."""
        data = {
            "job_id": self.job_id,
            "phase": self.phase.value,
            "run_id": self.run_id,
            "file_path": self.file_path,
            "attempt": self.attempt,
            "created_at": self.created_at,
        }
        
        if self.chunk_id:
            data["chunk_id"] = self.chunk_id
        
        if self.options:
            data["options"] = json.dumps(self.options)
        
        if self.metadata:
            data["metadata"] = json.dumps(self.metadata)
        
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IngestionJob":
        """Create job from dictionary."""
        options = json.loads(data.get("options", "{}")) if data.get("options") else None
        metadata = json.loads(data.get("metadata", "{}")) if data.get("metadata") else None
        
        return cls(
            job_id=data["job_id"],
            phase=IngestionPhase(data["phase"]),
            run_id=data["run_id"],
            file_path=data["file_path"],
            chunk_id=data.get("chunk_id"),
            attempt=int(data.get("attempt", 0)),
            options=options,
            created_at=float(data.get("created_at", 0.0)),
            metadata=metadata
        )


class RabbitMQIngestQueue:
    """RabbitMQ-based ingestion queue with SQLite idempotence gating."""
    
    # Queue names
    WORK_QUEUE = "ingest.work"
    RETRY_QUEUE = "ingest.retry"
    DLQ_QUEUE = "ingest.dlq"
    
    # Configuration
    MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 2  # seconds
    PREFETCH_COUNT = 10
    
    def __init__(self, max_retries: int = MAX_RETRIES):
        """Initialize RabbitMQ ingestion queue.
        
        Args:
            max_retries: Maximum retry attempts before moving to DLQ
        """
        self.max_retries = max_retries
        self.broker = None
        self.sqlite_manager = get_sqlite_manager()
        self.file_metadata_store = self.sqlite_manager.get_file_metadata_store()
        self.chunk_registry_store = self.sqlite_manager.get_chunk_registry_store()
        
        log.info("RabbitMQIngestQueue initialized (max_retries=%d)", max_retries)
    
    def _get_priority(self, phase: IngestionPhase) -> int:
        """Get priority for a job phase.
        
        Higher priority = more important
        """
        priority_map = {
            IngestionPhase.EXTRACT: 5,
            IngestionPhase.CHUNK: 4,
            IngestionPhase.EMBED: 3,
            IngestionPhase.UPSERT: 2,
            IngestionPhase.FINALIZE: 1,
        }
        return priority_map.get(phase, 3)
    
    async def connect(self) -> None:
        """Connect to RabbitMQ broker."""
        self.broker = await get_broker()
    
    async def enqueue_job(
        self,
        phase: IngestionPhase,
        run_id: str,
        file_path: str,
        chunk_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Enqueue a job for processing.
        
        Args:
            phase: Processing phase
            run_id: Ingestion run identifier
            file_path: File path to process
            chunk_id: Optional chunk identifier (for chunk/embed/upsert phases)
            options: Optional processing options
            metadata: Optional job metadata
            
        Returns:
            Job ID
        """
        if not self.broker:
            await self.connect()
        
        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        job = IngestionJob(
            job_id=job_id,
            phase=phase,
            run_id=run_id,
            file_path=file_path,
            chunk_id=chunk_id,
            attempt=0,
            options=options,
            created_at=time.time(),
            metadata=metadata
        )
        
        # Create message payload
        payload = MessagePayload(
            operation=f"ingestion.{phase.value.lower()}",
            data=job.to_dict()
        )
        
        # Create message
        message = Message(
            message_id=job_id,
            source="ingestion_queue",
            destination="ingestion_worker",
            payload=payload,
            priority=self._get_priority(phase),
            correlation_id=run_id
        )
        
        # Publish to work queue
        success = await self.broker.publish(self.WORK_QUEUE, message)
        
        if success:
            log.debug("Enqueued job %s for %s phase (file=%s)", job_id, phase.value, file_path)
        else:
            log.error("Failed to enqueue job %s", job_id)
        
        return job_id
    
    async def enqueue_batch(
        self,
        phase: IngestionPhase,
        run_id: str,
        file_paths: List[str],
        options: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Enqueue multiple jobs efficiently.
        
        Args:
            phase: Processing phase
            run_id: Ingestion run identifier
            file_paths: List of file paths to process
            options: Optional processing options
            
        Returns:
            List of job IDs
        """
        if not self.broker:
            await self.connect()
        
        job_ids = []
        
        for file_path in file_paths:
            job_id = await self.enqueue_job(
                phase=phase,
                run_id=run_id,
                file_path=file_path,
                options=options
            )
            job_ids.append(job_id)
        
        log.info("Enqueued %d job(s) for %s phase (run_id=%s)", len(file_paths), phase.value, run_id)
        return job_ids
    
    async def process_jobs(
        self,
        worker_name: str,
        callback: Callable,
        batch_size: int = 10
    ) -> None:
        """Process jobs from the work queue.
        
        Args:
            worker_name: Unique worker identifier
            callback: Callback function to process jobs
            batch_size: Maximum number of jobs to process in batch
        """
        if not self.broker:
            await self.connect()
        
        log.info("Worker %s started processing jobs", worker_name)
        
        # Define message handler
        async def handle_message(message: Message) -> Dict[str, Any]:
            try:
                # Parse job from message payload
                job_data = message.payload.data
                job = IngestionJob.from_dict(job_data)
                
                log.debug("Worker %s processing job %s (phase=%s, file=%s)",
                         worker_name, job.job_id, job.phase.value, job.file_path)
                
                # Execute idempotence gate
                gate_result = await self._execute_idempotence_gate(job)
                
                if gate_result.get("skip", False):
                    log.debug("Skipping job %s (already %s)", job.job_id, gate_result.get("reason", "processed"))
                    return {"success": True, "skipped": True, "reason": gate_result.get("reason")}
                
                # Execute the job
                result = await callback(job, gate_result)
                
                if result.get("success", False):
                    # Update SQLite status
                    await self._update_sqlite_status(job, result)
                    log.debug("Job %s completed successfully", job.job_id)
                    return {"success": True}
                else:
                    # Handle failure
                    error = result.get("error", "Unknown error")
                    await self._handle_failure(job, error)
                    return {"success": False, "error": error}
                    
            except Exception as e:
                log.error("Error processing job: %s", e, exc_info=True)
                return {"success": False, "error": str(e)}
        
        # Start consuming messages
        await self.broker.consume(self.WORK_QUEUE, handle_message)
    
    async def _execute_idempotence_gate(self, job: IngestionJob) -> Dict[str, Any]:
        """Execute idempotence gate based on SQLite status.
        
        Returns:
            Dictionary with gate decision
        """
        now_ts = int(time.time())
        
        if job.phase == IngestionPhase.EXTRACT:
            # Check file status
            decision = self.file_metadata_store.decide_processing(
                job.file_path,
                mtime_ns=0,  # Will be updated during processing
                size_bytes=0,  # Will be updated during processing
                content_hash=None,
                now_ts=now_ts
            )
            
            if decision == ProcessingDecision.SKIP:
                return {"skip": True, "reason": "file_already_processed"}
            elif decision == ProcessingDecision.RETRY:
                return {"skip": False, "retry": True}
            else:
                return {"skip": False, "process": True}
        
        elif job.phase in [IngestionPhase.CHUNK, IngestionPhase.EMBED, IngestionPhase.UPSERT]:
            # Check chunk status
            if not job.chunk_id:
                return {"skip": False, "process": True}
            
            status = self.chunk_registry_store.get_chunk_status(job.chunk_id)
            
            # Map phase to expected status
            expected_status_map = {
                IngestionPhase.CHUNK: ChunkStatus.NEW,
                IngestionPhase.EMBED: ChunkStatus.NEW,
                IngestionPhase.UPSERT: ChunkStatus.EMBEDDED,
            }
            
            expected_status = expected_status_map.get(job.phase)
            
            if status == ChunkStatus.UPSERTED:
                return {"skip": True, "reason": "chunk_already_upserted"}
            elif job.phase == IngestionPhase.EMBED and status == ChunkStatus.EMBEDDED:
                return {"skip": True, "reason": "chunk_already_embedded"}
            elif status == ChunkStatus.FAILED:
                # Check if we should retry
                return {"skip": False, "retry": True}
            elif expected_status and status != expected_status:
                return {"skip": True, "reason": f"chunk_not_in_expected_state: {status.value}"}
            else:
                return {"skip": False, "process": True}
        
        else:
            return {"skip": False, "process": True}
    
    async def _update_sqlite_status(self, job: IngestionJob, result: Dict[str, Any]) -> None:
        """Update SQLite status after successful job execution."""
        now_ts = int(time.time())
        
        if job.phase == IngestionPhase.EXTRACT:
            # Update file status to EXTRACTED
            self.file_metadata_store.set_status(
                job.file_path,
                FileStatus.EXTRACTED,
                now_ts
            )
        
        elif job.phase == IngestionPhase.CHUNK:
            # Update file status to CHUNKED
            self.file_metadata_store.set_status(
                job.file_path,
                FileStatus.CHUNKED,
                now_ts
            )
            
            # Register chunks if provided
            chunks = result.get("chunks", [])
            if chunks:
                self.chunk_registry_store.register_chunks(
                    job.file_path,
                    chunks,
                    now_ts
                )
        
        elif job.phase == IngestionPhase.EMBED:
            # Update chunk status to EMBEDDED
            if job.chunk_id:
                vector_id = result.get("vector_id")
                self.chunk_registry_store.set_chunk_status(
                    job.chunk_id,
                    ChunkStatus.EMBEDDED,
                    now_ts,
                    vector_id=vector_id
                )
        
        elif job.phase == IngestionPhase.UPSERT:
            # Update chunk status to UPSERTED
            if job.chunk_id:
                self.chunk_registry_store.set_chunk_status(
                    job.chunk_id,
                    ChunkStatus.UPSERTED,
                    now_ts
                )
            
            # Update file status to UPSERTED if all chunks are done
            # (This would require checking all chunks for the file)
    
    async def _handle_failure(self, job: IngestionJob, error: str) -> None:
        """Handle job failure with retry logic."""
        now_ts = int(time.time())
        
        if job.attempt >= self.max_retries:
            # Move to DLQ
            await self._move_to_dlq(job, error)
            
            # Mark as FAILED in SQLite
            if job.phase == IngestionPhase.EXTRACT:
                self.file_metadata_store.set_status(
                    job.file_path,
                    FileStatus.FAILED,
                    now_ts,
                    error=error
                )
            elif job.chunk_id:
                self.chunk_registry_store.set_chunk_status(
                    job.chunk_id,
                    ChunkStatus.FAILED,
                    now_ts,
                    error=error
                )
            
            log.warning("Job %s failed after %d retries, moved to DLQ", job.job_id, job.attempt)
        
        else:
            # Increment retry count and requeue
            job.attempt += 1
            backoff = self.RETRY_BACKOFF_BASE ** job.attempt
            
            log.info("Job %s failed (attempt %d/%d), will retry in %ds",
                    job.job_id, job.attempt, self.max_retries, backoff)
            
            # Update retry count in SQLite
            if job.chunk_id:
                self.chunk_registry_store.increment_retry(job.chunk_id, now_ts)
            
            # Requeue with delay
            await self._requeue_with_delay(job, backoff)
    
    async def _move_to_dlq(self, job: IngestionJob, error: str) -> None:
        """Move failed job to dead letter queue."""
        if not self.broker:
            await self.connect()
        
        # Add error to metadata
        dlq_metadata = job.metadata or {}
        dlq_metadata.update({
            "failed_at": time.time(),
            "error": error,
            "final_attempt": job.attempt
        })
        
        dlq_job = IngestionJob(
            job_id=job.job_id,
            phase=job.phase,
            run_id=job.run_id,
            file_path=job.file_path,
            chunk_id=job.chunk_id,
            attempt=job.attempt,
            options=job.options,
            created_at=job.created_at,
            metadata=dlq_metadata
        )
        
        # Create DLQ message payload
        payload = MessagePayload(
            operation=f"ingestion.dlq.{job.phase.value.lower()}",
            data=dlq_job.to_dict()
        )
        
        # Create DLQ message
        message = Message(
            message_id=f"dlq_{job.job_id}",
            source="ingestion_queue",
            destination="dlq_processor",
            payload=payload,
            priority=0,
            correlation_id=job.run_id
        )
        
        # Publish to DLQ
        await self.broker.publish(self.DLQ_QUEUE, message)
    
    async def _requeue_with_delay(self, job: IngestionJob, delay_seconds: int) -> None:
        """Requeue job with delay using retry queue."""
        if not self.broker:
            await self.connect()
        
        # Create retry message with delay metadata
        retry_metadata = job.metadata or {}
        retry_metadata.update({
            "retry_at": time.time() + delay_seconds,
            "retry_count": job.attempt
        })
        
        retry_job = IngestionJob(
            job_id=job.job_id,
            phase=job.phase,
            run_id=job.run_id,
            file_path=job.file_path,
            chunk_id=job.chunk_id,
            attempt=job.attempt,
            options=job.options,
            created_at=job.created_at,
            metadata=retry_metadata
        )
        
        # Create retry message payload
        payload = MessagePayload(
            operation=f"ingestion.retry.{job.phase.value.lower()}",
            data=retry_job.to_dict()
        )
        
        # Create retry message
        message = Message(
            message_id=f"retry_{job.job_id}",
            source="ingestion_queue",
            destination="ingestion_worker",
            payload=payload,
            priority=self._get_priority(job.phase),
            correlation_id=job.run_id
        )
        
        # Publish to retry queue
        await self.broker.publish(self.RETRY_QUEUE, message)
        
        log.debug("Requeued job %s with %ds delay (attempt %d)", 
                  job.job_id, delay_seconds, job.attempt)
