"""
Watermark Cleanup - Phase 5 of the optimization plan

Implements watermark-based cleanup to prevent disk saturation
and safely remove intermediate artifacts.
"""

import os
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Callable
from concurrent.futures import ThreadPoolExecutor

from src import logger
from src.workflows.query.audit.decorators import logged, timed


@dataclass
class DiskUsage:
    """Disk usage information."""
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_percent: float


@dataclass
class CleanupRule:
    """Cleanup rule."""
    name: str
    pattern: str  # Glob pattern or extension
    max_age_seconds: Optional[int] = None  # None = no age limit
    min_size_bytes: Optional[int] = None  # None = no size limit
    priority: int = 1  # 1 = highest priority, 10 = lowest priority


class WatermarkCleanup:
    """Watermark-based cleanup system."""
    
    def __init__(
        self,
        staging_dir: str,
        watermark_percent: float = 70.0,
        aggressive_percent: float = 85.0,
        check_interval_seconds: int = 300,  # 5 minutos
        workers: int = 2
    ):
        """
        Args:
            staging_dir: Staging directory to monitor
            watermark_percent: Usage percent that triggers normal cleanup
            aggressive_percent: Usage percent that triggers aggressive cleanup
            check_interval_seconds: Interval between checks
            workers: Number of workers for parallel cleanup
        """
        self.staging_dir = Path(staging_dir).resolve()
        self.watermark_percent = watermark_percent
        self.aggressive_percent = aggressive_percent
        self.check_interval = check_interval_seconds
        self.workers = workers
        
        # Default cleanup rules
        self.rules = self._get_default_rules()
        
        # State
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Metrics
        self._last_check_time = 0.0
        self._cleanup_count = 0
        self._freed_bytes = 0
        self._last_usage_percent = 0.0
        
        # Create directory if missing
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(
            "WatermarkCleanup initialized for %s: watermark=%.1f%%, aggressive=%.1f%%, check=%ds",
            self.staging_dir, watermark_percent, aggressive_percent, check_interval_seconds
        )
    
    def _get_default_rules(self) -> List[CleanupRule]:
        """Returns the default cleanup rules."""
        return [
            # Temporary processing files
            CleanupRule(
                name="temp_files",
                pattern="*.tmp",
                max_age_seconds=3600,  # 1 hour
                priority=1
            ),
            CleanupRule(
                name="temp_dirs",
                pattern="*_temp",
                max_age_seconds=3600,
                priority=1
            ),
            
            # Conversion/OCR artifacts
            CleanupRule(
                name="conversion_artifacts",
                pattern="*.converted.*",
                max_age_seconds=7200,  # 2 hours
                priority=2
            ),
            CleanupRule(
                name="ocr_output",
                pattern="*.ocr.*",
                max_age_seconds=7200,
                priority=2
            ),
            
            # Preprocessed files
            CleanupRule(
                name="preprocessed_files",
                pattern="*.preprocessed.*",
                max_age_seconds=86400,  # 24 hours
                priority=3
            ),
            
            # Old logs
            CleanupRule(
                name="old_logs",
                pattern="*.log",
                max_age_seconds=604800,  # 7 days
                min_size_bytes=1024 * 1024,  # 1 MB minimum
                priority=4
            ),
            
            # Old cache
            CleanupRule(
                name="old_cache",
                pattern="*.cache",
                max_age_seconds=86400,
                priority=5
            ),
        ]
    
    def add_rule(self, rule: CleanupRule) -> None:
        """Agrega una regla de limpieza."""
        with self._lock:
            self.rules.append(rule)
            self.rules.sort(key=lambda r: r.priority)
    
    def get_disk_usage(self) -> DiskUsage:
        """Obtiene uso de disco del directorio de staging."""
        try:
            stat = shutil.disk_usage(str(self.staging_dir))
            
            return DiskUsage(
                total_bytes=stat.total,
                used_bytes=stat.used,
                free_bytes=stat.free,
                usage_percent=(stat.used / stat.total) * 100 if stat.total > 0 else 0.0
            )
        except Exception as e:
            logger.error("Error obteniendo uso de disco para %s: %s", self.staging_dir, e)
            return DiskUsage(total_bytes=0, used_bytes=0, free_bytes=0, usage_percent=0.0)
    
    def should_cleanup(self) -> tuple[bool, bool]:
        """
        Determina si se debe realizar limpieza.
        
        Returns:
            Tuple (needs_cleanup, needs_aggressive_cleanup)
        """
        usage = self.get_disk_usage()
        self._last_usage_percent = usage.usage_percent
        
        needs_cleanup = usage.usage_percent >= self.watermark_percent
        needs_aggressive = usage.usage_percent >= self.aggressive_percent
        
        return needs_cleanup, needs_aggressive
    
    @logged("Ejecutando limpieza por watermark")
    @timed()
    def run_cleanup(self, aggressive: bool = False) -> Dict[str, Any]:
        """
        Ejecuta limpieza basada en reglas.
        
        Args:
            aggressive: True para limpieza agresiva (ignora algunas restricciones)
            
        Returns:
            Resumen de la limpieza
        """
        logger.info(
            "Iniciando limpieza %s (uso actual: %.1f%%)",
            "AGRESIVA" if aggressive else "NORMAL",
            self._last_usage_percent
        )
        
        start_time = time.time()
        files_cleaned = 0
        dirs_cleaned = 0
        freed_bytes = 0
        errors = 0
        
        # Get cleanup candidates
        candidates = self._find_cleanup_candidates(aggressive)
        
        if not candidates:
        logger.info("No cleanup candidates found")
            return {
                'status': 'no_candidates',
                'files_cleaned': 0,
                'dirs_cleaned': 0,
                'freed_bytes': 0,
                'errors': 0,
                'duration_seconds': time.time() - start_time
            }
        
        logger.info("Found %d cleanup candidates", len(candidates))
        
        # Limpiar en paralelo
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = []
            for candidate in candidates:
                future = executor.submit(self._cleanup_item, candidate)
                futures.append(future)
            
            # Procesar resultados
            for future in futures:
                try:
                    result = future.result()
                    if result['success']:
                        if result['is_dir']:
                            dirs_cleaned += 1
                        else:
                            files_cleaned += 1
                        freed_bytes += result['size_bytes']
                    else:
                        errors += 1
                except Exception as e:
                    logger.error("Error procesando resultado de limpieza: %s", e)
                    errors += 1
        
        # Update metrics
        with self._lock:
            self._cleanup_count += 1
            self._freed_bytes += freed_bytes
        
        duration = time.time() - start_time
        
        logger.info(
            "Cleanup completed: %d files, %d directories, %.2f MB freed, "
            "%d errors, %.2f seconds",
            files_cleaned, dirs_cleaned, freed_bytes / (1024 * 1024),
            errors, duration
        )
        
        return {
            'status': 'completed',
            'files_cleaned': files_cleaned,
            'dirs_cleaned': dirs_cleaned,
            'freed_bytes': freed_bytes,
            'freed_mb': freed_bytes / (1024 * 1024),
            'errors': errors,
            'duration_seconds': duration,
            'aggressive': aggressive,
            'initial_usage_percent': self._last_usage_percent,
            'final_usage_percent': self.get_disk_usage().usage_percent
        }
    
    def _find_cleanup_candidates(self, aggressive: bool) -> List[Path]:
        """Finds cleanup candidates based on the rules."""
        candidates = []
        now = time.time()
        
        for rule in self.rules:
            # In aggressive mode, skip lower priority rules
            if aggressive and rule.priority > 3:
                continue  # Skip low-priority rules in aggressive mode
            
            try:
                # Look for files that match the pattern
                for item in self.staging_dir.rglob(rule.pattern):
                    if not item.exists():
                        continue
                    
                    # Verificar edad
                    if rule.max_age_seconds is not None:
                        age = now - item.stat().st_mtime
                        if age < rule.max_age_seconds and not aggressive:
                            continue
                    
                    # Check minimum size
                    if rule.min_size_bytes is not None:
                        size = item.stat().st_size if item.is_file() else 0
                        if size < rule.min_size_bytes:
                            continue
                    
                    candidates.append(item)
                    
            except Exception as e:
                logger.warning("Error aplicando regla '%s': %s", rule.name, e)
        
        # Sort by priority (age * size)
        candidates.sort(key=lambda p: (
            -(now - p.stat().st_mtime) if p.exists() else 0,  # Oldest first
            -p.stat().st_size if p.is_file() else 0  # Biggest first
        ))
        
        return candidates
    
    def _cleanup_item(self, item: Path) -> Dict[str, Any]:
        """Cleans up a single file or directory."""
        try:
            if not item.exists():
                return {'success': False, 'error': 'not_exists', 'path': str(item)}
            
            is_dir = item.is_dir()
            size_bytes = 0
            
            if is_dir:
                # Calculate directory size
                for root, dirs, files in os.walk(str(item)):
                    for f in files:
                        file_path = Path(root) / f
                        try:
                            size_bytes += file_path.stat().st_size
                        except:
                            pass
                
                # Remove directory
                shutil.rmtree(str(item), ignore_errors=True)
            else:
                # Get file size
                size_bytes = item.stat().st_size
                
                # Remove file
                item.unlink(missing_ok=True)
            
            logger.debug(
                "Cleanup: %s %s (%.2f MB)",
                "directory" if is_dir else "file",
                item.name, size_bytes / (1024 * 1024)
            )
            
            return {
                'success': True,
                'path': str(item),
                'is_dir': is_dir,
                'size_bytes': size_bytes
            }
            
        except Exception as e:
            logger.warning("Error limpiando %s: %s", item, e)
            return {
                'success': False,
                'error': str(e),
                'path': str(item),
                'is_dir': item.is_dir() if item.exists() else False
            }
    
    def start_monitor(self) -> None:
        """Inicia el monitor de watermarks en segundo plano."""
        if self._running:
            logger.warning("Monitor already running")
            return
        
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        
        logger.info("Monitor de watermarks iniciado")
    
    def stop_monitor(self) -> None:
        """Detiene el monitor de watermarks."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
            self._monitor_thread = None
        
        logger.info("Monitor de watermarks detenido")
    
    def _monitor_loop(self) -> None:
        """Monitor loop that periodically checks watermarks."""
        logger.info("Monitor loop iniciado para %s", self.staging_dir)
        
        while self._running:
            try:
                # Verificar uso de disco
                needs_cleanup, needs_aggressive = self.should_cleanup()
                
                if needs_aggressive:
                    logger.warning(
                        "CRITICAL disk usage: %.1f%% (watermark=%.1f%%) - Aggressive cleanup",
                        self._last_usage_percent, self.aggressive_percent
                    )
                    self.run_cleanup(aggressive=True)
                    
                elif needs_cleanup:
                    logger.info(
                        "HIGH disk usage: %.1f%% (watermark=%.1f%%) - Normal cleanup",
                        self._last_usage_percent, self.watermark_percent
                    )
                    self.run_cleanup(aggressive=False)
                
                # Wait until the next check
                for _ in range(self.check_interval):
                    if not self._running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                logger.error("Error en monitor loop: %s", e)
                time.sleep(60)  # Esperar antes de reintentar
    
    def get_metrics(self) -> Dict[str, Any]:
        """Returns metrics from the cleanup system."""
        usage = self.get_disk_usage()
        
        with self._lock:
            return {
                'staging_dir': str(self.staging_dir),
                'disk_usage': {
                    'total_gb': usage.total_bytes / (1024**3),
                    'used_gb': usage.used_bytes / (1024**3),
                    'free_gb': usage.free_bytes / (1024**3),
                    'usage_percent': usage.usage_percent
                },
                'watermarks': {
                    'normal_percent': self.watermark_percent,
                    'aggressive_percent': self.aggressive_percent
                },
                'cleanup_stats': {
                    'total_cleanups': self._cleanup_count,
                    'total_freed_gb': self._freed_bytes / (1024**3),
                    'last_check_time': self._last_check_time
                },
                'monitor': {
                    'running': self._running,
                    'check_interval_seconds': self.check_interval
                }
            }
    
    def cleanup_completed_file(self, file_path: str, immediate: bool = True) -> bool:
        """
        Cleans up a processed file.
        
        Args:
            file_path: Path to the file to clean
            immediate: True to clean immediately, False to only mark
            
        Returns:
            True if the file was cleaned successfully
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return True  # Ya no existe
            
            # Ensure the file is inside the staging directory
            try:
                path.resolve().relative_to(self.staging_dir)
            except ValueError:
                logger.warning(
                    "File outside the staging dir, skipping cleanup: %s",
                    file_path
                )
                return False
            
            if immediate:
                # Limpiar inmediatamente
                if path.is_file():
                    size = path.stat().st_size
                    path.unlink(missing_ok=True)
                    
                    with self._lock:
                        self._freed_bytes += size
                    
                    logger.debug("Processed file cleaned: %s (%.2f MB)", 
                               path.name, size / (1024 * 1024))
                else:
                    logger.warning("Path is not a file: %s", file_path)
                    return False
            
            return True
            
        except Exception as e:
            logger.error("Error cleaning processed file %s: %s", file_path, e)
            return False
    
    def __enter__(self):
        self.start_monitor()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_monitor()


# Utilities for pipeline integration
def create_default_cleanup(config: Optional[Any] = None) -> WatermarkCleanup:
    """Creates a WatermarkCleanup with default configuration."""
    import os
    
    staging_dir = os.getenv(
        'PREPROCESSING_WORK_DIR',
        getattr(config, 'PREPROCESSING_WORK_DIR', '/tmp/rag-preprocessing')
    )
    
    watermark_str = os.getenv('CLEANUP_WATERMARK_PERCENT', '70.0')
    aggressive_str = os.getenv('CLEANUP_AGGRESSIVE_PERCENT', '85.0')
    check_interval_str = os.getenv('CLEANUP_CHECK_INTERVAL', '300')
    workers_str = os.getenv('CLEANUP_WORKERS', '2')
    
    watermark = float(watermark_str)
    aggressive = float(aggressive_str)
    check_interval = int(check_interval_str)
    workers = int(workers_str)
    
    return WatermarkCleanup(
        staging_dir=staging_dir,
        watermark_percent=watermark,
        aggressive_percent=aggressive,
        check_interval_seconds=check_interval,
        workers=workers
    )
