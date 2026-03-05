"""Text document ingestion steps.

This module handles ingestion of non-code documents:
1) Load documents using a loader.
2) Split into chunks.
3) Split oversized chunks to honor the embedding token limit.
4) Generate embeddings and upsert into the vector store.

It logs stage-level progress so long-running loaders/splitters do not appear
"stuck" in container logs.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict
import time

from src import logger
from src.conf import settings

from src.workflows.ingestion.loaders.helpers import call_loader, resolve_loader_source
from .splitters import split_documents
from .stage_reporting import IngestionFileContext, IngestionStageReporter
from src.workflows.ingestion.discovery.score_cache import set_file_score


def _score_file(pipeline, source: str, score: int, reason: str) -> None:
    """Write a file score; silently ignores all errors."""
    try:
        import os
        exts_hash = getattr(pipeline, "_exts_hash", "") or ""
        if not exts_hash:
            try:
                from src.workflows.ingestion.discovery.score_cache import compute_exts_hash
                import src.settings as _settings
                exts_hash = compute_exts_hash(_settings)
                pipeline._exts_hash = exts_hash
            except Exception:
                pass
        mtime = os.stat(source).st_mtime
        set_file_score(source, mtime, score, reason, exts_hash)
    except Exception as exc:
        logger.debug("score_cache write failed for %s: %s", source, exc)
from .state_helpers import finalize_file_ingestion
from .utils.splitting import prepare_embedding_segments
from src.utils.file_operations import gather_file_metadata
from src.utils.hashing import generate_hash_presanitized
from src.utils.metadata import prune_metadata, vector_store_contains
from src.utils.text import (
    sanitize_text,
    truncate_to_token_limit_presanitized,
)


def _resolve_file_context(pipeline: Any) -> IngestionFileContext:
    """Build an IngestionFileContext from the pipeline's internal context."""
    context: Dict[str, Any] = getattr(pipeline, "_file_context", {}) or {}
    return IngestionFileContext(
        file_index=context.get("file_index"),
        total_files=context.get("total_files"),
    )


def _log_with_file_prefix(file_context: IngestionFileContext, message: str, *args: object) -> None:
    """Log a message prefixed with file position information when available."""
    prefix = file_context.format_prefix()
    if prefix:
        logger.info("%s " + message, prefix, *args)
        return
    logger.info(message, *args)




def _format_eta_seconds(seconds: float | None) -> str:
    """Format ETA seconds for logs."""
    if seconds is None:
        return "N/A"
    if seconds < 0:
        return "N/A"
    return f"{seconds:.0f}s"


def _split_documents_with_progress(
    *,
    splitter: object,
    documents: list[object],
    source: str,
    file_context: IngestionFileContext,
) -> list[object]:
    """Split documents in batches and log progress with ETA.

    This function provides progress visibility even when splitting is expensive.
    It uses the existing `split_documents()` helper, but processes in batches so
    we can compute progress/ETA and avoid silent long stages.

    LangChain splitters typically expose `split_documents(documents)` which
    returns a list of chunks. :contentReference[oaicite:1]{index=1}

    Environment variables:
        RAG_SPLIT_BATCH_SIZE (default: 128)
        RAG_SPLIT_LOG_EVERY_SECONDS (default: 15)

    Args:
        splitter: Splitter instance used by `split_documents`.
        documents: Loaded LangChain Document-like objects.
        source: Source identifier (path).
        file_context: File context for prefixing log lines.

    Returns:
        List of chunk Documents.
    """
    total_docs = len(documents)
    if total_docs == 0:
        return []

    batch_size = settings.RAG_SPLIT_BATCH_SIZE
    if batch_size <= 0:
        raise ValueError("RAG_SPLIT_BATCH_SIZE must be a positive integer")

    log_every_seconds = settings.RAG_SPLIT_LOG_EVERY_SECONDS
    if log_every_seconds <= 0:
        raise ValueError("RAG_SPLIT_LOG_EVERY_SECONDS must be a positive integer")

    started_at = time.monotonic()
    next_log_at = started_at + float(log_every_seconds)

    processed_docs = 0
    produced_chunks = 0
    chunks: list[object] = []

    for start in range(0, total_docs, batch_size):
        end = min(total_docs, start + batch_size)
        batch = documents[start:end]

        batch_chunks = list(split_documents(splitter, batch))
        chunks.extend(batch_chunks)

        processed_docs += len(batch)
        produced_chunks = len(chunks)

        now = time.monotonic()
        should_log = now >= next_log_at or processed_docs >= total_docs
        if should_log:
            elapsed = max(0.001, now - started_at)
            rate = processed_docs / elapsed
            remaining = max(0, total_docs - processed_docs)
            eta_seconds = (remaining / rate) if rate > 0 else None
            percent = (processed_docs / total_docs) * 100.0

            # Create visual progress bar
            bar_width = 25
            filled = int(bar_width * percent / 100)
            bar = "#" * filled + "." * (bar_width - filled)

            _log_with_file_prefix(
                file_context,
                "Split progress: [%s] %d/%d docs (%.1f%%), %d chunks, eta=%s - %s",
                bar,
                processed_docs,
                total_docs,
                percent,
                produced_chunks,
                _format_eta_seconds(eta_seconds),
                source,
            )
            next_log_at = now + float(log_every_seconds)

    return chunks


