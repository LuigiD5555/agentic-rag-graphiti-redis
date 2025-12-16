"""File dispatch logic for ingestion.

This module decides how to process each discovered file based on extension:
- Text-like documents use the text pipeline.
- Code files use the code pipeline.

It also updates the ingestion catalog and registers per-file progress estimates.
"""

import os
import time
from typing import Any
from pathlib import Path

from src import logger
from src.rag.ingestion.loaders import CODE_LOADER_SPECS, TEXT_LOADER_SPECS, PlainTextLoader
from src.storage.vector.utils import gather_file_metadata

from .code_processor import process_code_document
from .loader_helpers import should_skip_path
from .state_helpers import register_observed_file
from .text_processor import process_text_document


def _format_timedelta(td):
    """Format timedelta in human-readable form."""
    seconds = int(td.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h"
    else:
        days = seconds // 86400
        return f"{days}d"


def _update_file_cache(
    pipeline: Any,
    full_path: str,
    chunk_count: int,
    embedding_count: int,
    status: str = 'processed',
    error_message: str | None = None
) -> None:
    """Update Redis cache with processed file metadata."""
    cache_manager = getattr(pipeline, 'cache_manager', None)
    if not cache_manager or not cache_manager.enabled:
        return

    try:
        # Compute file hash
        content_hash = cache_manager.compute_file_hash(full_path)
        if not content_hash:
            return

        # Get file stats
        stat = Path(full_path).stat()

        # Import FileMetadata
        from src.rag.ingestion.cache_manager import FileMetadata

        # Create metadata
        metadata = FileMetadata(
            file_path=full_path,
            content_hash=content_hash,
            mtime=stat.st_mtime,
            size=stat.st_size,
            last_processed=time.time(),
            chunk_count=chunk_count,
            embedding_count=embedding_count,
            status=status,
            error_message=error_message
        )

        # Save to cache
        cache_manager.set_file_metadata(metadata)
        logger.debug("Updated cache for %s: %d chunks, %d embeddings", full_path, chunk_count, embedding_count)

    except Exception as e:
        logger.debug("Failed to update cache for %s: %s", full_path, e)


def process_candidate_file(
    pipeline: Any,
    full_path: str,
    *,
    file_index: int | None = None,
    total_files: int | None = None,
    directory_path: str | None = None,
) -> None:
    """Process a single candidate path.

    Args:
        pipeline: The active IngestionPipeline instance.
        full_path: Absolute or relative file path.
        file_index: 1-based index of the file within its parent batch.
        total_files: Total number of files in the parent batch.
        directory_path: Parent directory path used for metadata.

    Returns:
        None
    """
    if should_skip_path(full_path):
        return

    directory = directory_path or os.path.dirname(full_path)
    file_info = gather_file_metadata(full_path)
    register_observed_file(pipeline, full_path)

    # Check Redis cache if available
    cache_manager = getattr(pipeline, 'cache_manager', None)
    if cache_manager and cache_manager.enabled:
        # Check if file is unchanged using content hash
        if cache_manager.is_file_unchanged(full_path):
            cached_meta = cache_manager.get_file_metadata(full_path)
            if cached_meta and cached_meta.status == 'processed':
                # Calculate time saved
                import datetime
                last_proc = datetime.datetime.fromtimestamp(cached_meta.last_processed)
                time_ago = datetime.datetime.now() - last_proc

                logger.info(
                    "✓ CACHE HIT: Skipping %s (processed %s ago, %d chunks, %d embeddings) %s",
                    os.path.basename(full_path),
                    _format_timedelta(time_ago),
                    cached_meta.chunk_count,
                    cached_meta.embedding_count,
                    "🚀" if not cache_manager.paranoid_mode else "🔒"
                )
                pipeline._current_file_info = None
                return

        # Content-based deduplication: check if identical file was already processed
        content_hash = cache_manager.compute_file_hash(full_path)
        if content_hash:
            duplicate_meta = cache_manager.find_processed_file_by_hash(content_hash)
            if duplicate_meta and duplicate_meta.file_path != full_path:
                # Found a duplicate! Reuse its metadata without processing
                import datetime
                last_proc = datetime.datetime.fromtimestamp(duplicate_meta.last_processed)
                time_ago = datetime.datetime.now() - last_proc

                logger.info(
                    "⚡ DUPLICATE: Skipping %s (identical to %s, processed %s ago, %d chunks, %d embeddings)",
                    os.path.basename(full_path),
                    os.path.basename(duplicate_meta.file_path),
                    _format_timedelta(time_ago),
                    duplicate_meta.chunk_count,
                    duplicate_meta.embedding_count,
                )

                # Cache this file with the same processing results
                stat = Path(full_path).stat()
                from src.rag.ingestion.cache_manager import FileMetadata
                new_metadata = FileMetadata(
                    file_path=full_path,
                    content_hash=content_hash,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    last_processed=time.time(),
                    chunk_count=duplicate_meta.chunk_count,
                    embedding_count=duplicate_meta.embedding_count,
                    status='processed',
                    error_message=None
                )
                cache_manager.set_file_metadata(new_metadata)
                pipeline._current_file_info = None
                return

    # Fallback to catalog-based check
    if not pipeline.catalog.should_process_file(file_info):
        logger.info("Skipping %s; no changes detected.", full_path)
        pipeline._current_file_info = None
        return

    pipeline.progress.register_file(full_path, file_info.get("file_size_bytes"))
    estimate = pipeline.progress.get_file_estimate(full_path)
    if estimate is not None:
        logger.info(
            "Estimated embeddings for %s: %d (size_bytes=%s)",
            full_path,
            int(estimate),
            file_info.get("file_size_bytes"),
        )

    pipeline._file_context = {
        "file_index": file_index,
        "total_files": total_files,
        "directory_path": directory,
    }
    pipeline._current_file_info = file_info
    logger.info("Processing candidate file: %s", full_path)

    for extensions, loader_cls in TEXT_LOADER_SPECS:
        if full_path.endswith(extensions):
            process_text_document(pipeline, loader_cls(full_path))
            return

    for extensions, loader_cls in CODE_LOADER_SPECS:
        if full_path.endswith(extensions):
            process_code_document(pipeline, loader_cls(full_path))
            return

    process_text_document(pipeline, PlainTextLoader(full_path))


__all__ = ["process_candidate_file"]
