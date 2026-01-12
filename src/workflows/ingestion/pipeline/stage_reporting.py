"""Stage-level progress reporting for ingestion.

This module provides a lightweight, logging-first way to surface *where* an
ingestion run is spending time. It intentionally avoids TTY-only features so it
works well in Docker/Podman logs.

Key features:
- Logs a stage start + end with elapsed time.
- Emits periodic "heartbeat" messages while a stage is running, which is useful
  when a stage is CPU/IO heavy and produces no intermediate logs.

The reporter is designed to be used as a context manager:

    with IngestionStageReporter(..., stage_name="load"):
        documents = loader.load()
"""

import logging
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class IngestionFileContext:
    """File-level context used to format log prefixes."""

    file_index: int | None = None
    total_files: int | None = None

    def format_prefix(self) -> str:
        """Return a human-readable prefix such as "[File 12/25851]"."""
        if self.file_index is None or self.total_files is None:
            return ""
        return f"[File {int(self.file_index)}/{int(self.total_files)}]"


class IngestionStageReporter:
    """Log stage start/end and periodic heartbeats for a single ingestion stage."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        stage_name: str,
        source: str,
        file_context: IngestionFileContext,
        heartbeat_seconds: float = 15.0,
        level: int = logging.INFO,
    ) -> None:
        """Create a stage reporter.

        Args:
            logger: Logger instance used for output.
            stage_name: Name of the stage (e.g., "load", "split").
            source: A useful identifier for the current file (path or name).
            file_context: Context containing file index / total.
            heartbeat_seconds: Interval for emitting "still running" lines.
                Set to 0 to disable.
            level: Log level for stage messages.
        """
        if not stage_name:
            raise ValueError("stage_name must be a non-empty string")

        self._logger = logger
        self._stage_name = stage_name
        self._source = source
        self._file_context = file_context
        self._heartbeat_seconds = max(0.0, float(heartbeat_seconds or 0.0))
        self._level = int(level)

        self._start_ts: float | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "IngestionStageReporter":
        self._start_ts = time.monotonic()
        prefix = self._file_context.format_prefix()
        message = f"{prefix} Stage START: {self._stage_name} - {self._source}".strip()
        self._logger.log(self._level, message)

        if self._heartbeat_seconds > 0:
            self._thread = threading.Thread(
                target=self._run_heartbeat,
                name=f"ingest-heartbeat:{self._stage_name}",
                daemon=True,
            )
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

        elapsed = self.elapsed_seconds()
        prefix = self._file_context.format_prefix()
        status = "OK" if exc_type is None else f"ERROR({exc_type.__name__})"
        message = (
            f"{prefix} Stage END: {self._stage_name} - {status} - "
            f"elapsed={elapsed:.2f}s - {self._source}"
        ).strip()
        self._logger.log(self._level, message)

    def elapsed_seconds(self) -> float:
        """Return elapsed seconds since __enter__ was called."""
        if self._start_ts is None:
            return 0.0
        return max(0.0, time.monotonic() - self._start_ts)

    def _run_heartbeat(self) -> None:
        """Emit periodic heartbeats until the stage finishes."""
        while not self._stop_event.wait(self._heartbeat_seconds):
            elapsed = self.elapsed_seconds()
            prefix = self._file_context.format_prefix()
            message = (
                f"{prefix} Stage RUNNING: {self._stage_name} - "
                f"elapsed={elapsed:.0f}s - {self._source}"
            ).strip()
            self._logger.log(self._level, message)


__all__ = ["IngestionFileContext", "IngestionStageReporter"]
