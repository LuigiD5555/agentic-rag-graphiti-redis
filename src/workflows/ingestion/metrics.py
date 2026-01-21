"""
Metrics Instrumentation - Fase 0 del plan de optimización

Implementa recolección de métricas para monitoreo del pipeline de ingestión.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from threading import Lock
from enum import Enum

from src import logger
from src.workflows.query.audit.decorators import logged, timed


class MetricType(Enum):
    """Tipos de métricas soportados."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class Metric:
    """Definición de una métrica."""
    name: str
    type: MetricType
    value: float
    timestamp: datetime
    tags: Dict[str, str]
    description: Optional[str] = None


class MetricsCollector:
    """Colector de métricas para el pipeline de ingestión."""
    
    def __init__(self):
        self._metrics: Dict[str, List[Metric]] = {}
        self._lock = Lock()
        
        # Métricas predefinidas
        self._predefined_metrics = {
            # Contadores
            "ingestion.files.discovered": MetricType.COUNTER,
            "ingestion.files.processed": MetricType.COUNTER,
            "ingestion.files.ingested": MetricType.COUNTER,
            "ingestion.files.failed": MetricType.COUNTER,
            "ingestion.chunks.created": MetricType.COUNTER,
            "ingestion.chunks.embedded": MetricType.COUNTER,
            "ingestion.chunks.upserted": MetricType.COUNTER,
            
            # Gauges
            "ingestion.pipeline.active_workers": MetricType.GAUGE,
            "ingestion.pipeline.queue_size": MetricType.GAUGE,
            "ingestion.memory.usage_mb": MetricType.GAUGE,
            "ingestion.disk.usage_percent": MetricType.GAUGE,
            "ingestion.disk.free_mb": MetricType.GAUGE,
            
            # Timers
            "ingestion.timing.file_processing": MetricType.TIMER,
            "ingestion.timing.chunk_embedding": MetricType.TIMER,
            "ingestion.timing.batch_upsert": MetricType.TIMER,
            "ingestion.timing.wave_processing": MetricType.TIMER,
            
            # Histogramas
            "ingestion.sizes.file_mb": MetricType.HISTOGRAM,
            "ingestion.sizes.chunk_tokens": MetricType.HISTOGRAM,
            "ingestion.sizes.embedding_dimensions": MetricType.HISTOGRAM,
        }
        
        logger.info("MetricsCollector inicializado con %d métricas predefinidas", 
                   len(self._predefined_metrics))
    
    def record(
        self,
        name: str,
        value: float,
        metric_type: Optional[MetricType] = None,
        tags: Optional[Dict[str, str]] = None,
        description: Optional[str] = None
    ) -> None:
        """
        Registra una métrica.
        
        Args:
            name: Nombre de la métrica
            value: Valor de la métrica
            metric_type: Tipo de métrica (si no se especifica, se infiere del nombre)
            tags: Etiquetas adicionales
            description: Descripción opcional
        """
        # Determinar tipo de métrica
        if metric_type is None:
            metric_type = self._infer_metric_type(name)
        
        # Crear métrica
        metric = Metric(
            name=name,
            type=metric_type,
            value=value,
            timestamp=datetime.now(timezone.utc),
            tags=tags or {},
            description=description
        )
        
        # Guardar métrica
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = []
            self._metrics[name].append(metric)
        
        logger.debug("Métrica registrada: %s = %s (%s)", name, value, metric_type.value)
    
    def increment(
        self,
        name: str,
        amount: float = 1.0,
        tags: Optional[Dict[str, str]] = None,
        description: Optional[str] = None
    ) -> None:
        """Incrementa un contador."""
        self.record(
            name=name,
            value=amount,
            metric_type=MetricType.COUNTER,
            tags=tags,
            description=description
        )
    
    def gauge(
        self,
        name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None,
        description: Optional[str] = None
    ) -> None:
        """Establece un gauge."""
        self.record(
            name=name,
            value=value,
            metric_type=MetricType.GAUGE,
            tags=tags,
            description=description
        )
    
    def timer(
        self,
        name: str,
        duration_seconds: float,
        tags: Optional[Dict[str, str]] = None,
        description: Optional[str] = None
    ) -> None:
        """Registra un tiempo de ejecución."""
        self.record(
            name=name,
            value=duration_seconds,
            metric_type=MetricType.TIMER,
            tags=tags,
            description=description
        )
    
    def histogram(
        self,
        name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None,
        description: Optional[str] = None
    ) -> None:
        """Registra un valor en un histograma."""
        self.record(
            name=name,
            value=value,
            metric_type=MetricType.HISTOGRAM,
            tags=tags,
            description=description
        )
    
    def timeit(self, name: str, tags: Optional[Dict[str, str]] = None):
        """
        Decorador para medir tiempo de ejecución.
        
        Uso:
            @metrics.timeit("ingestion.timing.file_processing")
            def process_file(file_path):
                # ... procesamiento ...
        """
        def decorator(func):
            def wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    duration = time.time() - start_time
                    self.timer(name, duration, tags)
            return wrapper
        return decorator
    
    def get_metrics(
        self,
        name: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> Dict[str, List[Metric]]:
        """
        Obtiene métricas almacenadas.
        
        Args:
            name: Nombre de métrica específica (None para todas)
            since: Filtrar métricas desde esta fecha
            limit: Límite de métricas por nombre
            
        Returns:
            Diccionario de nombre -> lista de métricas
        """
        with self._lock:
            if name:
                metrics = {name: self._metrics.get(name, [])}
            else:
                metrics = self._metrics.copy()
        
        # Aplicar filtros
        filtered_metrics = {}
        for metric_name, metric_list in metrics.items():
            filtered = metric_list
            
            if since:
                filtered = [m for m in filtered if m.timestamp >= since]
            
            if limit and len(filtered) > limit:
                filtered = filtered[-limit:]  # Últimas N métricas
            
            if filtered:
                filtered_metrics[metric_name] = filtered
        
        return filtered_metrics
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Obtiene un resumen estadístico de las métricas.
        
        Returns:
            Diccionario con estadísticas por tipo de métrica
        """
        with self._lock:
            all_metrics = self._metrics.copy()
        
        summary = {
            "total_metrics": 0,
            "metric_types": {},
            "recent_activity": {},
            "counters": {},
            "gauges": {},
            "timers": {},
            "histograms": {}
        }
        
        for name, metrics in all_metrics.items():
            if not metrics:
                continue
            
            summary["total_metrics"] += len(metrics)
            
            # Estadísticas por tipo
            metric_type = metrics[0].type.value
            summary["metric_types"][metric_type] = summary["metric_types"].get(metric_type, 0) + len(metrics)
            
            # Métricas recientes (última hora)
            one_hour_ago = datetime.now(timezone.utc).timestamp() - 3600
            recent = [m for m in metrics if m.timestamp.timestamp() > one_hour_ago]
            if recent:
                summary["recent_activity"][name] = len(recent)
            
            # Estadísticas específicas por tipo
            if metric_type == MetricType.COUNTER.value:
                total = sum(m.value for m in metrics)
                summary["counters"][name] = {
                    "total": total,
                    "count": len(metrics),
                    "avg_per_metric": total / len(metrics) if len(metrics) > 0 else 0
                }
            
            elif metric_type == MetricType.GAUGE.value:
                values = [m.value for m in metrics]
                summary["gauges"][name] = {
                    "current": values[-1] if values else 0,
                    "min": min(values) if values else 0,
                    "max": max(values) if values else 0,
                    "avg": sum(values) / len(values) if values else 0
                }
            
            elif metric_type == MetricType.TIMER.value:
                values = [m.value for m in metrics]
                summary["timers"][name] = {
                    "count": len(values),
                    "total_seconds": sum(values),
                    "avg_seconds": sum(values) / len(values) if values else 0,
                    "min_seconds": min(values) if values else 0,
                    "max_seconds": max(values) if values else 0
                }
            
            elif metric_type == MetricType.HISTOGRAM.value:
                values = [m.value for m in metrics]
                summary["histograms"][name] = {
                    "count": len(values),
                    "min": min(values) if values else 0,
                    "max": max(values) if values else 0,
                    "avg": sum(values) / len(values) if values else 0,
                    "p50": self._percentile(values, 50) if values else 0,
                    "p95": self._percentile(values, 95) if values else 0,
                    "p99": self._percentile(values, 99) if values else 0
                }
        
        return summary
    
    def clear(self, name: Optional[str] = None) -> None:
        """
        Limpia métricas almacenadas.
        
        Args:
            name: Nombre de métrica específica (None para todas)
        """
        with self._lock:
            if name:
                if name in self._metrics:
                    del self._metrics[name]
            else:
                self._metrics.clear()
        
        logger.info("Métricas limpiadas%s", f" para '{name}'" if name else "")
    
    def export_prometheus(self) -> str:
        """
        Exporta métricas en formato Prometheus.
        
        Returns:
            String en formato Prometheus
        """
        lines = []
        now = datetime.now(timezone.utc).timestamp() * 1000  # milisegundos
        
        with self._lock:
            for name, metrics in self._metrics.items():
                if not metrics:
                    continue
                
                # Usar la métrica más reciente
                latest = metrics[-1]
                
                # Formato Prometheus
                metric_type = latest.type.value
                value = latest.value
                
                # Construir etiquetas
                tags_str = ""
                if latest.tags:
                    tags = [f'{k}="{v}"' for k, v in latest.tags.items()]
                    tags_str = "{" + ",".join(tags) + "}"
                
                # Línea de métrica
                line = f"{self._sanitize_name(name)}{tags_str} {value} {int(now)}"
                lines.append(f"# TYPE {self._sanitize_name(name)} {metric_type}")
                lines.append(line)
        
        return "\n".join(lines)
    
    def _infer_metric_type(self, name: str) -> MetricType:
        """Infiere el tipo de métrica basado en el nombre."""
        # Verificar métricas predefinidas
        if name in self._predefined_metrics:
            return self._predefined_metrics[name]
        
        # Inferir por patrones en el nombre
        name_lower = name.lower()
        
        if any(pattern in name_lower for pattern in ["counter", "count", "total", "processed"]):
            return MetricType.COUNTER
        
        if any(pattern in name_lower for pattern in ["gauge", "current", "active", "usage", "free"]):
            return MetricType.GAUGE
        
        if any(pattern in name_lower for pattern in ["timer", "timing", "duration", "latency"]):
            return MetricType.TIMER
        
        if any(pattern in name_lower for pattern in ["histogram", "size", "distribution"]):
            return MetricType.HISTOGRAM
        
        # Por defecto, usar gauge
        return MetricType.GAUGE
    
    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Sanitiza nombre para formato Prometheus."""
        # Reemplazar caracteres no válidos
        sanitized = name.replace(".", "_").replace("-", "_").replace(" ", "_")
        # Asegurar que empiece con letra
        if sanitized and not sanitized[0].isalpha():
            sanitized = "metric_" + sanitized
        return sanitized
    
    @staticmethod
    def _percentile(values: List[float], p: float) -> float:
        """Calcula percentil de una lista de valores."""
        if not values:
            return 0.0
        
        sorted_values = sorted(values)
        k = (len(sorted_values) - 1) * (p / 100.0)
        f = int(k)
        c = k - f
        
        if f + 1 < len(sorted_values):
            return sorted_values[f] + c * (sorted_values[f + 1] - sorted_values[f])
        else:
            return sorted_values[f]


# Singleton global
_global_metrics_collector: Optional[MetricsCollector] = None


def get_global_metrics_collector() -> MetricsCollector:
    """Obtiene el colector de métricas global."""
    global _global_metrics_collector
    if _global_metrics_collector is None:
        _global_metrics_collector = MetricsCollector()
    return _global_metrics_collector


# Decoradores de conveniencia
def record_metric(name: str, value: float, **kwargs):
    """Decorador para registrar una métrica."""
    collector = get_global_metrics_collector()
    collector.record(name, value, **kwargs)


def increment_counter(name: str, amount: float = 1.0, **kwargs):
    """Decorador para incrementar un contador."""
    collector = get_global_metrics_collector()
    collector.increment(name, amount, **kwargs)


def set_gauge(name: str, value: float, **kwargs):
    """Decorador para establecer un gauge."""
    collector = get_global_metrics_collector()
    collector.gauge(name, value, **kwargs)


def record_timer(name: str, duration_seconds: float, **kwargs):
    """Decorador para registrar un timer."""
    collector = get_global_metrics_collector()
    collector.timer(name, duration_seconds, **kwargs)


def record_histogram(name: str, value: float, **kwargs):
    """Decorador para registrar un histograma."""
    collector = get_global_metrics_collector()
    collector.histogram(name, value, **kwargs)


def time_metric(name: str, **kwargs):
    """Decorador para medir tiempo de ejecución."""
    collector = get_global_metrics_collector()
    return collector.timeit(name, **kwargs)


# Integración con componentes existentes
class IngestionMetrics:
    """Clase de conveniencia para métricas de ingestión."""
    
    def __init__(self, collector: Optional[MetricsCollector] = None):
        self.collector = collector or get_global_metrics_collector()
    
    def record_discovery(self, file_count: int, directory_count: int) -> None:
        """Registra métricas de descubrimiento."""
        self.collector.increment("ingestion.files.discovered", file_count)
        self.collector.gauge("ingestion.directories.scanned", directory_count)
    
    def record_file_processing(
        self,
        file_path: str,
        size_mb: float,
        success: bool,
        duration_seconds: float
    ) -> None:
        """Registra métricas de procesamiento de archivo."""
        self.collector.increment("ingestion.files.processed")
        
        if success:
            self.collector.increment("ingestion.files.ingested")
        else:
            self.collector.increment("ingestion.files.failed")
        
        self.collector.timer("ingestion.timing.file_processing", duration_seconds)
        self.collector.histogram("ingestion.sizes.file_mb", size_mb)
    
    def record_chunk_processing(
        self,
        chunk_count: int,
        token_count: int,
        duration_seconds: float
    ) -> None:
        """Registra métricas de procesamiento de chunks."""
        self.collector.increment("ingestion.chunks.created", chunk_count)
        self.collector.histogram("ingestion.sizes.chunk_tokens", token_count)
        self.collector.timer("ingestion.timing.chunk_embedding", duration_seconds)
    
    def record_embedding_processing(
        self,
        chunk_count: int,
        embedding_dimensions: int,
        duration_seconds: float
    ) -> None:
        """Registra métricas de embedding."""
        self.collector.increment("ingestion.chunks.embedded", chunk_count)
        self.collector.histogram("ingestion.sizes.embedding_dimensions", embedding_dimensions)
        self.collector.timer("ingestion.timing.chunk_embedding", duration_seconds)
    
    def record_upsert_processing(
        self,
        chunk_count: int,
        duration_seconds: float,
        batch_size: int = 1
    ) -> None:
        """Registra métricas de upsert."""
        self.collector.increment("ingestion.chunks.upserted", chunk_count)
        self.collector.timer("ingestion.timing.batch_upsert", duration_seconds)
        self.collector.gauge("ingestion.batch.size", batch_size)
    
    def record_wave_processing(
        self,
        wave_id: str,
        file_count: int,
        total_mb: float,
        duration_seconds: float
    ) -> None:
        """Registra métricas de procesamiento por olas."""
        tags = {"wave_id": wave_id}
        self.collector.gauge("ingestion.wave.file_count", file_count, tags=tags)
        self.collector.gauge("ingestion.wave.total_mb", total_mb, tags=tags)
        self.collector.timer("ingestion.timing.wave_processing", duration_seconds, tags=tags)
    
    def record_resource_pool_metrics(
        self,
        pool_name: str,
        active_tasks: int,
        queued_tasks: int,
        completed_tasks: int
    ) -> None:
        """Registra métricas de pools de recursos."""
        tags = {"pool_name": pool_name}
        self.collector.gauge("ingestion.pool.active_tasks", active_tasks, tags=tags)
        self.collector.gauge("ingestion.pool.queued_tasks", queued_tasks, tags=tags)
        self.collector.gauge("ingestion.pool.completed_tasks", completed_tasks, tags=tags)
    
    def record_disk_metrics(
        self,
        usage_percent: float,
        free_mb: float,
        total_mb: float
    ) -> None:
        """Registra métricas de disco."""
        self.collector.gauge("ingestion.disk.usage_percent", usage_percent)
        self.collector.gauge("ingestion.disk.free_mb", free_mb)
        self.collector.gauge("ingestion.disk.total_mb", total_mb)
    
    def record_memory_metrics(
        self,
        usage_mb: float,
        usage_percent: float
    ) -> None:
        """Registra métricas de memoria."""
        self.collector.gauge("ingestion.memory.usage_mb", usage_mb)
        self.collector.gauge("ingestion.memory.usage_percent", usage_percent)
    
    def get_ingestion_summary(self) -> Dict[str, Any]:
        """Obtiene un resumen de las métricas de ingestión."""
        summary = self.collector.get_summary()
        
        # Extraer métricas clave
        key_metrics = {
            "files": {
                "discovered": summary.get("counters", {}).get("ingestion.files.discovered", {}).get("total", 0),
                "processed": summary.get("counters", {}).get("ingestion.files.processed", {}).get("total", 0),
                "ingested": summary.get("counters", {}).get("ingestion.files.ingested", {}).get("total", 0),
                "failed": summary.get("counters", {}).get("ingestion.files.failed", {}).get("total", 0),
            },
            "chunks": {
                "created": summary.get("counters", {}).get("ingestion.chunks.created", {}).get("total", 0),
                "embedded": summary.get("counters", {}).get("ingestion.chunks.embedded", {}).get("total", 0),
                "upserted": summary.get("counters", {}).get("ingestion.chunks.upserted", {}).get("total", 0),
            },
            "timing": {
                "file_processing_avg": summary.get("timers", {}).get("ingestion.timing.file_processing", {}).get("avg_seconds", 0),
                "chunk_embedding_avg": summary.get("timers", {}).get("ingestion.timing.chunk_embedding", {}).get("avg_seconds", 0),
                "batch_upsert_avg": summary.get("timers", {}).get("ingestion.timing.batch_upsert", {}).get("avg_seconds", 0),
            },
            "system": {
                "disk_usage": summary.get("gauges", {}).get("ingestion.disk.usage_percent", {}).get("current", 0),
                "memory_usage": summary.get("gauges", {}).get("ingestion.memory.usage_mb", {}).get("current", 0),
            }
        }
        
        return key_metrics
