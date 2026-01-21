"""
Wave Planner - Fase 3 del plan de optimización

Implementa el concepto de "waves" (olas) para procesar datasets en lotes acotados por peso,
evitando explosiones de backlog y saturación de recursos.
"""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from src import logger
from src.workflows.query.audit.decorators import logged, timed


@dataclass
class WavePlan:
    """Plan de una ola de procesamiento."""
    wave_id: str
    files: List[str]
    total_mb: float
    estimated_pages: int
    max_chunks: int = 10000  # Límite de chunks por ola
    max_tokens: int = 1000000  # Límite de tokens por ola


class WavePlanner:
    """Planificador de olas para procesamiento acotado."""
    
    def __init__(
        self,
        max_mb_per_wave: float = 500.0,
        max_files_per_wave: int = 100,
        max_chunks_per_wave: int = 10000,
        max_tokens_per_wave: int = 1000000,
        workers: int = 4
    ):
        """
        Args:
            max_mb_per_wave: MB máximos por ola (default: 500 MB)
            max_files_per_wave: archivos máximos por ola (default: 100)
            max_chunks_per_wave: chunks máximos por ola (default: 10,000)
            max_tokens_per_wave: tokens máximos por ola (default: 1,000,000)
            workers: workers para análisis paralelo
        """
        self.max_mb_per_wave = max_mb_per_wave
        self.max_files_per_wave = max_files_per_wave
        self.max_chunks_per_wave = max_chunks_per_wave
        self.max_tokens_per_wave = max_tokens_per_wave
        self.workers = workers
    
    @logged("Planificando olas de procesamiento")
    @timed()
    def plan_waves(self, file_paths: List[str]) -> List[WavePlan]:
        """
        Divide los archivos en olas acotadas por peso y cantidad.
        
        Args:
            file_paths: Lista de rutas de archivos a procesar
            
        Returns:
            Lista de planes de ola ordenados por tamaño (mayor a menor)
        """
        if not file_paths:
            return []
        
        # Analizar archivos en paralelo
        file_metadata = self._analyze_files_parallel(file_paths)
        
        # Ordenar por tamaño (mayor a menor para procesar primero los pesados)
        sorted_files = sorted(
            file_metadata.items(),
            key=lambda x: x[1]['size_mb'],
            reverse=True
        )
        
        # Crear olas
        waves = []
        current_wave_files = []
        current_wave_mb = 0.0
        current_wave_estimated_pages = 0
        wave_id = 1
        
        for file_path, metadata in sorted_files:
            file_mb = metadata['size_mb']
            estimated_pages = self._estimate_pages(file_path, file_mb)
            
            # Verificar si agregar este archivo excedería los límites
            would_exceed_mb = (current_wave_mb + file_mb) > self.max_mb_per_wave
            would_exceed_files = (len(current_wave_files) + 1) > self.max_files_per_wave
            
            if would_exceed_mb or would_exceed_files or not current_wave_files:
                # Crear nueva ola si la actual no está vacía
                if current_wave_files:
                    waves.append(self._create_wave_plan(
                        wave_id, current_wave_files, current_wave_mb, current_wave_estimated_pages
                    ))
                    wave_id += 1
                    current_wave_files = []
                    current_wave_mb = 0.0
                    current_wave_estimated_pages = 0
            
            # Agregar archivo a la ola actual
            current_wave_files.append(file_path)
            current_wave_mb += file_mb
            current_wave_estimated_pages += estimated_pages
        
        # Agregar la última ola si tiene archivos
        if current_wave_files:
            waves.append(self._create_wave_plan(
                wave_id, current_wave_files, current_wave_mb, current_wave_estimated_pages
            ))
        
        logger.info(
            "Planificadas %d olas para %d archivos (%.2f MB total)",
            len(waves), len(file_paths), sum(w.total_mb for w in waves)
        )
        
        for i, wave in enumerate(waves, 1):
            logger.info(
                "Ola %d: %d archivos, %.2f MB, ~%d páginas",
                i, len(wave.files), wave.total_mb, wave.estimated_pages
            )
        
        return waves
    
    def _analyze_files_parallel(self, file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
        """Analiza archivos en paralelo para obtener metadatos."""
        metadata = {}
        
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            future_to_path = {
                executor.submit(self._analyze_single_file, path): path
                for path in file_paths
            }
            
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    metadata[path] = future.result()
                except Exception as e:
                    logger.warning("Error analizando archivo %s: %s", path, e)
                    metadata[path] = {'size_mb': 0.0, 'extension': Path(path).suffix}
        
        return metadata
    
    def _analyze_single_file(self, file_path: str) -> Dict[str, Any]:
        """Analiza un solo archivo."""
        try:
            # Obtener tamaño en MB
            size_bytes = os.path.getsize(file_path)
            size_mb = size_bytes / (1024 * 1024)
            extension = Path(file_path).suffix.lower()
            
            return {
                'size_mb': size_mb,
                'extension': extension,
                'path': file_path
            }
        except Exception as e:
            logger.debug("Error obteniendo tamaño de %s: %s", file_path, e)
            return {'size_mb': 0.0, 'extension': Path(file_path).suffix, 'path': file_path}
    
    def _estimate_pages(self, file_path: str, size_mb: float) -> int:
        """Estima páginas basado en tipo de archivo y tamaño."""
        extension = Path(file_path).suffix.lower()
        
        # Estimaciones aproximadas
        if extension in ['.pdf', '.docx', '.doc']:
            # ~50 KB por página para documentos
            return max(1, int(size_mb * 1024 / 50))
        elif extension in ['.pptx', '.ppt']:
            # ~100 KB por slide
            return max(1, int(size_mb * 1024 / 100))
        elif extension in ['.xlsx', '.xls']:
            # ~10 KB por hoja
            return max(1, int(size_mb * 1024 / 10))
        elif extension in ['.txt', '.md', '.py', '.js', '.java']:
            # ~5 KB por "página" de texto
            return max(1, int(size_mb * 1024 / 5))
        else:
            # Estimación conservadora
            return max(1, int(size_mb * 1024 / 50))
    
    def _create_wave_plan(
        self,
        wave_id: int,
        files: List[str],
        total_mb: float,
        estimated_pages: int
    ) -> WavePlan:
        """Crea un plan de ola."""
        return WavePlan(
            wave_id=f"wave_{wave_id:03d}",
            files=files,
            total_mb=total_mb,
            estimated_pages=estimated_pages,
            max_chunks=self.max_chunks_per_wave,
            max_tokens=self.max_tokens_per_wave
        )
    
    def get_wave_summary(self, waves: List[WavePlan]) -> Dict[str, Any]:
        """Obtiene un resumen de las olas planificadas."""
        total_files = sum(len(w.files) for w in waves)
        total_mb = sum(w.total_mb for w in waves)
        total_pages = sum(w.estimated_pages for w in waves)
        
        return {
            'wave_count': len(waves),
            'total_files': total_files,
            'total_mb': total_mb,
            'total_estimated_pages': total_pages,
            'avg_files_per_wave': total_files / len(waves) if waves else 0,
            'avg_mb_per_wave': total_mb / len(waves) if waves else 0,
            'waves': [
                {
                    'wave_id': w.wave_id,
                    'file_count': len(w.files),
                    'total_mb': w.total_mb,
                    'estimated_pages': w.estimated_pages
                }
                for w in waves
            ]
        }


class WaveOrchestrator:
    """Orquestador que ejecuta olas secuencialmente."""
    
    def __init__(self, planner: WavePlanner):
        self.planner = planner
        self.current_wave = 0
        self.total_waves = 0
    
    def execute_waves(
        self,
        file_paths: List[str],
        process_callback,
        callback_kwargs: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Ejecuta las olas secuencialmente.
        
        Args:
            file_paths: Archivos a procesar
            process_callback: Función que procesa una lista de archivos
            callback_kwargs: Argumentos adicionales para el callback
            
        Returns:
            Resumen de ejecución
        """
        callback_kwargs = callback_kwargs or {}
        
        # Planificar olas
        waves = self.planner.plan_waves(file_paths)
        self.total_waves = len(waves)
        
        if not waves:
            return {'status': 'no_files', 'waves_processed': 0}
        
        results = []
        wave_summaries = []
        
        for i, wave in enumerate(waves, 1):
            self.current_wave = i
            
            logger.info(
                "=== Ejecutando Ola %d/%d: %s ===",
                i, self.total_waves, wave.wave_id
            )
            logger.info(
                "Archivos: %d, Tamaño: %.2f MB, Páginas estimadas: %d",
                len(wave.files), wave.total_mb, wave.estimated_pages
            )
            
            try:
                # Ejecutar callback con los archivos de esta ola
                wave_result = process_callback(wave.files, **callback_kwargs)
                
                # Agregar metadatos de la ola al resultado
                wave_summary = {
                    'wave_id': wave.wave_id,
                    'wave_index': i,
                    'file_count': len(wave.files),
                    'total_mb': wave.total_mb,
                    'estimated_pages': wave.estimated_pages,
                    'result': wave_result
                }
                
                wave_summaries.append(wave_summary)
                results.append(wave_result)
                
                logger.info(
                    "✓ Ola %d/%d completada: %s",
                    i, self.total_waves, wave.wave_id
                )
                
            except Exception as e:
                logger.error(
                    "✗ Error en ola %d/%d (%s): %s",
                    i, self.total_waves, wave.wave_id, e
                )
                
                wave_summary = {
                    'wave_id': wave.wave_id,
                    'wave_index': i,
                    'file_count': len(wave.files),
                    'total_mb': wave.total_mb,
                    'estimated_pages': wave.estimated_pages,
                    'error': str(e),
                    'result': None
                }
                
                wave_summaries.append(wave_summary)
        
        # Resumen final
        successful_waves = sum(1 for w in wave_summaries if w.get('error') is None)
        total_files_processed = sum(
            len(w['result'].get('files', [])) 
            for w in wave_summaries if w.get('result')
        )
        
        return {
            'status': 'completed',
            'total_waves': self.total_waves,
            'successful_waves': successful_waves,
            'failed_waves': self.total_waves - successful_waves,
            'total_files_processed': total_files_processed,
            'wave_summaries': wave_summaries,
            'planner_summary': self.planner.get_wave_summary(waves)
        }


# Configuración por defecto desde variables de entorno
def create_default_wave_planner() -> WavePlanner:
    """Crea un WavePlanner con configuración por defecto."""
    import os
    
    max_mb = float(os.getenv('WAVE_MAX_MB', '500'))
    max_files = int(os.getenv('WAVE_MAX_FILES', '100'))
    max_chunks = int(os.getenv('WAVE_MAX_CHUNKS', '10000'))
    max_tokens = int(os.getenv('WAVE_MAX_TOKENS', '1000000'))
    workers = int(os.getenv('WAVE_PLANNER_WORKERS', '4'))
    
    return WavePlanner(
        max_mb_per_wave=max_mb,
        max_files_per_wave=max_files,
        max_chunks_per_wave=max_chunks,
        max_tokens_per_wave=max_tokens,
        workers=workers
    )


def create_default_wave_orchestrator() -> WaveOrchestrator:
    """Crea un WaveOrchestrator con configuración por defecto."""
    planner = create_default_wave_planner()
    return WaveOrchestrator(planner)
