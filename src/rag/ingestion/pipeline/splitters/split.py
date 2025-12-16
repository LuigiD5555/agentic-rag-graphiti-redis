"""Split execution helpers (with progress)."""

import time
from typing import Iterable, List, Iterator, Protocol, Any, Callable
from collections.abc import Sequence

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter

from src import logger


# Protocol para type checking
class TextSplitter(Protocol):
    """Protocol para splitters que tienen método split_documents."""
    def split_documents(self, documents: List[Document]) -> List[Document]:
        ...


# ============================================================================
# CORE HELPER FUNCTIONS (DRY - Don't Repeat Yourself)
# ============================================================================

def _process_markdown_doc(doc: Document, splitter: MarkdownHeaderTextSplitter) -> List[Document]:
    """Process a single document with MarkdownHeaderTextSplitter.

    Centralized logic to avoid duplication across 5+ functions.
    """
    base_meta = doc.metadata or {}
    parts = splitter.split_text(doc.page_content)

    return [
        Document(
            page_content=chunk.page_content,
            metadata=base_meta | (chunk.metadata or {})
        )
        for chunk in parts
    ]


def _split_batch_core(
    splitter: Any,
    documents: Sequence[Document],
    is_markdown: bool,
    has_split_method: bool,
) -> List[Document]:
    """Core splitting logic without I/O or logging.

    Centralized to avoid duplication in batch processing functions.
    """
    if is_markdown:
        chunks: List[Document] = []
        for doc in documents:
            chunks.extend(_process_markdown_doc(doc, splitter))
        return chunks

    if has_split_method:
        return splitter.split_documents(list(documents))

    return list(documents)


def _create_progress_logger(
    source: str,
    file_prefix: str,
    start_time: float,
    parallel: bool = False,
) -> Callable[[int, int, int], None]:
    """Factory function that creates a progress logger closure.

    Returns a function that logs progress without repeating logging logic.
    """
    log_prefix = f"{file_prefix} " if file_prefix else ""
    mode_label = "[PARALLEL]" if parallel else ""

    def log(processed: int, total_docs: int, chunks_count: int) -> None:
        elapsed = max(0.001, time.monotonic() - start_time)
        rate = processed / elapsed
        remaining = total_docs - processed
        eta = (remaining / rate) if rate > 0 else -1.0
        pct = (processed / total_docs) * 100.0 if total_docs > 0 else 100.0

        logger.info(
            "%sSplit progress %s: docs=%d/%d (%.2f%%), chunks=%d, elapsed=%.0fs, eta=%.0fs - %s",
            log_prefix, mode_label, processed, total_docs, pct, chunks_count, elapsed, eta, source
        )

    return log


def split_documents(
    splitter: Any,
    documents: Sequence[Document]
) -> Iterator[Document]:
    """Basic split without progress."""
    if isinstance(splitter, MarkdownHeaderTextSplitter):
        for doc in documents:
            yield from _process_markdown_doc(doc, splitter)
        return

    if hasattr(splitter, "split_documents"):
        yield from splitter.split_documents(documents)
        return

    yield from documents


def split_documents_fast(
    splitter: Any,
    documents: Sequence[Document],
) -> List[Document]:
    """Fast version without progress for internal use."""
    is_markdown = isinstance(splitter, MarkdownHeaderTextSplitter)
    has_split_method = hasattr(splitter, "split_documents")
    return _split_batch_core(splitter, documents, is_markdown, has_split_method)


