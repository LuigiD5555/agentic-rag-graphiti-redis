"""Job message models for RabbitMQ ingestion."""

import json
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any


class IngestionPhase(Enum):
    """Ingestion processing phases."""
    EXTRACT = "EXTRACT"
    CHUNK = "CHUNK"
    EMBED = "EMBED"
    UPSERT = "UPSERT"
    FINALIZE = "FINALIZE"


@dataclass
class IngestionJobMessage:
    """Represents an ingestion job message for RabbitMQ.
    
    This is the canonical contract that must be used by both Planner and Worker.
    """
    job_id: str
    phase: IngestionPhase
    run_id: str
    file_path: str
    fingerprint: str  # Hash of file content + metadata
    attempt: int = 0
    created_at: float = 0.0
    options: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    chunk_id: Optional[str] = None
    
    def __post_init__(self):
        """Set default values after initialization."""
        if self.created_at == 0.0:
            self.created_at = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for serialization."""
        data = {
            "job_id": self.job_id,
            "phase": self.phase.value,
            "run_id": self.run_id,
            "file_path": self.file_path,
            "fingerprint": self.fingerprint,
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
    def from_dict(cls, data: Dict[str, Any]) -> "IngestionJobMessage":
        """Create job from dictionary."""
        options = json.loads(data.get("options", "{}")) if data.get("options") else None
        metadata = json.loads(data.get("metadata", "{}")) if data.get("metadata") else None
        
        return cls(
            job_id=data["job_id"],
            phase=IngestionPhase(data["phase"]),
            run_id=data["run_id"],
            file_path=data["file_path"],
            fingerprint=data["fingerprint"],
            chunk_id=data.get("chunk_id"),
            attempt=int(data.get("attempt", 0)),
            options=options,
            created_at=float(data.get("created_at", 0.0)),
            metadata=metadata
        )
    
    @classmethod
    def create(
        cls,
        phase: IngestionPhase,
        run_id: str,
        file_path: str,
        fingerprint: str,
        options: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        chunk_id: Optional[str] = None
    ) -> "IngestionJobMessage":
        """Create a new job with generated ID."""
        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        return cls(
            job_id=job_id,
            phase=phase,
            run_id=run_id,
            file_path=file_path,
            fingerprint=fingerprint,
            attempt=0,
            created_at=time.time(),
            options=options,
            metadata=metadata,
            chunk_id=chunk_id
        )


@dataclass
class ProcessingDecision:
    """Result of idempotence check."""
    should_process: bool
    reason: str
    skip: bool = False
    retry: bool = False
    
    @classmethod
    def skip_reason(cls, reason: str) -> "ProcessingDecision":
        """Create a skip decision."""
        return cls(should_process=False, reason=reason, skip=True)
    
    @classmethod
    def retry_reason(cls, reason: str) -> "ProcessingDecision":
        """Create a retry decision."""
        return cls(should_process=True, reason=reason, retry=True)
    
    @classmethod
    def process(cls, reason: str = "new_job") -> "ProcessingDecision":
        """Create a process decision."""
        return cls(should_process=True, reason=reason)