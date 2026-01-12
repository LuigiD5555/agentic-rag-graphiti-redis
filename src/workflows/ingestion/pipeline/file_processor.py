"""File dispatch logic for ingestion.

This module decides how to process each discovered file based on extension:
- Text-like documents use the text pipeline.
- Code files use the code pipeline.

It also updates the ingestion catalog and registers per-file progress estimates.
"""

import os
import time
from pathlib import Path
from typing import Any

from src import logger
from src.workflows.ingestion.loaders import CODE_LOADER_SPECS, TEXT_LOADER_SPECS, PlainTextLoader
from src.workflows.ingestion.preprocessor import get_preprocessor
from src.utils.file_operations import gather_file_metadata
from src.utils.path_discovery import should_preserve_duplicates

from .code_processor import process_code_document
from src.workflows.ingestion.loaders.helpers import should_skip_path
from .state_helpers import register_observed_file
from .text_processor import process_text_document


def _format_timedelta(td):
    """Format timedelta in human-readable form."""
    seconds = int(td.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h"
    days = seconds // 86400
    return f"{days}d"


def _update_file_cache(
    pipeline: Any,
    full_path: str,
    chunk_count: int,
    embedding_count: int,
    status: str = "processed",
    error_message: str | None = None,
) -> None:
    """Update Redis cache with processed file metadata."""
    cache_manager = getattr(pipeline, "cache_manager", None)
    if not cache_manager:
        logger.warning("Cache manager not available for pipeline, skipping cache update for %s", full_path)
        return

    if not cache_manager.enabled:
        logger.debug("Cache manager disabled, skipping cache update for %s", full_path)
        return

    try:
        # Compute file hash
        logger.debug("Computing file hash for %s", full_path)
        content_hash = cache_manager.compute_file_hash(full_path)
        if not content_hash:
            logger.error("Failed to compute file hash for %s, cannot cache", full_path)
            return

        logger.debug("File hash computed: %s for %s", content_hash[:16], full_path)

        # Get file stats
        stat = Path(full_path).stat()
        logger.debug("File stats: size=%d, mtime=%f for %s", stat.st_size, stat.st_mtime, full_path)

        # Import FileMetadata
        from src.backends.storage.cache.ingestion import FileMetadata

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
            error_message=error_message,
        )

        logger.debug("Created metadata object for %s", full_path)

        # Save to cache
        success = cache_manager.set_file_metadata(metadata)
        if success:
            logger.info(
                "Cache updated for %s: %d chunks, %d embeddings (hash=%s)",
                os.path.basename(full_path),
                chunk_count,
                embedding_count,
                content_hash[:16],
            )
        else:
            logger.error("Failed to save cache metadata for %s", full_path)

    except Exception as exc:
        logger.error("Failed to update cache for %s: %s", full_path, exc, exc_info=True)


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
    cache_manager = getattr(pipeline, "cache_manager", None)
    if cache_manager and cache_manager.enabled:
        # Check if file is unchanged using content hash
        if cache_manager.is_file_unchanged(full_path):
            cached_meta = cache_manager.get_file_metadata(full_path)
            if cached_meta and cached_meta.status == "processed":
                # Calculate time saved
                import datetime
                last_processed = datetime.datetime.fromtimestamp(cached_meta.last_processed)
                time_ago = datetime.datetime.now() - last_processed

                logger.info(
                    "CACHE HIT: Skipping %s (processed %s ago, %d chunks, %d embeddings) [%s]",
                    os.path.basename(full_path),
                    _format_timedelta(time_ago),
                    cached_meta.chunk_count,
                    cached_meta.embedding_count,
                    "Fast mode" if not cache_manager.paranoid_mode else "Security mode",
                )
                pipeline._current_file_info = None
                return

        # Content-based deduplication: check if identical file was already processed.
        # Some files are intentionally excluded from deduplication when their location matters.
        include_patterns = getattr(getattr(pipeline, "options", None), "include_duplicates_patterns", ())
        preserve_dupes = should_preserve_duplicates(full_path, include_patterns)

        content_hash = None if preserve_dupes else cache_manager.compute_file_hash(full_path)

        if content_hash:
            duplicate_meta = cache_manager.find_processed_file_by_hash(content_hash)
            if duplicate_meta and duplicate_meta.file_path != full_path:
                # Found a duplicate! Reuse its metadata without processing
                import datetime
                from src.backends.storage.cache.ingestion import FileMetadata

                last_processed = datetime.datetime.fromtimestamp(duplicate_meta.last_processed)
                time_ago = datetime.datetime.now() - last_processed

                logger.info(
                    "DUPLICATE: Skipping %s (identical to %s, processed %s ago, %d chunks, %d embeddings)",
                    os.path.basename(full_path),
                    os.path.basename(duplicate_meta.file_path),
                    _format_timedelta(time_ago),
                    duplicate_meta.chunk_count,
                    duplicate_meta.embedding_count,
                )

                # Cache this file with the same processing results
                stat = Path(full_path).stat()
                cache_manager.set_file_metadata(
                    FileMetadata(
                        file_path=full_path,
                        content_hash=content_hash,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                        last_processed=time.time(),
                        chunk_count=duplicate_meta.chunk_count,
                        embedding_count=duplicate_meta.embedding_count,
                        status="processed",
                        error_message=None,
                    )
                )
                pipeline._current_file_info = None
                return

    # Fallback to catalog-based check
    if not pipeline.catalog.should_process_file(file_info):
        logger.info("Skipping %s; no changes detected.", full_path)
        pipeline._current_file_info = None
        return

    # ============== PREPROCESSING: Convert/extract files before ingestion ==============
    # Check if file needs preprocessing (Office docs, archives, images for OCR, etc.)
    preprocessor = get_preprocessor()
    file_path = Path(full_path)

    if preprocessor.should_preprocess(file_path):
        logger.info("Preprocessing required for: %s", os.path.basename(full_path))
        processed_path = preprocessor.preprocess(file_path)

        if processed_path is None:
            # Preprocessing failed - skip this file
            logger.warning("Preprocessing failed for %s, skipping file", full_path)
            pipeline._current_file_info = None
            return

        if processed_path.is_dir():
            # Archive extraction -> process each extracted file recursively
            logger.info(
                "Archive extracted to %s, processing %d files...",
                processed_path.name,
                sum(1 for _ in processed_path.rglob("*") if _.is_file())
            )

            for extracted_file in processed_path.rglob("*"):
                if extracted_file.is_file():
                    # Recursively process each extracted file
                    process_candidate_file(
                        pipeline,
                        str(extracted_file),
                        file_index=file_index,
                        total_files=total_files,
                        directory_path=str(processed_path),  # Use extraction dir as parent
                    )

            pipeline._current_file_info = None
            return

        # File was converted (e.g., DOCX -> TXT) -> use preprocessed version
        full_path = str(processed_path)
        if str(file_path) != full_path:
            logger.info("Using preprocessed file: %s", os.path.basename(full_path))

        # Update file_info with preprocessed file metadata
        file_info = gather_file_metadata(full_path)
    # ============== END PREPROCESSING ==============

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
            # Pass Redis client to PDFLoader for content caching
            if loader_cls.__name__ == "PDFLoader":
                cache_manager = getattr(pipeline, "cache_manager", None)
                redis_client = getattr(cache_manager, "redis_client", None) if cache_manager else None
                loader = loader_cls(full_path, redis_client=redis_client)
            else:
                loader = loader_cls(full_path)
            process_text_document(pipeline, loader)
            return

    for extensions, loader_cls in CODE_LOADER_SPECS:
        if full_path.endswith(extensions):
            process_code_document(pipeline, loader_cls(full_path))
            return

    process_text_document(pipeline, PlainTextLoader(full_path))


__all__ = ["process_candidate_file"]
