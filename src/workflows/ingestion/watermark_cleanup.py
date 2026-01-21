"""
Watermark Cleanup - Fase 5 del plan de optimización

Implementa limpieza basada en watermarks para prevenir saturación de disco
y eliminar artefactos intermedios de manera segura.
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
    """Información de uso de disco."""
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_percent: float


@dataclass
class CleanupRule:
    """Regla de limpieza."""
    name: str
    pattern: str  # Patrón glob o extensión
    max_age_seconds: Optional[int] = None  # None = sin límite de edad
    min_size_bytes: Optional[int] = None  # None = sin límite de tamaño
    priority: int = 1  # 1 = más importante, 10 = menos importante


class WatermarkCleanup:
    """Sistema de limpieza basado en watermarks."""
    
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
            staging_dir: Directorio de staging a monitorear
            watermark_percent: Porcentaje de uso que activa limpieza normal
            aggressive_percent: Porcentaje que activa limpieza agresiva
            check_interval_seconds: Intervalo entre verificaciones
            workers: Workers para limpieza paralela
        """
        self.staging_dir = Path(staging_dir).resolve()
        self.watermark_percent = watermark_percent
        self.aggressive_percent = aggressive_percent
        self.check_interval = check_interval_seconds
        self.workers = workers
        
        # Reglas de limpieza por defecto
        self.rules = self._get_default_rules()
        
        # Estado
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Métricas
        self._last_check_time = 0.0
        self._cleanup_count = 0
        self._freed_bytes = 0
        self._last_usage_percent = 0.0
        
        # Crear directorio si no existe
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(
            "WatermarkCleanup inicializado para %s: watermark=%.1f%%, agresivo=%.1f%%, check=%ds",
            self.staging_dir, watermark_percent, aggressive_percent, check_interval_seconds
        )
    
    def _get_default_rules(self) -> List[CleanupRule]:
        """Obtiene reglas de limpieza por defecto."""
        return [
            # Archivos temporales de procesamiento
            CleanupRule(
                name="temp_files",
                pattern="*.tmp",
                max_age_seconds=3600,  # 1 hora
                priority=1
            ),
            CleanupRule(
                name="temp_dirs",
                pattern="*_temp",
                max_age_seconds=3600,
                priority=1
            ),
            
            # Artefactos de conversión/OCR
            CleanupRule(
                name="conversion_artifacts",
                pattern="*.converted.*",
                max_age_seconds=7200,  # 2 horas
                priority=2
            ),
            CleanupRule(
                name="ocr_output",
                pattern="*.ocr.*",
                max_age_seconds=7200,
                priority=2
            ),
            
            # Archivos preprocesados
            CleanupRule(
                name="preprocessed_files",
                pattern="*.preprocessed.*",
                max_age_seconds=86400,  # 24 horas
                priority=3
            ),
            
            # Logs antiguos
            CleanupRule(
                name="old_logs",
                pattern="*.log",
                max_age_seconds=604800,  # 7 días
                min_size_bytes=1024 * 1024,  # 1 MB mínimo
                priority=4
            ),
            
            # Caché antiguo
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
        
        # Obtener archivos candidatos
        candidates = self._find_cleanup_candidates(aggressive)
        
        if not candidates:
            logger.info("No hay candidatos para limpieza")
            return {
                'status': 'no_candidates',
                'files_cleaned': 0,
                'dirs_cleaned': 0,
                'freed_bytes': 0,
                'errors': 0,
                'duration_seconds': time.time() - start_time
            }
        
        logger.info("Encontrados %d candidatos para limpieza", len(candidates))
        
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
        
        # Actualizar métricas
        with self._lock:
            self._cleanup_count += 1
            self._freed_bytes += freed_bytes
        
        duration = time.time() - start_time
        
        logger.info(
            "Limpieza completada: %d archivos, %d directorios, %.2f MB liberados, "
            "%d errores, %.2f segundos",
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
        """Encuentra candidatos para limpieza basados en reglas."""
        candidates = []
        now = time.time()
        
        for rule in self.rules:
            # En modo agresivo, limpiar más archivos
            if aggressive and rule.priority > 3:
                continue  # Saltar reglas de baja prioridad en modo agresivo
            
            try:
                # Buscar archivos que coincidan con el patrón
                for item in self.staging_dir.rglob(rule.pattern):
                    if not item.exists():
                        continue
                    
                    # Verificar edad
                    if rule.max_age_seconds is not None:
                        age = now - item.stat().st_mtime
                        if age < rule.max_age_seconds and not aggressive:
                            continue
                    
                    # Verificar tamaño mínimo
                    if rule.min_size_bytes is not None:
                        size = item.stat().st_size if item.is_file() else 0
                        if size < rule.min_size_bytes:
                            continue
                    
                    candidates.append(item)
                    
            except Exception as e:
                logger.warning("Error aplicando regla '%s': %s", rule.name, e)
        
        # Ordenar por prioridad (edad * tamaño)
        candidates.sort(key=lambda p: (
            -(now - p.stat().st_mtime) if p.exists() else 0,  # Más viejo primero
            -p.stat().st_size if p.is_file() else 0  # Más grande primero
        ))
        
        return candidates
    
    def _cleanup_item(self, item: Path) -> Dict[str, Any]:
        """Limpia un solo archivo o directorio."""
        try:
            if not item.exists():
                return {'success': False, 'error': 'not_exists', 'path': str(item)}
            
            is_dir = item.is_dir()
            size_bytes = 0
            
            if is_dir:
                # Calcular tamaño del directorio
                for root, dirs, files in os.walk(str(item)):
                    for f in files:
                        file_path = Path(root) / f
                        try:
                            size_bytes += file_path.stat().st_size
                        except:
                            pass
                
                # Eliminar directorio
                shutil.rmtree(str(item), ignore_errors=True)
                
            else:
                # Obtener tamaño del archivo
                size_bytes = item.stat().st_size
                
                # Eliminar archivo
                item.unlink(missing_ok=True)
            
            logger.debug(
                "Limpieza: %s %s (%.2f MB)",
                "directorio" if is_dir else "archivo",
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
            logger.warning("Monitor ya está ejecutándose")
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
        """Loop del monitor que verifica watermarks periódicamente."""
        logger.info("Monitor loop iniciado para %s", self.staging_dir)
        
        while self._running:
            try:
                # Verificar uso de disco
                needs_cleanup, needs_aggressive = self.should_cleanup()
                
                if needs_aggressive:
                    logger.warning(
                        "Uso de disco CRÍTICO: %.1f%% (watermark=%.1f%%) - Limpieza agresiva",
                        self._last_usage_percent, self.aggressive_percent
                    )
                    self.run_cleanup(aggressive=True)
                    
                elif needs_cleanup:
                    logger.info(
                        "Uso de disco ALTO: %.1f%% (watermark=%.1f%%) - Limpieza normal",
                        self._last_usage_percent, self.watermark_percent
                    )
                    self.run_cleanup(aggressive=False)
                
                # Esperar hasta la siguiente verificación
                for _ in range(self.check_interval):
                    if not self._running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                logger.error("Error en monitor loop: %s", e)
                time.sleep(60)  # Esperar antes de reintentar
    
    def get_metrics(self) -> Dict[str, Any]:
        """Obtiene métricas del sistema de limpieza."""
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
        Limpia un archivo procesado exitosamente.
        
        Args:
            file_path: Ruta del archivo a limpiar
            immediate: True para limpiar inmediatamente, False para solo marcar
            
        Returns:
            True si se limpió exitosamente
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return True  # Ya no existe
            
            # Verificar que esté dentro del directorio de staging
            try:
                path.resolve().relative_to(self.staging_dir)
            except ValueError:
                logger.warning(
                    "Archivo fuera del staging dir, no se limpiará: %s",
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
                    
                    logger.debug("Archivo procesado limpiado: %s (%.2f MB)", 
                               path.name, size / (1024 * 1024))
                else:
                    logger.warning("Ruta no es archivo: %s", file_path)
                    return False
            
            return True
            
        except Exception as e:
            logger.error("Error limpiando archivo procesado %s: %s", file_path, e)
            return False
    
    def __enter__(self):
        self.start_monitor()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_monitor()


# Utilidades para integración con el pipeline
def create_default_cleanup(config: Optional[Any] = None) -> WatermarkCleanup:
    """Crea un WatermarkCleanup con configuración por defecto."""
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
