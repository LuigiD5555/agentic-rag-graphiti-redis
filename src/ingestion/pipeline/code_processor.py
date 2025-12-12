from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from .file_metadata import gather_file_metadata
from .loader_helpers import call_loader
from .metadata_utils import prune_metadata
from .state_helpers import finalize_file_ingestion
from .storage_utils import vector_store_contains
from .text_utils import generate_hash, sanitize_text, truncate_to_token_limit


def process_code_document(pipeline: Any, code_loader: object) -> None:
    summary_text_raw = call_loader(pipeline, code_loader, "load_structure_summary")
    if not summary_text_raw:
        pipeline._current_file_info = None
        return

    summary_text = sanitize_text(summary_text_raw)
    summary_text = truncate_to_token_limit(summary_text, pipeline.embedding_effective_limit, pipeline.tokenizer_model_name)
    summary_hash = generate_hash(summary_text)
    file_info = pipeline._current_file_info or gather_file_metadata(getattr(code_loader, "path", None))

    if vector_store_contains(pipeline.vector_store, summary_hash):
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

    try:
        pipeline.vector_store.upsert(
            summary_hash,
            embedding,
            metadata,
            tenant_id=pipeline.tenant_id,  # type: ignore[arg-type]
        )
    except TypeError:
        pipeline.vector_store.upsert(summary_hash, embedding, metadata)

    finalize_file_ingestion(pipeline, file_info, chunk_total=1)


__all__ = ["process_code_document"]
