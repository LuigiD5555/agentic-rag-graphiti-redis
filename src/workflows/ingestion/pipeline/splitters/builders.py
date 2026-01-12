"""Splitter builder (offline-first)."""

from typing import Optional

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from src.workflows.ingestion.options import PipelineOptions

from .strategies import SplitterStrategy
from .markdown import normalize_markdown_headers
from .semantic import build_semantic_splitter


def build_text_splitter(
    strategy: SplitterStrategy,
    options: PipelineOptions,
    markdown_levels: Optional[object],
) -> object:
    if strategy == SplitterStrategy.RECURSIVE:
        return RecursiveCharacterTextSplitter(
            chunk_size=options.chunk_size,
            chunk_overlap=options.chunk_overlap,
        )

    if strategy == SplitterStrategy.MARKDOWN_HEADERS:
        headers = normalize_markdown_headers(markdown_levels)
        return MarkdownHeaderTextSplitter(headers_to_split_on=headers)

    if strategy == SplitterStrategy.SEMANTIC:
        return build_semantic_splitter(options)

    raise ValueError(f"Unknown splitting strategy: {strategy}")


__all__ = ["build_text_splitter"]