def split_documents_with_progress(
    splitter: Any,
    documents: List[Document],
    *,
    source: str,
    file_prefix: str = "",
    batch_size: int = 512,
    log_every_batches: int = 5,
) -> List[Document]:
    """Split in batches and log progress + ETA."""
    total_docs = len(documents)
    if total_docs == 0:
        return []

    start = time.monotonic()
    chunks: List[Document] = []
    processed = 0

    # Use centralized logger
    log = _create_progress_logger(source, file_prefix, start)

    # Pre-check splitter type once
    is_markdown = isinstance(splitter, MarkdownHeaderTextSplitter)
    has_split_method = hasattr(splitter, "split_documents")

    # Process in batches using centralized logic
    for i in range(0, total_docs, batch_size):
        batch_end = min(i + batch_size, total_docs)
        batch = documents[i:batch_end]

        # Use centralized batch processing
        batch_chunks = _split_batch_core(splitter, batch, is_markdown, has_split_method)
        chunks.extend(batch_chunks)

        processed = batch_end

        batch_number = (i // batch_size) + 1
        if batch_number % log_every_batches == 0:
            log(processed, total_docs, len(chunks))

    log(processed, total_docs, len(chunks))
    return chunks


def split_documents_with_progress_parallel(
    splitter: Any,
    documents: List[Document],
    *,
    source: str,
    file_prefix: str = "",
    batch_size: int = 512,
    log_every_batches: int = 5,
    num_workers: int = 4,
) -> List[Document]:
    """Parallel version for very large datasets (experimental)."""
    from concurrent.futures import ProcessPoolExecutor, as_completed

    total_docs = len(documents)
    if total_docs == 0:
        return []

    # If dataset is small, use sequential version
    if total_docs < batch_size * 4:
        return split_documents_with_progress(
            splitter, documents, source=source,
            file_prefix=file_prefix, batch_size=batch_size,
            log_every_batches=log_every_batches
        )

    start = time.monotonic()
    chunks: List[Document] = []
    processed = 0

    # Use centralized logger with parallel flag
    log = _create_progress_logger(source, file_prefix, start, parallel=True)

    # Divide into chunks for parallel processing
    batches = [documents[i:i + batch_size] for i in range(0, total_docs, batch_size)]

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        # Submit all batches
        futures = {
            executor.submit(split_documents_fast, splitter, batch): idx
            for idx, batch in enumerate(batches)
        }

        # Process results as they complete
        results: dict[int, List[Document]] = {}
        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                batch_chunks = future.result()
                results[batch_idx] = batch_chunks
                processed += len(batches[batch_idx])

                if (batch_idx + 1) % log_every_batches == 0:
                    log(processed, total_docs, len(chunks))
            except Exception as e:
                logger.error("Error processing batch %d: %s", batch_idx, e)
                results[batch_idx] = []

        # Reconstruct in original order
        for idx in sorted(results.keys()):
            chunks.extend(results[idx])

    log(processed, total_docs, len(chunks))
    return chunks


def split_documents_streaming(
    splitter: Any,
    documents: Iterable[Document],
    *,
    source: str,
    file_prefix: str = "",
    log_every_docs: int = 1000,
) -> Iterator[Document]:
    """Streaming version for very large documents without loading everything into memory."""
    start = time.monotonic()
    processed = 0
    chunks_yielded = 0
    log_prefix = f"{file_prefix} " if file_prefix else ""

    is_markdown = isinstance(splitter, MarkdownHeaderTextSplitter)
    has_split_method = hasattr(splitter, "split_documents")

    def log() -> None:
        elapsed = max(0.001, time.monotonic() - start)
        rate = processed / elapsed
        logger.info(
            "%sSplit streaming: docs=%d, chunks=%d, rate=%.1f docs/s, elapsed=%.0fs - %s",
            log_prefix, processed, chunks_yielded, rate, elapsed, source
        )

    for doc in documents:
        if is_markdown:
            # Use centralized markdown processing
            doc_chunks = _process_markdown_doc(doc, splitter)
            for chunk in doc_chunks:
                yield chunk
                chunks_yielded += 1
        elif has_split_method:
            # For splitters that expect a list, process one at a time
            split_result = splitter.split_documents([doc])
            for chunk in split_result:
                yield chunk
                chunks_yielded += 1
        else:
            yield doc
            chunks_yielded += 1

        processed += 1
        if processed % log_every_docs == 0:
            log()

    log()


__all__ = [
    "split_documents", 
    "split_documents_with_progress",
    "split_documents_with_progress_parallel",
    "split_documents_streaming",
    "split_documents_fast"
]