"""Reusable decorators for logging and timing cross-cutting concerns."""
from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def timed(level: int = logging.DEBUG, logger_name: str | None = None) -> Callable[[F], F]:
    """Measure execution time and log it at the given level."""

    def decorator(func: F) -> F:
        log = logging.getLogger(logger_name or func.__module__)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000.0
                log.log(level, "%s executed in %.2f ms", func.__qualname__, duration_ms)

        return wrapper  # type: ignore[return-value]

    return decorator


def logged(
    message: str | None = None,
    level: int = logging.DEBUG,
    logger_name: str | None = None,
) -> Callable[[F], F]:
    """Log entry/exit for a function, including exceptions."""

    def decorator(func: F) -> F:
        log = logging.getLogger(logger_name or func.__module__)
        entry_msg = message or f"Calling {func.__qualname__}"

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            log.log(level, entry_msg)
            try:
                result = func(*args, **kwargs)
                log.log(level, "%s completed", func.__qualname__)
                return result
            except Exception:
                log.exception("%s raised an exception", func.__qualname__)
                raise

        return wrapper  # type: ignore[return-value]

    return decorator
