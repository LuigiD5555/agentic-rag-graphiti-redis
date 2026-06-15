"""Lightweight structured logging helper for concurrency investigations."""



import asyncio
import json
import threading
from datetime import datetime, timezone
from typing import Any


def _thread_or_task_id() -> str:
    """Return a stable thread/task identifier for correlation."""
    thread_id = threading.get_ident()
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    if task is None:
        return f"thread:{thread_id}"
    return f"thread:{thread_id}|task:{id(task)}"


def emit_structured_log(
    logger: Any,
    *,
    component: str,
    request_id: str,
    operation: str,
    model_name: str = "",
    duration_ms: float | None = None,
    **extra: Any,
) -> None:
    """Emit a JSON line with mandatory observability fields."""
    payload = {
        "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "request_id": request_id,
        "operation": operation,
        "model_name": model_name,
        "duration_ms": round(duration_ms, 3) if duration_ms is not None else None,
        "thread_or_task_id": _thread_or_task_id(),
    }
    if extra:
        payload.update(extra)
    logger.info("%s", json.dumps(payload, ensure_ascii=True, sort_keys=True))

