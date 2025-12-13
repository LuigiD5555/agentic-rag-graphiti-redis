from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Optional

from src import logger


def record_directory_listing(pipeline: Any, directory_path: str, file_paths: Iterable[str]) -> None:
    directory = os.path.abspath(directory_path)
    pipeline.catalog.record_directory(directory, file_paths)
    pipeline._observed_directories.add(directory)


def register_observed_file(pipeline: Any, full_path: str) -> None:
    pipeline._observed_files.add(os.path.abspath(full_path))


def finalize_file_ingestion(pipeline: Any, file_info: Dict[str, Any], chunk_total: int) -> None:
    directory_total = None
    if isinstance(pipeline._file_context, dict):
        directory_total = pipeline._file_context.get("total_files")
    pipeline.catalog.record_file_ingestion(
        file_info,
        chunk_total=chunk_total,
        directory_total=directory_total,
    )
    pipeline._current_file_info = None


def finalize_ingestion_run(pipeline: Any) -> None:
    try:
        _handle_deleted_files(pipeline)
    finally:
        pipeline.catalog.save()


def _handle_deleted_files(pipeline: Any) -> None:
    missing = pipeline.catalog.list_missing_files(
        pipeline._observed_files,
        pipeline._observed_directories,
    )
    if not missing:
        return
    archive_fn = getattr(pipeline.vector_store, "archive_file", None)
    if not callable(archive_fn):
        for entry in missing:
            logger.warning("Archiving unsupported; leaving stale embeddings for %s", entry["file_path"])
        return

    for entry in missing:
        file_id = entry.get("file_id")
        file_path = entry.get("file_path")
        if not file_id:
            continue
        try:
            archive_fn(file_id, tenant_id=pipeline.tenant_id)  # type: ignore[arg-type]
            pipeline.catalog.mark_archived(file_path)
            logger.info("Archived embeddings for removed file %s", file_path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to archive embeddings for %s", file_path)


__all__ = [
    "record_directory_listing",
    "register_observed_file",
    "finalize_file_ingestion",
    "finalize_ingestion_run",
]
