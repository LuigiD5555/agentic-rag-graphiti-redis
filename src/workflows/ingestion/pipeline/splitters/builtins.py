"""
Built-in text splitter strategies.

This module registers the built-in text splitter strategies using the decorator pattern.
"""

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from src.workflows.ingestion.options import PipelineOptions
from .registry import register_splitter
from .strategies import SplitterStrategy
from .markdown import normalize_markdown_headers
from .semantic import build_semantic_splitter


@register_splitter(SplitterStrategy.RECURSIVE)
def build_recursive_splitter(options: PipelineOptions, markdown_levels: object) -> object:
    """
    Build a recursive character text splitter.
    
    Args:
        options: Pipeline options with chunk_size and chunk_overlap
        markdown_levels: Unused for this strategy
        
    Returns:
        RecursiveCharacterTextSplitter instance
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=options.chunk_size,
        chunk_overlap=options.chunk_overlap,
    )


@register_splitter(SplitterStrategy.MARKDOWN_HEADERS)
def build_markdown_headers_splitter(options: PipelineOptions, markdown_levels: object) -> object:
    """
    Build a markdown headers text splitter.
    
    Args:
        options: Pipeline options (unused for this strategy)
        markdown_levels: Markdown header levels configuration
        
    Returns:
        MarkdownHeaderTextSplitter instance
    """
    headers = normalize_markdown_headers(markdown_levels)
    return MarkdownHeaderTextSplitter(headers_to_split_on=headers)


@register_splitter(SplitterStrategy.SEMANTIC)
def build_semantic_splitter_wrapper(options: PipelineOptions, markdown_levels: object) -> object:
    """
    Build a semantic text splitter.
    
    Args:
        options: Pipeline options for semantic splitter configuration
        markdown_levels: Unused for this strategy
        
    Returns:
        Semantic text splitter instance
    """
    return build_semantic_splitter(options)