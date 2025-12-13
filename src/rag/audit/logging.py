"""Centralized logging helpers for the project."""
from __future__ import annotations

import logging

DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def resolve_level(level: str | int | None) -> int:
    """Convert a string/int level into a logging level constant."""
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        return getattr(logging, level.upper(), logging.INFO)
    return logging.INFO


def configure_logging(level: str | int | None = None, fmt: str = DEFAULT_FORMAT) -> logging.Logger:
    """
    Configure the root logger with a consistent format and level.

    Returns the project logger for convenience.
    """
    numeric_level = resolve_level(level)
    logging.basicConfig(level=numeric_level, format=fmt, force=True)
    return get_logger()


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a namespaced logger."""
    return logging.getLogger(name or "rag")


__all__ = ["configure_logging", "get_logger", "resolve_level", "DEFAULT_FORMAT"]
