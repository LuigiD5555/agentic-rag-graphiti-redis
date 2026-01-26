"""Ingestion planner that creates and publishes jobs to RabbitMQ."""

import os
import hashlib
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from src.workflows.ingestion.jobs.models import IngestionJobMessage, IngestionPhase
from src.workflows.ingestion.state.job_state_repository import JobStateRepository
from src.workflows.ingestion.rabbitmq_queue import RabbitMQIngestQueue
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


@dataclass
class PublishReport:
    """Report of job publishing results."""
    total_jobs: int
    successful: int
    failed: int
    job_ids: List[str]
    phases: Dict[str, int]


class IngestionPlanner:
    """Planner that creates jobs and publishes them to RabbitMQ.
    
    Follows specification: Planner decides WHAT to do, publishes to RabbitMQ, does NOT execute.
    """
    
    def __init__(self, state_repository: Optional[JobStateRepository] = None):
        """Initialize ingestion planner.
        
        Args:
            state_repository: Optional job state repository (creates new if not provided)
        """
        self.state_repository = state_repository or JobStateRepository()
        self.queue = None
    
    async def connect_queue(self) -> None:
        """Connect to RabbitMQ queue."""
        if not self.queue:
            self.queue = RabbitMQIngestQueue()
            await self.queue.connect()
    
    def calculate_fingerprint(self, file_path: str, size: int, mtime: float) -> str:
        """Calculate fingerprint for a file.
        
        Args:
            file_path: File path
            size: File size in bytes
            mtime: File modification time
            
        Returns:
            Fingerprint string (hash of path + size + mtime)
        """
        # For now, use a simple hash of path + size + mtime
        # In production, you might want to include content hash
        content = f"{file_path}:{size}:{mtime}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def plan_jobs(
        self,
        file_paths: List[str],
        run_id: str,
        options: Optional[Dict[str, Any]] = None
    ) -> List[IngestionJobMessage]:
        """Plan jobs for file paths.
        
        Args:
            file_paths: List of file paths to process
            run_id: Ingestion run identifier
            options: Optional processing options
            
        Returns:
            List of job messages to publish
        """
        jobs = []
        
        for file_path in file_paths:
            try:
                # Get file metadata
                stat = os.stat(file_path)
                size = stat.st_size
                mtime = stat.st_mtime
                
                # Calculate fingerprint
                fingerprint = self.calculate_fingerprint(file_path, size, mtime)
                
                # Update file metadata in SQLite
                self.state_repository.update_file_metadata(file_path, fingerprint, size, int(mtime))
                
                # Create jobs for each phase
                # Note: In a real implementation, you might want to check which phases are needed
                phases = [
                    IngestionPhase.EXTRACT,
                    IngestionPhase.CHUNK,
                    IngestionPhase.EMBED,
                    IngestionPhase.UPSERT
                ]
                
                for phase in phases:
                    job = IngestionJobMessage.create(
                        phase=phase,
                        run_id=run_id,
                        file_path=file_path,
                        fingerprint=fingerprint,
                        options=options
                    )
                    jobs.append(job)
                
                log.debug("Planned %d jobs for file: %s", len(phases), file_path)
                
            except Exception as e:
                log.error("Error planning jobs for file %s: %s", file_path, e)
                continue
        
        log.info("Planned %d total jobs for %d files", len(jobs), len(file_paths))
        return jobs
    
    async def publish_jobs(self, jobs: List[IngestionJobMessage]) -> PublishReport:
        """Publish jobs to RabbitMQ.
        
        Args:
            jobs: List of job messages to publish
            
        Returns:
            PublishReport with results
        """
        await self.connect_queue()
        
        successful = 0
        failed = 0
        job_ids = []
        phases = {}
        
        for job in jobs:
            try:
                # Publish job to RabbitMQ
                job_id = await self.queue.enqueue_job(
                    phase=job.phase,
                    run_id=job.run_id,
                    file_path=job.file_path,
                    chunk_id=job.chunk_id,
                    options=job.options,
                    metadata=job.metadata
                )
                
                successful += 1
                job_ids.append(job_id)
                
                # Track phases
                phase_name = job.phase.value
                phases[phase_name] = phases.get(phase_name, 0) + 1
                
                log.debug("Published job %s for %s phase", job_id, phase_name)
                
            except Exception as e:
                failed += 1
                log.error("Failed to publish job for file %s: %s", job.file_path, e)
        
        report = PublishReport(
            total_jobs=len(jobs),
            successful=successful,
            failed=failed,
            job_ids=job_ids,
            phases=phases
        )
        
        log.info("Published %d/%d jobs successfully (failed: %d)", 
                 successful, len(jobs), failed)
        
        return report
    
    async def plan_and_publish(
        self,
        file_paths: List[str],
        run_id: str,
        options: Optional[Dict[str, Any]] = None
    ) -> PublishReport:
        """Plan and publish jobs in one operation.
        
        Args:
            file_paths: List of file paths to process
            run_id: Ingestion run identifier
            options: Optional processing options
            
        Returns:
            PublishReport with results
        """
        # Create run record in SQLite
        self.state_repository.create_run(run_id)
        
        # Plan jobs
        jobs = self.plan_jobs(file_paths, run_id, options)
        
        if not jobs:
            log.warning("No jobs planned for run %s", run_id)
            return PublishReport(
                total_jobs=0,
                successful=0,
                failed=0,
                job_ids=[],
                phases={}
            )
        
        # Publish jobs
        report = await self.publish_jobs(jobs)
        
        return report
    
    def get_file_status(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get status of a file across all phases.
        
        Args:
            file_path: File path
            
        Returns:
            Dictionary with file status or None if not found
        """
        # Get latest fingerprint
        metadata = self.state_repository.get_file_metadata(file_path)
        if not metadata:
            return None
        
        fingerprint = metadata["fingerprint"]
        
        # Get status for each phase
        status_by_phase = {}
        for phase in IngestionPhase:
            status = self.state_repository.get_status(file_path, phase.value, fingerprint)
            if status:
                status_by_phase[phase.value] = status
        
        if not status_by_phase:
            return None
        
        return {
            "file_path": file_path,
            "fingerprint": fingerprint,
            "metadata": metadata,
            "phases": status_by_phase
        }