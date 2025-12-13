from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from src import logger
from .loader_helpers import call_loader
from .state_helpers import finalize_file_ingestion
from src.storage.vector.utils import (
    gather_file_metadata,
    generate_hash,
    prune_metadata,
    sanitize_text,
    truncate_to_token_limit,
    vector_store_contains,
)


def process_code_document(pipeline: Any, code_loader: object) -> None:
    summary_text_raw = call_loader(pipeline, code_loader, "load_structure_summary")
    if not summary_text_raw:
        source = getattr(code_loader, "path", None) or getattr(code_loader, "_path", None)
        pipeline.progress.add_total(0, source=source)
        pipeline._current_file_info = None
        return

    source = getattr(code_loader, "path", None) or getattr(code_loader, "_path", None)
    summary_text = sanitize_text(summary_text_raw)
    summary_text = truncate_to_token_limit(summary_text, pipeline.embedding_effective_limit, pipeline.tokenizer_model_name)
    summary_hash = generate_hash(summary_text)
    file_info = pipeline._current_file_info or gather_file_metadata(source)
    existing_cache = getattr(pipeline, "_existing_hash_cache", set())

    if summary_hash in existing_cache:
        pipeline.progress.add_total(0, source=source)
        finalize_file_ingestion(pipeline, file_info, chunk_total=1)
        return

    if vector_store_contains(pipeline.vector_store, summary_hash):
        pipeline.progress.add_total(0, source=source)
        existing_cache.add(summary_hash)
        finalize_file_ingestion(pipeline, file_info, chunk_total=1)
        return

    embedding = pipeline.embedding_service.generate(summary_text)
    file_context = getattr(pipeline, "_file_context", {}) or {}
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
        "parent_directory": file_context.get("directory_path") or file_info.get("parent_directory"),
        "file_size_bytes": file_info.get("file_size_bytes"),
        "file_modified_at": file_info.get("file_modified_at"),
        "file_id": file_info.get("file_id"),
        "directory_file_index": file_context.get("file_index"),
        "directory_total_files": file_context.get("total_files"),
        "ingested_at": ingested_at,
        "archived": False,
    }
    metadata.setdefault("path", getattr(code_loader, "path", None))
    metadata = prune_metadata(metadata)

    pipeline.progress.add_total(1, source=source)
    try:
        pipeline.vector_store.upsert(
            summary_hash,
            embedding,
            metadata,
            tenant_id=pipeline.tenant_id,  # type: ignore[arg-type]
        )
    except TypeError:
        pipeline.vector_store.upsert(summary_hash, embedding, metadata)

    existing_cache.add(summary_hash)
    base_url = getattr(getattr(pipeline, "vector_store", None), "base_url", None) or ""
    target_url = f"{base_url.rstrip('/')}/v1/objects" if base_url else "/v1/objects"
    source_value = file_info.get("file_path") or source or "code_document"
    log_line = pipeline.progress.advance(
        file_index=int(file_context.get("file_index") or 1),
        file_total=int(file_context.get("total_files") or 1),
        source=source_value,
        base_url=target_url,
    )
    logger.info(log_line)
    finalize_file_ingestion(pipeline, file_info, chunk_total=1)


__all__ = ["process_code_document"]
