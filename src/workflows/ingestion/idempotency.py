"""
Idempotency Hardening - Fase 6 del plan de optimización

Implementa mecanismos robustos de idempotencia para hacer reintentos seguros
y evitar trabajo duplicado después de fallos.
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
    """Etapas del procesamiento de un archivo."""
    DISCOVERED = "discovered"
    PREPROCESSED = "preprocessed"
    SPLIT = "split"
    EMBEDDED = "embedded"
    UPSERTED = "upserted"
    FAILED = "failed"


@dataclass
class FileProcessingState:
    """Estado de procesamiento de un archivo."""
    file_path: str
    file_hash: str
    stages: Dict[ProcessingStage, Dict[str, Any]]
    last_updated: datetime
    completed: bool = False
    error: Optional[str] = None


class IdempotencyManager:
    """Gestor de idempotencia para el pipeline de ingestión."""
    
    def __init__(
        self,
        storage_backend: Optional[Any] = None,
        ttl_seconds: int = 86400,  # 24 horas
        workers: int = 4
    ):
        """
        Args:
            storage_backend: Backend de almacenamiento (SQLite, archivo, etc.)
            ttl_seconds: TTL para estados en segundos
            workers: Workers para operaciones paralelas
        """
        self.storage_backend = storage_backend
        self.ttl_seconds = ttl_seconds
        self.workers = workers
        
        # Cache en memoria para acceso rápido
        self._memory_cache: Dict[str, FileProcessingState] = {}
        self._lock = threading.Lock()
        
        # Métricas
        self._hits = 0
        self._misses = 0
        self._skipped_work = 0
        
        logger.info(
            "IdempotencyManager inicializado: TTL=%ds, workers=%d",
            ttl_seconds, workers
        )
    
    def compute_file_hash(self, file_path: str, chunk_size: int = 8192) -> str:
        """
        Calcula hash determinístico de un archivo.
        
        Args:
            file_path: Ruta del archivo
            chunk_size: Tamaño de chunk para lectura
            
        Returns:
            Hash SHA256 del archivo
        """
        try:
            hasher = hashlib.sha256()
            path = Path(file_path)
            
            if not path.exists():
                raise FileNotFoundError(f"Archivo no encontrado: {file_path}")
            
            # Incluir metadatos en el hash
            stat = path.stat()
            metadata = f"{path.name}:{stat.st_size}:{stat.st_mtime}"
            hasher.update(metadata.encode('utf-8'))
            
            # Incluir contenido del archivo
            with open(file_path, 'rb') as f:
                while chunk := f.read(chunk_size):
                    hasher.update(chunk)
            
            return hasher.hexdigest()
            
        except Exception as e:
            logger.error("Error calculando hash de %s: %s", file_path, e)
            # Fallback: hash basado en ruta y timestamp
            fallback = f"{file_path}:{time.time()}"
            return hashlib.sha256(fallback.encode('utf-8')).hexdigest()
    
    def get_file_state(self, file_path: str) -> Optional[FileProcessingState]:
        """
        Obtiene el estado de procesamiento de un archivo.
        
        Returns:
            FileProcessingState si existe, None si no
        """
        file_hash = self.compute_file_hash(file_path)
        
        # Primero verificar cache en memoria
        with self._lock:
            cache_key = f"{file_path}:{file_hash}"
            if cache_key in self._memory_cache:
                self._hits += 1
                return self._memory_cache[cache_key]
        
        self._misses += 1
        
        # Si hay backend, buscar allí
        if self.storage_backend:
            try:
                state_data = self._load_from_backend(file_path, file_hash)
                if state_data:
                    state = self._deserialize_state(state_data)
                    with self._lock:
                        self._memory_cache[cache_key] = state
                    return state
            except Exception as e:
                logger.warning("Error cargando estado desde backend: %s", e)
        
        return None
    
    def mark_stage_completed(
        self,
        file_path: str,
        stage: ProcessingStage,
        metadata: Optional[Dict[str, Any]] = None,
        force: bool = False
    ) -> bool:
        """
        Marca una etapa como completada para un archivo.
        
        Args:
            file_path: Ruta del archivo
            stage: Etapa completada
            metadata: Metadatos adicionales de la etapa
            force: Forzar actualización incluso si ya está completada
            
        Returns:
            True si se actualizó el estado, False si ya estaba completado
        """
        file_hash = self.compute_file_hash(file_path)
        cache_key = f"{file_path}:{file_hash}"
        
        with self._lock:
            # Obtener o crear estado
            if cache_key in self._memory_cache:
                state = self._memory_cache[cache_key]
            else:
                state = FileProcessingState(
                    file_path=file_path,
                    file_hash=file_hash,
                    stages={},
                    last_updated=datetime.now(timezone.utc)
                )
            
            # Verificar si ya está completado
            if stage in state.stages and not force:
                logger.debug(
                    "Etapa %s ya completada para %s (idempotencia)",
                    stage.value, file_path
                )
                self._skipped_work += 1
                return False
            
            # Actualizar estado
            state.stages[stage] = {
                'completed_at': datetime.now(timezone.utc).isoformat(),
                'metadata': metadata or {}
            }
            state.last_updated = datetime.now(timezone.utc)
            
            # Marcar como completado si todas las etapas están hechas
            if self._all_stages_completed(state):
                state.completed = True
            
            # Guardar en cache
            self._memory_cache[cache_key] = state
            
            # Guardar en backend si existe
            if self.storage_backend:
                try:
                    self._save_to_backend(state)
                except Exception as e:
                    logger.warning("Error guardando estado en backend: %s", e)
        
        logger.debug(
            "Etapa %s marcada como completada para %s",
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
        """Marca una etapa como fallida."""
        file_hash = self.compute_file_hash(file_path)
        cache_key = f"{file_path}:{file_hash}"
        
        with self._lock:
            # Obtener o crear estado
            if cache_key in self._memory_cache:
                state = self._memory_cache[cache_key]
            else:
                state = FileProcessingState(
                    file_path=file_path,
                    file_hash=file_hash,
                    stages={},
                    last_updated=datetime.now(timezone.utc)
                )
            
            # Marcar como fallido
            state.stages[ProcessingStage.FAILED] = {
                'failed_at': datetime.now(timezone.utc).isoformat(),
                'stage': stage.value,
                'error': error,
                'metadata': metadata or {}
            }
            state.error = error
            state.last_updated = datetime.now(timezone.utc)
            
            # Guardar
            self._memory_cache[cache_key] = state
            
            if self.storage_backend:
                try:
                    self._save_to_backend(state)
                except Exception as e:
                    logger.warning("Error guardando estado fallido: %s", e)
        
        logger.warning(
            "Etapa %s marcada como fallida para %s: %s",
            stage.value, file_path, error
        )
    
    def should_skip_file(self, file_path: str) -> tuple[bool, Optional[str]]:
        """
        Determina si un archivo debe ser saltado.
        
        Returns:
            Tuple (should_skip, reason)
        """
        state = self.get_file_state(file_path)
        
        if not state:
            return False, None
        
        # Si ya está completamente procesado
        if state.completed:
            return True, "already_fully_processed"
        
        # Si falló recientemente (menos de 1 hora)
        if ProcessingStage.FAILED in state.stages:
            failed_data = state.stages[ProcessingStage.FAILED]
            failed_at = datetime.fromisoformat(failed_data['failed_at'])
            age = (datetime.now(timezone.utc) - failed_at).total_seconds()
            
            if age < 3600:  # 1 hora
                return True, f"recent_failure: {state.error}"
        
        return False, None
    
    def get_next_stage(self, file_path: str) -> Optional[ProcessingStage]:
        """
        Obtiene la siguiente etapa a procesar para un archivo.
        
        Returns:
            Siguiente etapa, o None si ya está completo
        """
        state = self.get_file_state(file_path)
        
        if not state:
            return ProcessingStage.DISCOVERED
        
        if state.completed:
            return None
        
        # Determinar última etapa completada
        completed_stages = set(state.stages.keys())
        
        # Orden de procesamiento
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
        Verifica estados de múltiples archivos en batch.
        
        Returns:
            Dict con estado de cada archivo
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
        Limpia estados antiguos.
        
        Args:
            max_age_seconds: Edad máxima en segundos (None = usar TTL)
            
        Returns:
            Número de estados limpiados
        """
        age_limit = max_age_seconds or self.ttl_seconds
        cutoff = datetime.now(timezone.utc).timestamp() - age_limit
        
        cleaned = 0
        
        with self._lock:
            # Limpiar cache en memoria
            keys_to_remove = []
            for key, state in self._memory_cache.items():
                if state.last_updated.timestamp() < cutoff:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self._memory_cache[key]
                cleaned += 1
            
            # Limpiar backend si existe
            if self.storage_backend:
                try:
                    backend_cleaned = self._cleanup_backend(cutoff)
                    cleaned += backend_cleaned
                except Exception as e:
                    logger.warning("Error limpiando backend: %s", e)
        
        if cleaned > 0:
            logger.info("Limpiados %d estados antiguos", cleaned)
        
        return cleaned
    
    def get_metrics(self) -> Dict[str, Any]:
        """Obtiene métricas del gestor de idempotencia."""
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
        """Verifica si todas las etapas están completadas."""
        required_stages = {
            ProcessingStage.DISCOVERED,
            ProcessingStage.PREPROCESSED,
            ProcessingStage.SPLIT,
            ProcessingStage.EMBEDDED,
            ProcessingStage.UPSERTED
        }
        
        return required_stages.issubset(set(state.stages.keys()))
    
    def _serialize_state(self, state: FileProcessingState) -> Dict[str, Any]:
        """Serializa estado para almacenamiento."""
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
        """Deserializa estado desde almacenamiento."""
        stages = {}
        for stage_str, stage_data in data.get('stages', {}).items():
            try:
                stage = ProcessingStage(stage_str)
                stages[stage] = stage_data
            except ValueError:
                logger.warning("Etapa desconocida en datos serializados: %s", stage_str)
        
        return FileProcessingState(
            file_path=data['file_path'],
            file_hash=data['file_hash'],
            stages=stages,
            last_updated=datetime.fromisoformat(data['last_updated']),
            completed=data.get('completed', False),
            error=data.get('error')
        )
    
    def _save_to_backend(self, state: FileProcessingState) -> None:
        """Guarda estado en backend (implementación básica)."""
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
        """Carga estado desde backend."""
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
        """Limpia estados antiguos del backend."""
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
                    logger.warning("Error limpiando clave %s: %s", key, e)
        
        return cleaned


