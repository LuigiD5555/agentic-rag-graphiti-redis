from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src import logger
try:
    from langchain_core.documents import Document
except ImportError:
    from langchain.schema import Document  # type: ignore

from .loader_helpers import call_loader, resolve_loader_source
from .splitters import split_documents
from .state_helpers import finalize_file_ingestion
from src.storage.vector.utils import (
    gather_file_metadata,
    generate_hash,
    prepare_embedding_segments,
    prune_metadata,
    sanitize_text,
    truncate_to_token_limit,
    vector_store_contains,
)


def process_text_document(pipeline: Any, loader: object) -> None:
    documents = call_loader(pipeline, loader, "load")
    if not documents:
        pipeline.progress.add_total(0, source=resolve_loader_source(loader))
        pipeline._current_file_info = None
        return

    chunks = list(split_documents(pipeline.text_splitter, documents))
    if not chunks:
        source = resolve_loader_source(loader)
        logger.warning("Skipping %s; no chunks produced after splitting.", source)
        pipeline.progress.add_total(0, source=source)
        pipeline._current_file_info = None
        return

    prepared_chunks = prepare_embedding_segments(chunks, pipeline.embedding_token_limit)
    if not prepared_chunks:
        source = resolve_loader_source(loader)
        logger.warning("Skipping %s; splitting produced no embedding-ready chunks.", source)
        pipeline.progress.add_total(0, source=source)
        pipeline._current_file_info = None
        return

    chunk_total = len(prepared_chunks)
    source = resolve_loader_source(loader)
    pipeline.progress.add_total(chunk_total, source=source)
    file_info = pipeline._current_file_info or gather_file_metadata(source)
    file_context: Dict[str, Optional[Any]] = getattr(pipeline, "_file_context", {}) or {}
    directory_file_index = file_context.get("file_index")
    directory_total_files = file_context.get("total_files")
    directory_path = file_context.get("directory_path") or file_info.get("parent_directory")
    ingested_at = datetime.now(timezone.utc).isoformat()
    existing_cache = getattr(pipeline, "_existing_hash_cache", set())

    for chunk_index, (segment_text, chunk_meta) in enumerate(prepared_chunks, start=1):
        sanitized_text = sanitize_text(segment_text)
        sanitized_text = truncate_to_token_limit(
            sanitized_text,
            pipeline.embedding_effective_limit,
            pipeline.tokenizer_model_name,
        )
        content_hash = generate_hash(sanitized_text)
        if content_hash in existing_cache:
            continue
        if vector_store_contains(pipeline.vector_store, content_hash):
            existing_cache.add(content_hash)
            continue

        embedding = pipeline.embedding_service.generate(sanitized_text)
        raw_meta: Dict[str, Any] = dict(chunk_meta or {})
        source_value = str(raw_meta.get("source") or file_info.get("file_path") or "document")
        metadata: Dict[str, Any] = {
            "content": sanitized_text,
            "source": source_value,
            "visibility": str(pipeline.visibility),
            "owner_id": str(pipeline.owner_id),
            "allowed_user_ids": [str(u) for u in (pipeline.allowed_user_ids or [])],
            "hash": content_hash,
            "file_path": file_info.get("file_path"),
            "file_name": file_info.get("file_name"),
            "file_extension": file_info.get("file_extension"),
            "parent_directory": directory_path,
            "file_size_bytes": file_info.get("file_size_bytes"),
            "file_modified_at": file_info.get("file_modified_at"),
            "file_id": file_info.get("file_id"),
            "chunk_index": chunk_index,
            "chunk_total": chunk_total,
            "ingested_at": ingested_at,
            "directory_file_index": directory_file_index,
            "directory_total_files": directory_total_files,
            "archived": False,
        }
        metadata = prune_metadata(metadata)

        try:
            pipeline.vector_store.upsert(
                content_hash,
                embedding,
                metadata,
                tenant_id=pipeline.tenant_id,  # type: ignore[arg-type]
            )
        except TypeError as exc:
            # Backends without tenant_id support raise TypeError for unexpected kwarg.
            if "tenant_id" in str(exc) or "unexpected keyword" in str(exc).lower():
                pipeline.vector_store.upsert(content_hash, embedding, metadata)
            else:
                raise

        existing_cache.add(content_hash)
        base_url = getattr(getattr(pipeline, "vector_store", None), "base_url", None) or ""
        target_url = f"{base_url.rstrip('/')}/v1/objects" if base_url else "/v1/objects"
        log_line = pipeline.progress.advance(
            file_index=chunk_index,
            file_total=chunk_total,
            source=source_value,
            base_url=target_url,
        )
        logger.info(log_line)
    finalize_file_ingestion(pipeline, file_info, chunk_total=chunk_total)


__all__ = ["process_text_document"]
