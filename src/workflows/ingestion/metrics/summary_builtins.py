"""
Built-in metric summary strategies.

This module registers the built-in metric summary strategies using the decorator pattern.
"""

from typing import List, Dict, Any
from .summary_registry import register_metric_summary


@register_metric_summary("counter")
def summarize_counter(metrics: List) -> Dict[str, Any]:
    """
    Summarize counter metrics.
    
    Args:
        metrics: List of counter metrics
        
    Returns:
        Dictionary with counter statistics
    """
    if not metrics:
        return {"total": 0, "count": 0, "avg_per_metric": 0}
    
    total = sum(m.value for m in metrics)
    return {
        "total": total,
        "count": len(metrics),
        "avg_per_metric": total / len(metrics) if len(metrics) > 0 else 0
    }


@register_metric_summary("gauge")
def summarize_gauge(metrics: List) -> Dict[str, Any]:
    """
    Summarize gauge metrics.
    
    Args:
        metrics: List of gauge metrics
        
    Returns:
        Dictionary with gauge statistics
    """
    if not metrics:
        return {"current": 0, "min": 0, "max": 0, "avg": 0}
    
    values = [m.value for m in metrics]
    return {
        "current": values[-1] if values else 0,
        "min": min(values) if values else 0,
        "max": max(values) if values else 0,
        "avg": sum(values) / len(values) if values else 0
    }


@register_metric_summary("timer")
def summarize_timer(metrics: List) -> Dict[str, Any]:
    """
    Summarize timer metrics.
    
    Args:
        metrics: List of timer metrics
        
    Returns:
        Dictionary with timer statistics
    """
    if not metrics:
        return {
            "count": 0,
            "total_seconds": 0,
            "avg_seconds": 0,
            "min_seconds": 0,
            "max_seconds": 0
        }
    
    values = [m.value for m in metrics]
    return {
        "count": len(values),
        "total_seconds": sum(values),
        "avg_seconds": sum(values) / len(values) if values else 0,
        "min_seconds": min(values) if values else 0,
        "max_seconds": max(values) if values else 0
    }


@register_metric_summary("histogram")
def summarize_histogram(metrics: List) -> Dict[str, Any]:
    """
    Summarize histogram metrics.
    
    Args:
        metrics: List of histogram metrics
        
    Returns:
        Dictionary with histogram statistics
    """
    if not metrics:
        return {
            "count": 0,
            "min": 0,
            "max": 0,
            "avg": 0,
            "p50": 0,
            "p95": 0,
            "p99": 0
        }
    
    values = [m.value for m in metrics]
    
    def _percentile(vals: List[float], p: float) -> float:
        """Calculate percentile of a list of values."""
        if not vals:
            return 0.0
        
        sorted_values = sorted(vals)
        scaled_index = (len(sorted_values) - 1) * (p / 100.0)
        lower_index = int(scaled_index)
        fractional_part = scaled_index - lower_index

        if lower_index + 1 < len(sorted_values):
            return sorted_values[lower_index] + fractional_part * (
                sorted_values[lower_index + 1] - sorted_values[lower_index]
            )
        return sorted_values[lower_index]
    
    return {
        "count": len(values),
        "min": min(values) if values else 0,
        "max": max(values) if values else 0,
        "avg": sum(values) / len(values) if values else 0,
        "p50": _percentile(values, 50) if values else 0,
        "p95": _percentile(values, 95) if values else 0,
        "p99": _percentile(values, 99) if values else 0
    }
