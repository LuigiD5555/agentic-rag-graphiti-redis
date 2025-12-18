"""Centralized logging helpers for the project."""
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
    """Configure logging with a consistent format and sensible defaults.

    This project runs in containers and talks to multiple services (Weaviate, Redis,
    Neo4j, LM Studio). Some third-party libraries (notably `httpx`) can be very
    chatty at INFO level. We keep the application logger at the requested level,
    while lowering noisy dependencies unless the user explicitly raises them.

    Args:
        level: The desired root log level.
        fmt: The log line format.

    Returns:
        The project logger ("rag") for convenience.
    """
    numeric_level = resolve_level(level)
    logging.basicConfig(level=numeric_level, format=fmt, force=True)

    # Silence noisy third-party loggers
    for noisy_logger_name in (
        "httpx",
        "httpcore",
        "weaviate",
        "urllib3",
    ):
        logging.getLogger(noisy_logger_name).setLevel(logging.WARNING)

    return get_logger()


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a namespaced logger."""
    return logging.getLogger(name or "rag")


__all__ = ["configure_logging", "get_logger", "resolve_level", "DEFAULT_FORMAT"]
