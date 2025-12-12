from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src import logger

from .file_metadata import gather_file_metadata


def record_failure(
    pipeline: Any,
    source: str,
    message: str,
    reason: str,
) -> None:
    """
    Record metadata for a file that could not be ingested.

    This matches the behavior of the original monolithic pipeline:
    if the vector store exposes `upsert_failure`, send the record there.
    """
    file_info = gather_file_metadata(source)
    file_context: Dict[str, Optional[Any]] = getattr(pipeline, "_file_context", {}) or {}
    record: Dict[str, Any] = {
        "source": source,
        "file_path": file_info.get("file_path"),
        "file_name": file_info.get("file_name"),
        "file_extension": file_info.get("file_extension"),
        "parent_directory": file_context.get("directory_path") or file_info.get("parent_directory"),
        "file_size_bytes": file_info.get("file_size_bytes"),
        "file_modified_at": file_info.get("file_modified_at"),
        "file_id": file_info.get("file_id"),
        "failure_reason": reason,
        "failure_message": message,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "directory_file_index": file_context.get("file_index"),
        "directory_total_files": file_context.get("total_files"),
    }

    sink = getattr(pipeline.vector_store, "upsert_failure", None)
    if callable(sink):
        try:
            sink(record)
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failure sink raised error; falling back to log")

    logger.warning("Failure record (no sink available): %s", record)


__all__ = ["record_failure"]
