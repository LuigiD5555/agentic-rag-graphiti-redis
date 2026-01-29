"""
Registry for metric summary strategies with decorator pattern.

This module provides a registry system for metric summary strategies,
allowing registration via decorators and lookup by metric type.
"""

import threading
from typing import Callable, Dict, Any, List

# Import will be done lazily to avoid circular imports
# Metric type will be imported when needed


# Type alias for metric summary functions
MetricSummaryFn = Callable[[List], Dict[str, Any]]

_lock = threading.RLock()
_summaries: Dict[str, MetricSummaryFn] = {}


def register_metric_summary(metric_type: str) -> Callable[[MetricSummaryFn], MetricSummaryFn]:
    """
    Decorator to register a metric summary function.
    
    Args:
        metric_type: Metric type (e.g., 'counter', 'gauge', 'timer', 'histogram')
        
    Returns:
        Decorator function
        
    Example:
        @register_metric_summary('counter')
        def summarize_counter(metrics):
            # ... implementation ...
    """
    def decorator(summary_fn: MetricSummaryFn) -> MetricSummaryFn:
        normalized = (metric_type or "").strip().lower()
        if not normalized:
            raise ValueError("Metric type must be non-empty")
        if not callable(summary_fn):
            raise TypeError("Metric summary function must be callable")
        
        with _lock:
            _summaries[normalized] = summary_fn
        
        return summary_fn
    return decorator


def get_metric_summary(metric_type: str) -> MetricSummaryFn:
    """
    Get a metric summary function by metric type.
    
    Args:
        metric_type: Metric type
        
    Returns:
        Metric summary function
        
    Raises:
        KeyError: If metric type not found
    """
    normalized = (metric_type or "").strip().lower()
    
    with _lock:
        if normalized not in _summaries:
            available = ", ".join(sorted(_summaries.keys())) or "<none>"
            raise KeyError(f"Unknown metric type '{metric_type}'. Available: {available}")
        
        return _summaries[normalized]


def list_metric_summary_types() -> list[str]:
    """
    List all registered metric summary types.
    
    Returns:
        List of metric type strings
    """
    with _lock:
        return sorted(_summaries.keys())


def reset_metric_summary_registry() -> None:
    """
    Reset the metric summary registry (for testing).
    
    Warning: This clears all registered summaries.
    """
    with _lock:
        _summaries.clear()


# Built-in summaries loader flag
_builtins_loaded = False
_builtins_lock = threading.Lock()


def ensure_builtin_metric_summaries_loaded() -> None:
    """
    Ensure built-in metric summaries are loaded.
    
    This function is idempotent and thread-safe.
    """
    global _builtins_loaded
    
    with _builtins_lock:
        if not _builtins_loaded:
            # Import builtins module to trigger registration
            from src.workflows.ingestion.metrics import summary_builtins  # noqa: F401
            _builtins_loaded = True