"""
Metrics Instrumentation - Phase 0 of the optimization plan

Implements metric collection for monitoring the ingestion pipeline.
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
    """Supported metric types."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class Metric:
    """Definition of a metric."""
    name: str
    type: MetricType
    value: float
    timestamp: datetime
    tags: Dict[str, str]
    description: Optional[str] = None


class MetricsCollector:
    """Metrics collector for the ingestion pipeline."""
    
    def __init__(self):
        self._metrics: Dict[str, List[Metric]] = {}
        self._lock = Lock()
        
        # Predefined metrics
        self._predefined_metrics = {
            # Counters
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
            
            # Histograms
            "ingestion.sizes.file_mb": MetricType.HISTOGRAM,
            "ingestion.sizes.chunk_tokens": MetricType.HISTOGRAM,
            "ingestion.sizes.embedding_dimensions": MetricType.HISTOGRAM,
        }
        
        logger.info("MetricsCollector initialized with %d predefined metrics", 
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
        Records a metric.
        
        Args:
            name: Metric name
            value: Metric value
            metric_type: Metric type (inferred from name if not provided)
            tags: Additional tags
            description: Optional description
        """
        # Determine metric type
        if metric_type is None:
            metric_type = self._infer_metric_type(name)
        
        # Create metric
        metric = Metric(
            name=name,
            type=metric_type,
            value=value,
            timestamp=datetime.now(timezone.utc),
            tags=tags or {},
            description=description
        )
        
        # Store metric
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = []
            self._metrics[name].append(metric)
        
        logger.debug("Metric recorded: %s = %s (%s)", name, value, metric_type.value)
    
    def increment(
        self,
        name: str,
        amount: float = 1.0,
        tags: Optional[Dict[str, str]] = None,
        description: Optional[str] = None
    ) -> None:
        """Increment a counter."""
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
        """Set a gauge."""
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
        """Record a duration."""
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
        """Record a value in a histogram."""
        self.record(
            name=name,
            value=value,
            metric_type=MetricType.HISTOGRAM,
            tags=tags,
            description=description
        )
    
    def timeit(self, name: str, tags: Optional[Dict[str, str]] = None):
        """
        Decorator to measure execution time.
        
        Example:
            @metrics.timeit("ingestion.timing.file_processing")
            def process_file(file_path):
                # ... processing ...
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
        Retrieves stored metrics.
        
        Args:
            name: Specific metric name (None for all)
            since: Filter metrics from this timestamp
            limit: Maximum metrics per name
            
        Returns:
            Dictionary mapping metric names to lists of metrics
        """
        with self._lock:
            if name:
                metrics = {name: self._metrics.get(name, [])}
            else:
                metrics = self._metrics.copy()
        
        # Apply filters
        filtered_metrics = {}
        for metric_name, metric_list in metrics.items():
            filtered = metric_list
            
            if since:
                filtered = [m for m in filtered if m.timestamp >= since]
            
            if limit and len(filtered) > limit:
                filtered = filtered[-limit:]  # Last N metrics
            
            if filtered:
                filtered_metrics[metric_name] = filtered
        
        return filtered_metrics
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Returns a statistical summary of the metrics.
        
        Returns:
            Dictionary with statistics per metric type
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
        
        # Ensure built-in metric summaries are loaded
        from .metrics.summary_registry import ensure_builtin_metric_summaries_loaded, get_metric_summary
        ensure_builtin_metric_summaries_loaded()
        
        for name, metrics in all_metrics.items():
            if not metrics:
                continue
            
            summary["total_metrics"] += len(metrics)
            
            # Statistics per metric type
            metric_type = metrics[0].type.value
            summary["metric_types"][metric_type] = summary["metric_types"].get(metric_type, 0) + len(metrics)
            
            # Recent metrics (last hour)
            one_hour_ago = datetime.now(timezone.utc).timestamp() - 3600
            recent = [m for m in metrics if m.timestamp.timestamp() > one_hour_ago]
            if recent:
                summary["recent_activity"][name] = len(recent)
            
            # Get summary function from registry
            try:
                summary_fn = get_metric_summary(metric_type)
                summary_dict = summary_fn(metrics)
                
                # Store in appropriate section based on metric type
                if metric_type == MetricType.COUNTER.value:
                    summary["counters"][name] = summary_dict
                elif metric_type == MetricType.GAUGE.value:
                    summary["gauges"][name] = summary_dict
                elif metric_type == MetricType.TIMER.value:
                    summary["timers"][name] = summary_dict
                elif metric_type == MetricType.HISTOGRAM.value:
                    summary["histograms"][name] = summary_dict
                    
            except KeyError:
                # If metric type not found in registry, skip detailed summary
                pass
        
        return summary
    
    def clear(self, name: Optional[str] = None) -> None:
        """
        Clears stored metrics.
        
        Args:
            name: Specific metric name (None for all)
        """
        with self._lock:
            if name:
                if name in self._metrics:
                    del self._metrics[name]
            else:
                self._metrics.clear()
        
        logger.info("Metrics cleared%s", f" for '{name}'" if name else "")
    
    def export_prometheus(self) -> str:
        """
        Exports metrics in Prometheus format.
        
        Returns:
            Prometheus-formatted string
        """
        lines = []
        now = datetime.now(timezone.utc).timestamp() * 1000  # milisegundos
        
        with self._lock:
            for name, metrics in self._metrics.items():
                if not metrics:
                    continue
                
                # Use the most recent metric
                latest = metrics[-1]
                
                # Prometheus format
                metric_type = latest.type.value
                value = latest.value
                
                # Build tags
                tags_str = ""
                if latest.tags:
                    tags = [f'{k}="{v}"' for k, v in latest.tags.items()]
                    tags_str = "{" + ",".join(tags) + "}"
                
                # Metric line
                line = f"{self._sanitize_name(name)}{tags_str} {value} {int(now)}"
                lines.append(f"# TYPE {self._sanitize_name(name)} {metric_type}")
                lines.append(line)
        
        return "\n".join(lines)
    
    def _infer_metric_type(self, name: str) -> MetricType:
        """Infers the metric type based on the name."""
        # Check predefined metrics
        if name in self._predefined_metrics:
            return self._predefined_metrics[name]
        
        # Infer by name patterns
        name_lower = name.lower()
        
        if any(pattern in name_lower for pattern in ["counter", "count", "total", "processed"]):
            return MetricType.COUNTER
        
        if any(pattern in name_lower for pattern in ["gauge", "current", "active", "usage", "free"]):
            return MetricType.GAUGE
        
        if any(pattern in name_lower for pattern in ["timer", "timing", "duration", "latency"]):
            return MetricType.TIMER
        
        if any(pattern in name_lower for pattern in ["histogram", "size", "distribution"]):
            return MetricType.HISTOGRAM
        
        # Default to gauge
        return MetricType.GAUGE
    
    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Sanitizes metric names for Prometheus format."""
        # Replace invalid characters
        sanitized = name.replace(".", "_").replace("-", "_").replace(" ", "_")
        # Ensure name starts with a letter
        if sanitized and not sanitized[0].isalpha():
            sanitized = "metric_" + sanitized
        return sanitized
    
    @staticmethod
    def _percentile(values: List[float], p: float) -> float:
        """Calculates the percentile of a list of values."""
        if not values:
            return 0.0
        
        sorted_values = sorted(values)
        scaled_index = (len(sorted_values) - 1) * (p / 100.0)
        lower_index = int(scaled_index)
        fractional_part = scaled_index - lower_index

        if lower_index + 1 < len(sorted_values):
            return sorted_values[lower_index] + fractional_part * (
                sorted_values[lower_index + 1] - sorted_values[lower_index]
            )
        else:
            return sorted_values[lower_index]


# Singleton global
_global_metrics_collector: Optional[MetricsCollector] = None


def get_global_metrics_collector() -> MetricsCollector:
    """Returns the global metrics collector."""
    global _global_metrics_collector
    if _global_metrics_collector is None:
        _global_metrics_collector = MetricsCollector()
    return _global_metrics_collector


# Decoradores de conveniencia
def record_metric(name: str, value: float, **kwargs):
    """Decorator to record a metric."""
    collector = get_global_metrics_collector()
    collector.record(name, value, **kwargs)


def increment_counter(name: str, amount: float = 1.0, **kwargs):
    """Decorator to increment a counter."""
    collector = get_global_metrics_collector()
    collector.increment(name, amount, **kwargs)


def set_gauge(name: str, value: float, **kwargs):
    """Decorator to set a gauge."""
    collector = get_global_metrics_collector()
    collector.gauge(name, value, **kwargs)


def record_timer(name: str, duration_seconds: float, **kwargs):
    """Decorator to record a timer."""
    collector = get_global_metrics_collector()
    collector.timer(name, duration_seconds, **kwargs)


def record_histogram(name: str, value: float, **kwargs):
    """Decorator to record a histogram."""
    collector = get_global_metrics_collector()
    collector.histogram(name, value, **kwargs)


def time_metric(name: str, **kwargs):
    """Decorator to measure execution time."""
    collector = get_global_metrics_collector()
    return collector.timeit(name, **kwargs)


# Integration with existing components
class IngestionMetrics:
    """Convenience class for ingestion metrics."""
    
    def __init__(self, collector: Optional[MetricsCollector] = None):
        self.collector = collector or get_global_metrics_collector()
    
    def record_discovery(self, file_count: int, directory_count: int) -> None:
        """Record discovery metrics."""
        self.collector.increment("ingestion.files.discovered", file_count)
        self.collector.gauge("ingestion.directories.scanned", directory_count)
    
    def record_file_processing(
        self,
        file_path: str,
        size_mb: float,
        success: bool,
        duration_seconds: float
    ) -> None:
        """Record file processing metrics."""
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
        """Record chunk processing metrics."""
        self.collector.increment("ingestion.chunks.created", chunk_count)
        self.collector.histogram("ingestion.sizes.chunk_tokens", token_count)
        self.collector.timer("ingestion.timing.chunk_embedding", duration_seconds)
    
    def record_embedding_processing(
        self,
        chunk_count: int,
        embedding_dimensions: int,
        duration_seconds: float
    ) -> None:
        """Record embedding metrics."""
        self.collector.increment("ingestion.chunks.embedded", chunk_count)
        self.collector.histogram("ingestion.sizes.embedding_dimensions", embedding_dimensions)
        self.collector.timer("ingestion.timing.chunk_embedding", duration_seconds)
    
    def record_upsert_processing(
        self,
        chunk_count: int,
        duration_seconds: float,
        batch_size: int = 1
    ) -> None:
        """Record upsert metrics."""
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
        """Record wave processing metrics."""
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
        """Record resource pool metrics."""
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
        """Record disk metrics."""
        self.collector.gauge("ingestion.disk.usage_percent", usage_percent)
        self.collector.gauge("ingestion.disk.free_mb", free_mb)
        self.collector.gauge("ingestion.disk.total_mb", total_mb)
    
    def record_memory_metrics(
        self,
        usage_mb: float,
        usage_percent: float
    ) -> None:
        """Record memory metrics."""
        self.collector.gauge("ingestion.memory.usage_mb", usage_mb)
        self.collector.gauge("ingestion.memory.usage_percent", usage_percent)
    
    def get_ingestion_summary(self) -> Dict[str, Any]:
        """Returns a summary of ingestion metrics."""
        summary = self.collector.get_summary()
        
        # Extract key metrics
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
