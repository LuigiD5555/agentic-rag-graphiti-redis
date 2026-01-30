"""Ingestion worker that consumes jobs from RabbitMQ and executes them."""

import asyncio
import os
import socket
from typing import Callable, Dict, Any, Optional

from src.workflows.ingestion.jobs.models import IngestionJobMessage, IngestionPhase
from src.workflows.ingestion.state.job_state_repository import JobStateRepository
from src.workflows.ingestion.rabbitmq_queue import RabbitMQIngestQueue
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class IngestionWorker:
    """Worker that consumes jobs from RabbitMQ and executes them.
    
    Follows specification: Worker consumes, checks SQLite, executes, updates SQLite, ACKs.
    """
    
    def __init__(
        self,
        worker_name: Optional[str] = None,
        state_repository: Optional[JobStateRepository] = None,
        max_retries: int = 3
    ):
        """Initialize ingestion worker.
        
        Args:
            worker_name: Unique worker identifier (defaults to hostname_pid)
            state_repository: Optional job state repository
            max_retries: Maximum retry attempts
        """
        self.worker_name = worker_name or self._generate_worker_name()
        self.state_repository = state_repository or JobStateRepository()
        self.queue = None
        self.max_retries = max_retries
        self.running = False
        
        log.info("IngestionWorker initialized: %s", self.worker_name)
    
    def _generate_worker_name(self) -> str:
        """Generate unique worker name."""
        hostname = socket.gethostname()
        pid = os.getpid()
        return f"{hostname}_{pid}"
    
    async def connect_queue(self) -> None:
        """Connect to RabbitMQ queue."""
        if not self.queue:
            self.queue = RabbitMQIngestQueue(max_retries=self.max_retries)
            await self.queue.connect()
    
    async def process_job(self, job: IngestionJobMessage) -> Dict[str, Any]:
        """Process a single job according to specification FASE D.
        
        Implements the exact algorithm:
        1. Check idempotence in SQLite
        2. Execute if needed
        3. Update SQLite
        4. Return result
        
        Args:
            job: Job to process
            
        Returns:
            Dictionary with processing result
        """
        log.debug("Worker %s processing job %s (phase=%s, file=%s)",
                 self.worker_name, job.job_id, job.phase.value, job.file_path)
        
        # Step 1: Check idempotency
        decision = self.state_repository.try_claim(job)
        
        if decision.skip:
            log.debug("Skipping job %s: %s", job.job_id, decision.reason)
            return {
                "success": True,
                "skipped": True,
                "reason": decision.reason,
                "job_id": job.job_id
            }
        
        if decision.retry:
            log.info("Retrying job %s: %s", job.job_id, decision.reason)
        
        try:
            # Step 2: Execute work according to the phase
            result = await self._execute_phase(job)
            
            if result.get("success", False):
                # Step 3: Mark as DONE in SQLite
                metrics = result.get("metrics", {})
                self.state_repository.mark_done(job, metrics)
                
                log.debug("Job %s completed successfully", job.job_id)
                return {
                    "success": True,
                    "job_id": job.job_id,
                    "metrics": metrics
                }
            else:
                # Step 3: Mark as FAILED in SQLite
                error = result.get("error", "Unknown error")
                retryable = result.get("retryable", True)
                self.state_repository.mark_failed(job, error, retryable)
                
                log.warning("Job %s failed: %s", job.job_id, error)
                return {
                    "success": False,
                    "job_id": job.job_id,
                    "error": error,
                    "retryable": retryable
                }
                
        except Exception as e:
            # Handle unexpected errors
            error_msg = f"Unexpected error processing job {job.job_id}: {str(e)}"
            log.error(error_msg, exc_info=True)
            
            self.state_repository.mark_failed(job, error_msg, retryable=True)
            
            return {
                "success": False,
                "job_id": job.job_id,
                "error": error_msg,
                "retryable": True
            }
    
    async def _execute_phase(self, job: IngestionJobMessage) -> Dict[str, Any]:
        """Execute the actual work for a job phase.
        
        This is a placeholder implementation. In a real system, this would:
        - For EXTRACT: Load and convert document to text
        - For CHUNK: Split text into chunks
        - For EMBED: Generate embeddings
        - For UPSERT: Insert into vector store
        
        Args:
            job: Job to execute
            
        Returns:
            Dictionary with execution result
        """
        # TODO: Implement actual phase execution
        # This should integrate with your existing pipeline components
        
        log.info("Executing phase %s for file %s", job.phase.value, job.file_path)
        
        # Simulate work
        await asyncio.sleep(0.1)
        
        # Return success for now
        return {
            "success": True,
            "metrics": {
                "phase": job.phase.value,
                "file": job.file_path,
                "duration_ms": 100
            }
        }
    
    async def _job_callback(self, job: IngestionJobMessage, gate_result: Dict[str, Any]) -> Dict[str, Any]:
        """Callback for RabbitMQ queue processing.
        
        This adapts the RabbitMQIngestQueue callback interface to our process_job method.
        
        Args:
            job: Job from RabbitMQ
            gate_result: Idempotence gate result from queue
            
        Returns:
            Dictionary with processing result
        """
        # We already handle idempotence in process_job, so ignore gate_result
        return await self.process_job(job)
    
    async def run(
        self,
        concurrency: int = 4,
        prefetch: int = 10
    ) -> None:
        """Start consuming and processing jobs.
        
        Args:
            concurrency: Number of concurrent workers
            prefetch: Prefetch count for RabbitMQ
        """
        await self.connect_queue()
        
        self.running = True
        log.info("Worker %s started with concurrency=%d, prefetch=%d",
                 self.worker_name, concurrency, prefetch)
        
        try:
            # Start processing jobs from RabbitMQ
            await self.queue.process_jobs(
                worker_name=self.worker_name,
                callback=self._job_callback,
                batch_size=concurrency
            )
            
        except asyncio.CancelledError:
            log.info("Worker %s cancelled", self.worker_name)
            self.running = False
            raise
            
        except Exception as e:
            log.error("Worker %s stopped with error: %s", self.worker_name, e)
            self.running = False
            raise
            
        finally:
            self.running = False
            log.info("Worker %s stopped", self.worker_name)
    
    async def stop(self) -> None:
        """Stop the worker."""
        self.running = False
        log.info("Worker %s stopping...", self.worker_name)
    
    def get_status(self) -> Dict[str, Any]:
        """Get worker status.
        
        Returns:
            Dictionary with worker status
        """
        return {
            "worker_name": self.worker_name,
            "running": self.running,
            "max_retries": self.max_retries
        }


async def start_worker_cluster(
    worker_count: int = 1,
    concurrency_per_worker: int = 4,
    max_retries: int = 3
) -> None:
    """Start a cluster of ingestion workers.
    
    Args:
        worker_count: Number of workers to start
        concurrency_per_worker: Concurrency per worker
        max_retries: Maximum retry attempts
    """
    workers = []
    
    log.info("Starting worker cluster with %d workers", worker_count)
    
    try:
        # Create and start workers
        for i in range(worker_count):
            worker = IngestionWorker(
                worker_name=f"worker_{i+1}",
                max_retries=max_retries
            )
            workers.append(worker)
        
        # Start all workers
        tasks = [
            asyncio.create_task(worker.run(concurrency=concurrency_per_worker))
            for worker in workers
        ]
        
        # Wait for all workers to complete (they shouldn't unless there's an error)
        await asyncio.gather(*tasks)
        
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received, stopping workers...")
        
    except Exception as e:
        log.error("Error in worker cluster: %s", e)
        
    finally:
        # Stop all workers
        for worker in workers:
            try:
                await worker.stop()
            except:
                pass
        
        log.info("Worker cluster stopped")
