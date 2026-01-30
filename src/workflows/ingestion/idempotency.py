"""
Idempotency Hardening - Phase 6 of the optimization plan

Implements robust idempotency mechanisms for safe retries
and to avoid duplicate work after failures.
"""

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Callable
from enum import Enum

from src import logger
from src.workflows.query.audit.decorators import logged, timed


class ProcessingStage(Enum):
    """Processing stages for a file."""
    DISCOVERED = "discovered"
    PREPROCESSED = "preprocessed"
    SPLIT = "split"
    EMBEDDED = "embedded"
    UPSERTED = "upserted"
    FAILED = "failed"


@dataclass
class FileProcessingState:
    """Processing state for a file."""
    file_path: str
    file_hash: str
    stages: Dict[ProcessingStage, Dict[str, Any]]
    last_updated: datetime
    completed: bool = False
    error: Optional[str] = None


class IdempotencyManager:
    """Idempotency manager for the ingestion pipeline."""
    
    def __init__(
        self,
        storage_backend: Optional[Any] = None,
        ttl_seconds: int = 86400,  # 24 horas
        workers: int = 4
    ):
        """
        Args:
            storage_backend: Storage backend (SQLite, file, etc.)
            ttl_seconds: TTL for states in seconds
            workers: Workers for parallel operations
        """
        self.storage_backend = storage_backend
        self.ttl_seconds = ttl_seconds
        self.workers = workers
        
        # In-memory cache for quick access
        self._memory_cache: Dict[str, FileProcessingState] = {}
        self._lock = threading.Lock()
        
        # Metrics
        self._hits = 0
        self._misses = 0
        self._skipped_work = 0
        
        logger.info(
            "IdempotencyManager initialized: TTL=%ds, workers=%d",
            ttl_seconds, workers
        )
    
    def compute_file_hash(self, file_path: str, chunk_size: int = 8192) -> str:
        """
        Computes a deterministic hash for a file.
        
        Args:
            file_path: Path to the file
            chunk_size: Chunk size for reading
            
        Returns:
            SHA256 hash of the file
        """
        try:
            hasher = hashlib.sha256()
            path = Path(file_path)
            
            if not path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            
            # Include metadata in the hash
            stat = path.stat()
            metadata = f"{path.name}:{stat.st_size}:{stat.st_mtime}"
            hasher.update(metadata.encode('utf-8'))
            
            # Include file contents
            with open(file_path, 'rb') as f:
                while chunk := f.read(chunk_size):
                    hasher.update(chunk)
            
            return hasher.hexdigest()
            
        except Exception as e:
            logger.error("Error calculating hash for %s: %s", file_path, e)
            # Fallback: hash based on path and timestamp
            fallback = f"{file_path}:{time.time()}"
            return hashlib.sha256(fallback.encode('utf-8')).hexdigest()
    
    def get_file_state(self, file_path: str) -> Optional[FileProcessingState]:
        """
        Retrieves the processing state of a file.
        
        Returns:
            FileProcessingState if found, None otherwise
        """
        file_hash = self.compute_file_hash(file_path)
        
        # First check in-memory cache
        with self._lock:
            cache_key = f"{file_path}:{file_hash}"
            if cache_key in self._memory_cache:
                self._hits += 1
                return self._memory_cache[cache_key]
        
        self._misses += 1
        
        # If a backend exists, try loading from it
        if self.storage_backend:
            try:
                state_data = self._load_from_backend(file_path, file_hash)
                if state_data:
                    state = self._deserialize_state(state_data)
                    with self._lock:
                        self._memory_cache[cache_key] = state
                    return state
            except Exception as e:
                logger.warning("Error loading state from backend: %s", e)
        
        return None
    
    def mark_stage_completed(
        self,
        file_path: str,
        stage: ProcessingStage,
        metadata: Optional[Dict[str, Any]] = None,
        force: bool = False
    ) -> bool:
        """
        Marks a stage as completed for a file.
        
        Args:
            file_path: Path to the file
            stage: Completed stage
            metadata: Additional metadata for the stage
            force: Force update even if already completed
            
        Returns:
            True if the state was updated, False if already completed
        """
        file_hash = self.compute_file_hash(file_path)
        cache_key = f"{file_path}:{file_hash}"
        
        with self._lock:
            # Obtain or create the state
            if cache_key in self._memory_cache:
                state = self._memory_cache[cache_key]
            else:
                state = FileProcessingState(
                    file_path=file_path,
                    file_hash=file_hash,
                    stages={},
                    last_updated=datetime.now(timezone.utc)
                )
            
            # Check if already completed
            if stage in state.stages and not force:
                logger.debug(
                    "Stage %s already completed for %s (idempotency)",
                    stage.value, file_path
                )
                self._skipped_work += 1
                return False
            
            # Update state
            state.stages[stage] = {
                'completed_at': datetime.now(timezone.utc).isoformat(),
                'metadata': metadata or {}
            }
            state.last_updated = datetime.now(timezone.utc)
            
            # Mark as completed if all stages are done
            if self._all_stages_completed(state):
                state.completed = True
            
            # Store in cache
            self._memory_cache[cache_key] = state
            
            # Save to backend if available
            if self.storage_backend:
                try:
                    self._save_to_backend(state)
                except Exception as e:
                    logger.warning("Error saving state to backend: %s", e)
        
        logger.debug(
            "Stage %s marked as completed for %s",
            stage.value, file_path
        )
        
        return True
    
    def mark_stage_failed(
        self,
        file_path: str,
        stage: ProcessingStage,
        error: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Marks a stage as failed."""
        file_hash = self.compute_file_hash(file_path)
        cache_key = f"{file_path}:{file_hash}"
        
        with self._lock:
            # Obtain or create the state
            if cache_key in self._memory_cache:
                state = self._memory_cache[cache_key]
            else:
                state = FileProcessingState(
                    file_path=file_path,
                    file_hash=file_hash,
                    stages={},
                    last_updated=datetime.now(timezone.utc)
                )
            
            # Mark as failed
            state.stages[ProcessingStage.FAILED] = {
                'failed_at': datetime.now(timezone.utc).isoformat(),
                'stage': stage.value,
                'error': error,
                'metadata': metadata or {}
            }
            state.error = error
            state.last_updated = datetime.now(timezone.utc)
            
            # Store state
            self._memory_cache[cache_key] = state
           
            if self.storage_backend:
                try:
                    self._save_to_backend(state)
                except Exception as e:
                    logger.warning("Error saving failed state: %s", e)
        
        logger.warning(
            "Stage %s marked as failed for %s: %s",
            stage.value, file_path, error
        )
    
    def should_skip_file(self, file_path: str) -> tuple[bool, Optional[str]]:
        """
        Determines whether a file should be skipped.
        
        Returns:
            Tuple (should_skip, reason)
        """
        state = self.get_file_state(file_path)
        
        if not state:
            return False, None
        
        # If already fully processed
        if state.completed:
            return True, "already_fully_processed"
        
        # If it failed recently (less than 1 hour)
        if ProcessingStage.FAILED in state.stages:
            failed_data = state.stages[ProcessingStage.FAILED]
            failed_at = datetime.fromisoformat(failed_data['failed_at'])
            age = (datetime.now(timezone.utc) - failed_at).total_seconds()
            
            if age < 3600:  # 1 hora
                return True, f"recent_failure: {state.error}"
        
        return False, None
    
    def get_next_stage(self, file_path: str) -> Optional[ProcessingStage]:
        """
        """
        Determines the next stage to process for a file.
        
        Returns:
            Next stage, or None if already complete
        """
        state = self.get_file_state(file_path)
        
        if not state:
            return ProcessingStage.DISCOVERED
        
        if state.completed:
            return None
        
        # Determine the last completed stage
        completed_stages = set(state.stages.keys())
        
        # Processing order
        stage_order = [
            ProcessingStage.DISCOVERED,
            ProcessingStage.PREPROCESSED,
            ProcessingStage.SPLIT,
            ProcessingStage.EMBEDDED,
            ProcessingStage.UPSERTED
        ]
        
        for stage in stage_order:
            if stage not in completed_stages:
                return stage
        
        return None
    
    def batch_check_states(
        self,
        file_paths: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """
        """
        Checks states for multiple files in batch.
        
        Returns:
            Dict with the state of each file
        """
        results = {}
        
        for file_path in file_paths:
            state = self.get_file_state(file_path)
            
            if state:
                results[file_path] = {
                    'completed': state.completed,
                    'last_stage': max(state.stages.keys(), key=lambda s: s.value) 
                                if state.stages else None,
                    'error': state.error,
                    'last_updated': state.last_updated.isoformat()
                }
            else:
                results[file_path] = {
                    'completed': False,
                    'last_stage': None,
                    'error': None,
                    'last_updated': None
                }
        
        return results
    
    def cleanup_old_states(self, max_age_seconds: Optional[int] = None) -> int:
        """
        """
        Cleans up old states.
        
        Args:
            max_age_seconds: Maximum age in seconds (None = use TTL)
            
        Returns:
            Number of states cleaned
        """
        age_limit = max_age_seconds or self.ttl_seconds
        cutoff = datetime.now(timezone.utc).timestamp() - age_limit
        
        cleaned = 0
        
        with self._lock:
            # Clean in-memory cache
            keys_to_remove = []
            for key, state in self._memory_cache.items():
                if state.last_updated.timestamp() < cutoff:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self._memory_cache[key]
                cleaned += 1
            
            # Clean backend if available
            if self.storage_backend:
                try:
                    backend_cleaned = self._cleanup_backend(cutoff)
                    cleaned += backend_cleaned
                except Exception as e:
                    logger.warning("Error limpiando backend: %s", e)
        
        if cleaned > 0:
            logger.info("Removed %d old states", cleaned)
        
        return cleaned
    
    def get_metrics(self) -> Dict[str, Any]:
        """Returns metrics from the idempotency manager."""
        with self._lock:
            cache_size = len(self._memory_cache)
            
            completed = sum(1 for s in self._memory_cache.values() if s.completed)
            failed = sum(1 for s in self._memory_cache.values() if s.error)
            
            return {
                'cache_size': cache_size,
                'hits': self._hits,
                'misses': self._misses,
                'hit_ratio': self._hits / (self._hits + self._misses) 
                           if (self._hits + self._misses) > 0 else 0.0,
                'skipped_work': self._skipped_work,
                'completed_files': completed,
                'failed_files': failed,
                'in_progress': cache_size - completed - failed
            }
    
    def _all_stages_completed(self, state: FileProcessingState) -> bool:
        """Checks if all stages are completed."""
        required_stages = {
            ProcessingStage.DISCOVERED,
            ProcessingStage.PREPROCESSED,
            ProcessingStage.SPLIT,
            ProcessingStage.EMBEDDED,
            ProcessingStage.UPSERTED
        }
        
        return required_stages.issubset(set(state.stages.keys()))
    
    def _serialize_state(self, state: FileProcessingState) -> Dict[str, Any]:
        """Serializes state for storage."""
        return {
            'file_path': state.file_path,
            'file_hash': state.file_hash,
            'stages': {
                stage.value: data 
                for stage, data in state.stages.items()
            },
            'last_updated': state.last_updated.isoformat(),
            'completed': state.completed,
            'error': state.error
        }
    
    def _deserialize_state(self, data: Dict[str, Any]) -> FileProcessingState:
        """Deserializes state from storage."""
        stages = {}
        for stage_str, stage_data in data.get('stages', {}).items():
            try:
                stage = ProcessingStage(stage_str)
                stages[stage] = stage_data
            except ValueError:
                logger.warning("Unknown stage in serialized data: %s", stage_str)
        
        return FileProcessingState(
            file_path=data['file_path'],
            file_hash=data['file_hash'],
            stages=stages,
            last_updated=datetime.fromisoformat(data['last_updated']),
            completed=data.get('completed', False),
            error=data.get('error')
        )
    
    def _save_to_backend(self, state: FileProcessingState) -> None:
        """Saves state to the backend (basic implementation)."""
        if hasattr(self.storage_backend, 'set'):
            # Cache-like interface
            key = f"idempotency:{state.file_hash}"
            value = json.dumps(self._serialize_state(state))
            self.storage_backend.set(key, value, ex=self.ttl_seconds)
        else:
            # Fallback: guardar en archivo
            cache_dir = Path("/tmp/rag-idempotency")
            cache_dir.mkdir(exist_ok=True)
            
            cache_file = cache_dir / f"{state.file_hash}.json"
            with open(cache_file, 'w') as f:
                json.dump(self._serialize_state(state), f)
    
    def _load_from_backend(self, file_path: str, file_hash: str) -> Optional[Dict[str, Any]]:
        """Loads state from the backend."""
        if hasattr(self.storage_backend, 'get'):
            # Cache-like interface
            key = f"idempotency:{file_hash}"
            value = self.storage_backend.get(key)
            if value:
                return json.loads(value)
        else:
            # Fallback: cargar desde archivo
            cache_dir = Path("/tmp/rag-idempotency")
            cache_file = cache_dir / f"{file_hash}.json"
            
            if cache_file.exists():
                with open(cache_file, 'r') as f:
                    return json.load(f)
        
        return None
    
    def _cleanup_backend(self, cutoff_timestamp: float) -> int:
        """Cleans up old states from the backend."""
        cleaned = 0
        
        if hasattr(self.storage_backend, 'scan_iter'):
            # Cache-like interface
            for key in self.storage_backend.scan_iter("idempotency:*"):
                try:
                    value = self.storage_backend.get(key)
                    if value:
                        data = json.loads(value)
                        last_updated = datetime.fromisoformat(data['last_updated']).timestamp()
                        
                        if last_updated < cutoff_timestamp:
                            self.storage_backend.delete(key)
                            cleaned += 1
                except Exception as e:
                    logger.warning("Error cleaning key %s: %s", key, e)
        
        return cleaned


# Decorators for idempotency
def idempotent_stage(stage: ProcessingStage):
    """
    Decorator to make a stage function idempotent.
    
    Usage:
        @idempotent_stage(ProcessingStage.PREPROCESSED)
        def preprocess_file(idempotency_manager: IdempotencyManager, file_path: str) -> Dict[str, Any]:
            # ... processing ...
            return {'result': 'data'}
    """
    def decorator(func: Callable):
        def wrapper(idempotency_manager: IdempotencyManager, file_path: str, *args, **kwargs):
            # Check if already completed
            if not idempotency_manager.mark_stage_completed(file_path, stage):
                logger.debug(
                    "Skipping stage %s for %s (already completed)",
                    stage.value, file_path
                )
                return {'skipped': True, 'stage': stage.value}
            
            try:
                # Execute function
                result = func(idempotency_manager, file_path, *args, **kwargs)
                
                # Record metadata
                metadata = {
                    'result_type': type(result).__name__,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                
                # Update state with metadata
                idempotency_manager.mark_stage_completed(
                    file_path, stage, metadata=metadata, force=True
                )
                
                return result
                
            except Exception as e:
                # Mark as failed
                idempotency_manager.mark_stage_failed(
                    file_path, stage, str(e)
                )
                raise
        
        return wrapper
    
    return decorator


# Utilities for integration
def create_default_idempotency_manager(config: Optional[Any] = None) -> IdempotencyManager:
    """Creates an IdempotencyManager with default configuration."""
    import os
    
    # External cache removed: always use in-memory backend
    storage_backend = None
    logger.info("IdempotencyManager using in-memory cache (SQLite control plane)")
    
    ttl = int(os.getenv('IDEMPOTENCY_TTL_SECONDS', '86400'))
    workers = int(os.getenv('IDEMPOTENCY_WORKERS', '4'))
    
    return IdempotencyManager(
        storage_backend=storage_backend,
        ttl_seconds=ttl,
        workers=workers
    )
