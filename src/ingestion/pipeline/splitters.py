from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, cast

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
    TokenTextSplitter,
)
try:
    from langchain_core.documents import Document
except ImportError:
    from langchain.schema import Document  # type: ignore

try:
    from langchain_experimental.text_splitter import SemanticChunker  # type: ignore
except ImportError:
    SemanticChunker = None  # type: ignore

from src.cli.options import PipelineOptions


class SplitterStrategy(str, Enum):
    TOKEN = "token"
    RECURSIVE = "recursive"
    MARKDOWN_HEADERS = "md_headers"
    SEMANTIC = "semantic"


def normalize_markdown_headers(levels: Optional[object]) -> List[Tuple[str, str]]:
    if levels is None:
        return [("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]

    if isinstance(levels, dict):
        return [(str(header), str(label)) for header, label in levels.items()]

    if isinstance(levels, (list, tuple)):
        normalized = []
        for entry in levels:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ValueError("markdown_levels entries must be (separator, label) pairs.")
            header, label = entry
            normalized.append((str(header), str(label)))
        return normalized

    raise TypeError("markdown_levels must be None, a dict, or a sequence of (separator, label) pairs.")


def build_text_splitter(
    strategy: SplitterStrategy,
    options: PipelineOptions,
    markdown_levels: Optional[object],
) -> object:
    md_levels = normalize_markdown_headers(markdown_levels)
    builders: Dict[SplitterStrategy, Callable[[], object]] = {
        SplitterStrategy.TOKEN: lambda: TokenTextSplitter(
            chunk_size=options.chunk_size,
            chunk_overlap=options.chunk_overlap,
            model_name=options.tokenizer_model_name,
        ),
        SplitterStrategy.RECURSIVE: lambda: RecursiveCharacterTextSplitter(
            chunk_size=options.chunk_size,
            chunk_overlap=options.chunk_overlap,
        ),
        SplitterStrategy.MARKDOWN_HEADERS: lambda: MarkdownHeaderTextSplitter(
            headers_to_split_on=md_levels,
        ),
    }

    if SemanticChunker is not None:
        builders[SplitterStrategy.SEMANTIC] = lambda: build_semantic_splitter(options)

    builder = builders.get(strategy)
    if builder is None:
        raise ValueError(f"Unknown splitting strategy: {strategy}")
    return builder()


def build_semantic_splitter(options: PipelineOptions) -> Any:
    if SemanticChunker is None:
        raise RuntimeError("SemanticChunker is unavailable; install langchain_experimental.")

    embeddings = options.semantic_embeddings
    if embeddings is None:
        raise ValueError("semantic_embeddings must be provided for semantic splitting.")

    return cast(
        Any,
        SemanticChunker(
            cast(Any, embeddings),
            breakpoint_threshold_type="percentile",
            buffer_size=options.chunk_overlap,
            number_of_chunks=getattr(options, "number_of_chunks", None),
            breakpoint_threshold_amount=getattr(options, "breakpoint_threshold_amount", None),
            add_start_index=True,
        ),
    )


def split_documents(splitter: object, documents: List[Document]) -> Iterable[Document]:
    if isinstance(splitter, MarkdownHeaderTextSplitter):
        for doc in documents:
            md_chunks = splitter.split_text(doc.page_content)
            for chunk in md_chunks:
                merged_meta = dict(doc.metadata or {})
                merged_meta.update(chunk.metadata or {})
                yield Document(page_content=chunk.page_content, metadata=merged_meta)
        return

    if hasattr(splitter, "split_documents"):
        yield from splitter.split_documents(documents)  # type: ignore[attr-defined]
        return

    yield from documents
