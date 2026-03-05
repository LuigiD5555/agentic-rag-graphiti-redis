"""RabbitMQ-based ingestion queue with SQLite idempotence gating.

This module implements the RabbitMQIngestQueue which provides:
- Persistent job queue using RabbitMQ
- Integration with SQLite control plane for idempotence (via JobStateRepository)
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

from src.messaging.broker import get_broker
from src.messaging.config import config as broker_config
from src.messaging.models.message import Message, MessagePayload
from src.workflows.ingestion.jobs.models import IngestionJobMessage, IngestionPhase, ProcessingDecision
from src.workflows.ingestion.state.job_state_repository import JobStateRepository
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class RabbitMQIngestQueue:
    """RabbitMQ-based ingestion queue with SQLite idempotence gating."""
    
    # Queue names — must match broker_config.ingest_*_queue
    WORK_QUEUE = broker_config.ingest_work_queue
    RETRY_QUEUE = broker_config.ingest_retry_queue
    DLQ_QUEUE = broker_config.ingest_dlq_queue
    
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
        self.state_repository = JobStateRepository()
        
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
        
        # Create job message (fingerprint will be calculated by planner)
        # For now, use a placeholder fingerprint
        import hashlib
        import os
        try:
            stat = os.stat(file_path)
            fingerprint_content = f"{file_path}:{stat.st_size}:{stat.st_mtime}"
            fingerprint = hashlib.sha256(fingerprint_content.encode()).hexdigest()[:16]
        except:
            fingerprint = "unknown"
        
        job = IngestionJobMessage.create(
            phase=phase,
            run_id=run_id,
            file_path=file_path,
            fingerprint=fingerprint,
            options=options,
            metadata=metadata,
            chunk_id=chunk_id
        )
        
        # Create message payload
        payload = MessagePayload(
            operation=f"ingestion.{phase.value.lower()}",
            data=job.to_dict()
        )
        
        # Create message
        message = Message(
            message_id=job.job_id,
            source="ingestion_queue",
            destination="ingestion_worker",
            payload=payload,
            priority=self._get_priority(phase),
            correlation_id=run_id
        )
        
        # Publish to work queue
        success = await self.broker.publish(self.WORK_QUEUE, message)
        
        if success:
            log.debug("Enqueued job %s for %s phase (file=%s)", job.job_id, phase.value, file_path)
        else:
            log.error("Failed to enqueue job %s", job.job_id)
        
        return job.job_id
    
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
                job = IngestionJobMessage.from_dict(job_data)
                
                log.debug("Worker %s processing job %s (phase=%s, file=%s)",
                         worker_name, job.job_id, job.phase.value, job.file_path)
                
                # Execute idempotence gate using JobStateRepository
                decision = self.state_repository.try_claim(job)
                
                if decision.skip:
                    log.debug("Skipping job %s (reason: %s)", job.job_id, decision.reason)
                    return {"success": True, "skipped": True, "reason": decision.reason}
                
                if decision.retry:
                    log.info("Retrying job %s (reason: %s)", job.job_id, decision.reason)
                
                # Execute the job
                result = await callback(job, {"decision": decision})
                
                if result.get("success", False):
                    # Update SQLite status
                    metrics = result.get("metrics", {})
                    self.state_repository.mark_done(job, metrics)
                    log.debug("Job %s completed successfully", job.job_id)
                    return {"success": True}
                else:
                    # Handle failure
                    error = result.get("error", "Unknown error")
                    retryable = result.get("retryable", True)
                    self.state_repository.mark_failed(job, error, retryable)
                    
                    if retryable and job.attempt < self.max_retries:
                        # Requeue with delay
                        await self._requeue_with_delay(job, error)
                        return {"success": False, "error": error, "requeued": True}
                    else:
                        # Move to DLQ
                        await self._move_to_dlq(job, error)
                        return {"success": False, "error": error, "dlq": True}
                    
            except Exception as e:
                log.error("Error processing job: %s", e, exc_info=True)
                return {"success": False, "error": str(e)}
        
        # Start consuming messages
        await self.broker.consume(self.WORK_QUEUE, handle_message)
    
    async def _move_to_dlq(self, job: IngestionJobMessage, error: str) -> None:
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
        
        dlq_job = IngestionJobMessage(
            job_id=job.job_id,
            phase=job.phase,
            run_id=job.run_id,
            file_path=job.file_path,
            fingerprint=job.fingerprint,
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
        
        log.warning("Job %s moved to DLQ after %d retries", job.job_id, job.attempt)
    
    async def _requeue_with_delay(self, job: IngestionJobMessage, error: str) -> None:
        """Requeue job with delay using retry queue."""
        if not self.broker:
            await self.connect()
        
        # Increment attempt count
        job.attempt += 1
        backoff = self.RETRY_BACKOFF_BASE ** job.attempt
        
        log.info("Job %s failed (attempt %d/%d), will retry in %ds",
                job.job_id, job.attempt, self.max_retries, backoff)
        
        # Create retry message with delay metadata
        retry_metadata = job.metadata or {}
        retry_metadata.update({
            "retry_at": time.time() + backoff,
            "retry_count": job.attempt,
            "last_error": error
        })
        
        retry_job = IngestionJobMessage(
            job_id=job.job_id,
            phase=job.phase,
            run_id=job.run_id,
            file_path=job.file_path,
            fingerprint=job.fingerprint,
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
                  job.job_id, backoff, job.attempt)