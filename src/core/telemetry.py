"""Observability hook for Result errors.

This module is the single integration point between the Result pattern and any
external monitoring system (OpenTelemetry, Sentry, Prometheus, Datadog, etc.).

How it works
------------
Every ``Result.err(...)`` in the pipeline calls ``emit_error`` **once**, at the
point where the Err is created.  Callers that propagate or transform the error
do NOT call emit_error again — the event is already recorded.

The default implementation is a no-op.  Replace it at startup with a real
backend using ``set_error_reporter`` and ``set_metrics_recorder``.

Integration examples
--------------------
OpenTelemetry::

    from opentelemetry import trace
    from src.core.telemetry import set_error_reporter

    tracer = trace.get_tracer(__name__)

    def otel_reporter(error, component, operation, extra):
        span = trace.get_current_span()
        span.record_exception(error if isinstance(error, Exception) else Exception(str(error)))
        span.set_status(trace.StatusCode.ERROR, str(error))

    set_error_reporter(otel_reporter)

Sentry::

    import sentry_sdk
    from src.core.telemetry import set_error_reporter

    def sentry_reporter(error, component, operation, extra):
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("component", component)
            scope.set_tag("operation", operation)
            for key, value in (extra or {}).items():
                scope.set_extra(key, value)
            if isinstance(error, Exception):
                sentry_sdk.capture_exception(error)
            else:
                sentry_sdk.capture_message(str(error), level="error")

    set_error_reporter(sentry_reporter)

Prometheus (counter only)::

    from prometheus_client import Counter
    from src.core.telemetry import set_metrics_recorder

    errors_total = Counter(
        "rag_errors_total",
        "Total pipeline errors",
        ["component", "operation", "error_type"],
    )

    def prom_recorder(error, component, operation, extra):
        error_type = type(error).__name__ if isinstance(error, Exception) else type(error).__name__
        errors_total.labels(component=component, operation=operation, error_type=error_type).inc()

    set_metrics_recorder(prom_recorder)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reporter type alias
# ---------------------------------------------------------------------------

ErrorReporter = Callable[
    [
        Any,          # error: AnyError (ErrorEvent | Exception)
        str,          # component: e.g. "score_cache", "pdf_loader"
        str,          # operation: e.g. "get_file_score", "load"
        Optional[Dict[str, Any]],  # extra: arbitrary key-value context
    ],
    None,
]

# ---------------------------------------------------------------------------
# Global reporters (replaced at startup by the monitoring integration)
# ---------------------------------------------------------------------------

_error_reporter: Optional[ErrorReporter] = None
_metrics_recorder: Optional[ErrorReporter] = None


def set_error_reporter(reporter: ErrorReporter) -> None:
    """Register the function that receives every Result.err(...) event.

    Call this once at application startup before serving requests.
    """
    global _error_reporter
    _error_reporter = reporter


def set_metrics_recorder(recorder: ErrorReporter) -> None:
    """Register a secondary function for metric counters/histograms.

    Both ``_error_reporter`` and ``_metrics_recorder`` are called on every
    error — use one for traces/exceptions and the other for counters.
    """
    global _metrics_recorder
    _metrics_recorder = recorder


# ---------------------------------------------------------------------------
# Public API — called inside Result-returning functions
# ---------------------------------------------------------------------------

def emit_error(
    error: Any,
    *,
    component: str,
    operation: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit an error event to all registered reporters.

    Call this immediately before ``return Result.err(error)``::

        def load(self, path: str) -> Result[list, LoaderError]:
            try:
                ...
            except OSError as exc:
                err = LoaderFileNotFoundError(path)
                emit_error(err, component="pdf_loader", operation="load",
                           extra={"path": path})
                return Result.err(err)

    Parameters
    ----------
    error:
        The error value that will be wrapped in ``Result.err(...)``.  Can be
        a ``RagError`` subclass, a plain ``Exception``, or an ``ErrorEvent``.
    component:
        Short identifier for the module/class emitting the error.
        Use snake_case, e.g. ``"score_cache"``, ``"weaviate_repository"``.
    operation:
        The method or function name, e.g. ``"get_file_score"``, ``"upsert"``.
    extra:
        Optional dict with additional context (file path, tenant id, etc.).
    """
    if _error_reporter is not None:
        try:
            _error_reporter(error, component, operation, extra)
        except Exception as reporter_exc:  # noqa: BLE001
            log.debug("Error reporter raised: %s", reporter_exc)

    if _metrics_recorder is not None:
        try:
            _metrics_recorder(error, component, operation, extra)
        except Exception as recorder_exc:  # noqa: BLE001
            log.debug("Metrics recorder raised: %s", recorder_exc)


def emit_ok(
    *,
    component: str,
    operation: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit a success event for latency/throughput tracking (optional).

    Only useful when a metrics_recorder is registered and you want to track
    success rates alongside error rates.  Not required for error monitoring.
    """
    if _metrics_recorder is not None:
        try:
            _metrics_recorder(None, component, operation, extra)
        except Exception as recorder_exc:  # noqa: BLE001
            log.debug("Metrics recorder raised on ok: %s", recorder_exc)