# Decoradores para idempotencia
def idempotent_stage(stage: ProcessingStage):
    """
    Decorador para hacer una función de etapa idempotente.
    
    Uso:
        @idempotent_stage(ProcessingStage.PREPROCESSED)
        def preprocess_file(idempotency_manager: IdempotencyManager, file_path: str) -> Dict[str, Any]:
            # ... procesamiento ...
            return {'result': 'data'}
    """
    def decorator(func: Callable):
        def wrapper(idempotency_manager: IdempotencyManager, file_path: str, *args, **kwargs):
            # Verificar si ya está completado
            if not idempotency_manager.mark_stage_completed(file_path, stage):
                logger.debug(
                    "Saltando etapa %s para %s (ya completada)",
                    stage.value, file_path
                )
                return {'skipped': True, 'stage': stage.value}
            
            try:
                # Ejecutar función
                result = func(idempotency_manager, file_path, *args, **kwargs)
                
                # Registrar metadatos
                metadata = {
                    'result_type': type(result).__name__,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                
                # Actualizar estado con metadatos
                idempotency_manager.mark_stage_completed(
                    file_path, stage, metadata=metadata, force=True
                )
                
                return result
                
            except Exception as e:
                # Marcar como fallido
                idempotency_manager.mark_stage_failed(
                    file_path, stage, str(e)
                )
                raise
        
        return wrapper
    
    return decorator


# Utilidades para integración
def create_default_idempotency_manager(config: Optional[Any] = None) -> IdempotencyManager:
    """Crea un IdempotencyManager con configuración por defecto."""
    import os
    
    # External cache removed: always use in-memory backend
    storage_backend = None
    logger.info("IdempotencyManager usando cache en memoria (SQLite control plane)")
    
    ttl = int(os.getenv('IDEMPOTENCY_TTL_SECONDS', '86400'))
    workers = int(os.getenv('IDEMPOTENCY_WORKERS', '4'))
    
    return IdempotencyManager(
        storage_backend=storage_backend,
        ttl_seconds=ttl,
        workers=workers
    )