def process_text_document(pipeline: Any, loader: object) -> None:
    """Ingest a text-like document using the configured splitter and embedding service.

    Args:
        pipeline: The active IngestionPipeline instance.
        loader: Loader instance with a `.load()` method returning LangChain Documents.

    Returns:
        None
    """
    source = resolve_loader_source(loader)
    file_context = _resolve_file_context(pipeline)

    with IngestionStageReporter(
        logger=logger,
        stage_name="load",
        source=source,
        file_context=file_context,
        heartbeat_seconds=15.0,
    ):
        documents = call_loader(pipeline, loader, "load")

    if not documents:
        _score_file(pipeline, source, 0, "no_text")
        pipeline.progress.add_total(0, source=source)
        pipeline._current_file_info = None
        return

    document_count = len(documents)
    _log_with_file_prefix(file_context, "Loaded %d document(s) from %s", document_count, source)

    # Guardrail: prevent pathological loaders (e.g., CSV row-per-document) from
    # bringing ingestion to a halt. In LangChain CSV loaders, one row can become
    # one Document. :contentReference[oaicite:2]{index=2}
    max_docs_per_file = settings.RAG_MAX_DOCS_PER_FILE
    if max_docs_per_file > 0 and document_count > max_docs_per_file:
        logger.warning(
            "%s Skipping %s; loader returned %d documents which exceeds RAG_MAX_DOCS_PER_FILE=%d.",
            file_context.format_prefix(),
            source,
            document_count,
            max_docs_per_file,
        )
        pipeline.progress.add_total(0, source=source)
        pipeline._current_file_info = None
        return

    with IngestionStageReporter(
        logger=logger,
        stage_name="split",
        source=source,
        file_context=file_context,
        heartbeat_seconds=15.0,
    ):
        chunks = _split_documents_with_progress(
            splitter=pipeline.text_splitter,
            documents=documents,
            source=source,
            file_context=file_context,
        )

    if not chunks:
        logger.warning("Skipping %s; no chunks produced after splitting.", source)
        _score_file(pipeline, source, 0, "no_chunks")
        pipeline.progress.add_total(0, source=source)
        pipeline._current_file_info = None
        return

    _log_with_file_prefix(file_context, "Split into %d chunk(s) from %s", len(chunks), source)

    # Ledger: mark CHUNK stage done
    ledger = getattr(pipeline, "ledger", None)
    if ledger is not None:
        try:
            from src.ingestion.ledger.ledger_repository import Stage
            doc_id = ledger.get_or_create_document(source)
            active_version = ledger.get_active_version(doc_id)
            if active_version:
                ledger.mark_stage_done(active_version, Stage.CHUNK, int(time.time()))
        except Exception as _exc:
            logger.debug("Ledger CHUNK mark failed for %s: %s", source, _exc)

    with IngestionStageReporter(
        logger=logger,
        stage_name="prepare_segments",
        source=source,
        file_context=file_context,
        heartbeat_seconds=15.0,
    ):
        prepared_chunks = prepare_embedding_segments(chunks, pipeline.embedding_token_limit)

    if not prepared_chunks:
        logger.warning("Skipping %s; splitting produced no embedding-ready chunks.", source)
        _score_file(pipeline, source, 0, "no_embeddings")
        pipeline.progress.add_total(0, source=source)
        pipeline._current_file_info = None
        return

    segment_total = len(prepared_chunks)
    _log_with_file_prefix(file_context, "Prepared %d embedding segment(s) for %s", segment_total, source)

    pipeline.progress.add_total(segment_total, source=source)

    file_info = pipeline._current_file_info or gather_file_metadata(source)
    directory_path = (getattr(pipeline, "_file_context", {}) or {}).get("directory_path") or file_info.get(
        "parent_directory"
    )

    ingested_at = datetime.now(timezone.utc).isoformat()

    # Configure batching and logging
    batch_size = settings.RAG_EMBED_BATCH_SIZE
    log_every_n_chunks = settings.RAG_EMBED_LOG_EVERY_N_CHUNKS
    supports_batch = hasattr(pipeline.embedding_service, "generate_batch")

    with IngestionStageReporter(
        logger=logger,
        stage_name="embed+upsert",
        source=source,
        file_context=file_context,
        heartbeat_seconds=30.0,
    ):
        # Accumulate chunks for batching
        batch_records = []
        processed_count = 0
        skipped_count = 0

        for chunk_index, (segment_text, chunk_meta) in enumerate(prepared_chunks, start=1):
            # Sanitize once, then reuse for truncation and hashing (optimization)
            sanitized_text = sanitize_text(segment_text)
            truncated_text = truncate_to_token_limit_presanitized(
                sanitized_text,
                pipeline.embedding_effective_limit,
                pipeline.tokenizer_model_name,
            )
            content_hash = generate_hash_presanitized(truncated_text)

            # Skip duplicates (thread-safe)
            if pipeline.hash_exists(content_hash):
                skipped_count += 1
                continue
            if vector_store_contains(pipeline.vector_store, content_hash):
                pipeline.add_hash(content_hash)
                skipped_count += 1
                continue

            # Build metadata for this chunk
            raw_meta: Dict[str, Any] = dict(chunk_meta or {})
            source_value = str(raw_meta.get("source") or file_info.get("file_path") or "document")

            # Accumulate for batch processing
            batch_records.append({
                "text": truncated_text,
                "hash": content_hash,
                "source": source_value,
                "chunk_index": chunk_index,
                "chunk_meta": chunk_meta,
            })

            # Process batch when full or at end
            should_flush = (len(batch_records) >= batch_size) or (chunk_index == segment_total)

            if should_flush and batch_records:
                # Generate embeddings (batched if supported, sequential otherwise)
                texts = [r["text"] for r in batch_records]
                sources = [r["source"] for r in batch_records]
                chunk_indices = [r["chunk_index"] for r in batch_records]

                if supports_batch:
                    # Try to pass metadata to batch generation if supported
                    try:
                        embeddings = pipeline.embedding_service.generate_batch(
                            texts, sources=sources, chunk_indices=chunk_indices
                        )
                    except TypeError:
                        # Fallback if service doesn't support metadata parameters
                        embeddings = pipeline.embedding_service.generate_batch(texts)
                else:
                    # Sequential generation with metadata
                    embeddings = []
                    for r in batch_records:
                        try:
                            emb = pipeline.embedding_service.generate(
                                r["text"], source=r["source"], chunk_index=r["chunk_index"]
                            )
                        except TypeError:
                            # Fallback if service doesn't support metadata parameters
                            emb = pipeline.embedding_service.generate(r["text"])
                        embeddings.append(emb)

                # Upsert each record with its embedding
                for record, embedding in zip(batch_records, embeddings):
                    metadata: Dict[str, Any] = {
                        "content": record["text"],
                        "source": record["source"],
                        "visibility": str(pipeline.visibility),
                        "owner_id": str(pipeline.owner_id),
                        "allowed_user_ids": [str(u) for u in (pipeline.allowed_user_ids or [])],
                        "hash": record["hash"],
                        "file_path": file_info.get("file_path"),
                        "file_name": file_info.get("file_name"),
                        "file_extension": file_info.get("file_extension"),
                        "parent_directory": directory_path,
                        "file_size_bytes": file_info.get("file_size_bytes"),
                        "file_modified_at": file_info.get("file_modified_at"),
                        "file_id": file_info.get("file_id"),
                        "chunk_index": record["chunk_index"],
                        "chunk_total": segment_total,
                        "ingested_at": ingested_at,
                        "directory_file_index": file_context.file_index,
                        "directory_total_files": file_context.total_files,
                        "archived": False,
                    }
                    metadata = prune_metadata(metadata)

                    pipeline.vector_store.upsert(
                        record["hash"],
                        embedding,
                        metadata,
                        tenant_id=pipeline.tenant_id,
                    )

                    pipeline.add_hash(record["hash"])
                    processed_count += 1

                    # Only log progress every N chunks or on the last chunk
                    should_log = (record["chunk_index"] % log_every_n_chunks == 0) or (
                        record["chunk_index"] == segment_total
                    )
                    if should_log:
                        percent = (record["chunk_index"] / segment_total) * 100.0
                        bar_width = 25
                        filled = int(bar_width * percent / 100)
                        bar = "#" * filled + "." * (bar_width - filled)

                        # Create enhanced log line with progress bar
                        log_line = (
                            f"[{bar}] Embed+Upsert: {record['chunk_index']}/{segment_total} "
                            f"({percent:.1f}%) - {processed_count} new, {skipped_count} skipped - "
                            f"{os.path.basename(record['source'])}"
                        )

                        prefix = file_context.format_prefix()
                        if prefix:
                            logger.info("%s %s", prefix, log_line)
                        else:
                            logger.info(log_line)

                # Clear batch for next iteration
                batch_records.clear()

    # Ledger: mark EMBED stage done
    ledger = getattr(pipeline, "ledger", None)
    if ledger is not None:
        try:
            from src.ingestion.ledger.ledger_repository import Stage
            doc_id = ledger.get_or_create_document(source)
            active_version = ledger.get_active_version(doc_id)
            if active_version:
                ledger.mark_stage_done(active_version, Stage.EMBED, int(time.time()))
        except Exception as _exc:
            logger.debug("Ledger EMBED mark failed for %s: %s", source, _exc)

    _score_file(pipeline, source, 1, "extracted_ok")
    finalize_file_ingestion(pipeline, file_info, chunk_total=segment_total)

    # Update cache with processing results
    from .file_processor import _update_file_cache
    _update_file_cache(
        pipeline=pipeline,
        full_path=source,
        chunk_count=len(chunks),
        embedding_count=segment_total,
        status='processed'
    )


__all__ = ["process_text_document"]
