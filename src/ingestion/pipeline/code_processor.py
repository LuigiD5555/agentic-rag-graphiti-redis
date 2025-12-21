"""Code document ingestion steps.

This module ingests source code files by building a lightweight structural
summary (via the configured code loader), embedding that summary, and upserting
it into the vector store.

It logs stage-level progress to avoid "silent" long-running steps.
"""

from datetime import datetime, timezone
import os
from typing import Any, Dict

from src import logger

from src.ingestion.loaders.helpers import call_loader
from .stage_reporting import IngestionFileContext, IngestionStageReporter
from .state_helpers import finalize_file_ingestion
from src.utils.file_operations import gather_file_metadata
from src.utils.hashing import generate_hash
from src.utils.metadata import prune_metadata, vector_store_contains
from src.utils.text import sanitize_text, truncate_to_token_limit
from src.utils.path_discovery import should_preserve_duplicates


def _resolve_file_context(pipeline: Any) -> IngestionFileContext:
    """Build an IngestionFileContext from the pipeline's internal context."""
    context: Dict[str, Any] = getattr(pipeline, "_file_context", {}) or {}
    return IngestionFileContext(
        file_index=context.get("file_index"),
        total_files=context.get("total_files"),
    )


def process_code_document(pipeline: Any, code_loader: object) -> None:
    """Ingest a code document.

    Args:
        pipeline: The active IngestionPipeline instance.
        code_loader: Loader instance that can generate a structural summary.

    Returns:
        None
    """
    source = getattr(code_loader, "path", None) or getattr(code_loader, "_path", None) or code_loader.__class__.__name__
    source = str(source)
    file_context = _resolve_file_context(pipeline)

    with IngestionStageReporter(
        logger=logger,
        stage_name="load_structure_summary",
        source=source,
        file_context=file_context,
        heartbeat_seconds=15.0,
    ):
        summary_text_raw = call_loader(pipeline, code_loader, "load_structure_summary")

    if not summary_text_raw:
        pipeline.progress.add_total(0, source=source)
        pipeline._current_file_info = None
        return

    file_info = pipeline._current_file_info or gather_file_metadata(source)

    summary_text = sanitize_text(summary_text_raw)
    summary_text = truncate_to_token_limit(summary_text, pipeline.embedding_effective_limit, pipeline.tokenizer_model_name)
    file_path = str(file_info.get("file_path") or source)

    include_patterns = getattr(getattr(pipeline, "options", None), "include_duplicates_patterns", ())
    preserve_dupes = should_preserve_duplicates(file_path, include_patterns)

    # Preserve directory-tree context and avoid hash collisions for identical content.
    if preserve_dupes:
        summary_text = f"FILE_PATH: {file_path}\n\n{summary_text}"

    summary_hash = generate_hash(summary_text)

    if pipeline.hash_exists(summary_hash):
        pipeline.progress.add_total(0, source=source)
        finalize_file_ingestion(pipeline, file_info, chunk_total=1)
        return

    if vector_store_contains(pipeline.vector_store, summary_hash):
        pipeline.progress.add_total(0, source=source)
        pipeline.add_hash(summary_hash)
        finalize_file_ingestion(pipeline, file_info, chunk_total=1)
        return

    with IngestionStageReporter(
        logger=logger,
        stage_name="embed+upsert",
        source=source,
        file_context=file_context,
        heartbeat_seconds=30.0,
    ):
        embedding = pipeline.embedding_service.generate(summary_text)
        ingested_at = datetime.now(timezone.utc).isoformat()

        metadata: Dict[str, object] = {
            "type": "code_context",
            "structure_summary": summary_text,
            "visibility": pipeline.visibility,
            "owner_id": pipeline.owner_id,
            "allowed_user_ids": pipeline.allowed_user_ids,
            "hash": summary_hash,
            "file_path": file_info.get("file_path"),
            "file_name": file_info.get("file_name"),
            "file_extension": file_info.get("file_extension"),
            "parent_directory": (getattr(pipeline, "_file_context", {}) or {}).get("directory_path")
            or file_info.get("parent_directory"),
            "file_size_bytes": file_info.get("file_size_bytes"),
            "file_modified_at": file_info.get("file_modified_at"),
            "file_id": file_info.get("file_id"),
            "directory_file_index": file_context.file_index,
            "directory_total_files": file_context.total_files,
            "ingested_at": ingested_at,
            "archived": False,
        }
        metadata.setdefault("path", getattr(code_loader, "path", None))
        metadata = prune_metadata(metadata)

        pipeline.progress.add_total(1, source=source)
        pipeline.vector_store.upsert(
            summary_hash,
            embedding,
            metadata,
            tenant_id=pipeline.tenant_id,
        )

        pipeline.add_hash(summary_hash)

        base_url = getattr(getattr(pipeline, "vector_store", None), "base_url", None) or ""
        target_url = f"{base_url.rstrip('/')}/v1/objects" if base_url else "/v1/objects"
        source_value = str(file_info.get("file_path") or source or "code_document")

        log_line = pipeline.progress.advance(
            file_index=1,
            file_total=1,
            source=source_value,
            base_url=target_url,
        )

        prefix = file_context.format_prefix()
        if prefix:
            logger.info("%s %s", prefix, log_line)
        else:
            logger.info(log_line)

    finalize_file_ingestion(pipeline, file_info, chunk_total=1)

    # Update Redis cache with processing results
    from .file_processor import _update_file_cache
    _update_file_cache(
        pipeline=pipeline,
        full_path=source,
        chunk_count=1,
        embedding_count=1,
        status='processed'
    )


__all__ = ["process_code_document"]
