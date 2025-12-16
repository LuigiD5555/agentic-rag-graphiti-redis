"""Semantic splitter builder."""

from typing import Any

from langchain_experimental.text_splitter import SemanticChunker  # type: ignore

from src.rag.ingestion.options import PipelineOptions


def build_semantic_splitter(options: PipelineOptions) -> Any:
    embeddings = options.semantic_embeddings
    if embeddings is None:
        raise ValueError("semantic_embeddings must be provided for semantic splitting.")

    return SemanticChunker(
        embeddings,
        breakpoint_threshold_type="percentile",
        buffer_size=options.chunk_overlap,
        number_of_chunks=getattr(options, "number_of_chunks", None),
        breakpoint_threshold_amount=getattr(options, "breakpoint_threshold_amount", None),
        add_start_index=True,
    )


__all__ = ["build_semantic_splitter"]
