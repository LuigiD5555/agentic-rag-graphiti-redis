"""Splitter builder (offline-first)."""

from typing import Optional

from src.workflows.ingestion.options import PipelineOptions

from .strategies import SplitterStrategy
from .registry import ensure_builtin_splitters_loaded, get_splitter_factory


def build_text_splitter(
    strategy: SplitterStrategy,
    options: PipelineOptions,
    markdown_levels: Optional[object],
) -> object:
    """
    Build a text splitter based on the specified strategy.
    
    Args:
        strategy: Splitter strategy
        options: Pipeline options
        markdown_levels: Markdown header levels configuration (optional)
        
    Returns:
        Text splitter instance
        
    Raises:
        KeyError: If strategy is not registered
    """
    # Ensure built-in splitters are loaded
    ensure_builtin_splitters_loaded()
    
    # Get factory from registry
    factory = get_splitter_factory(strategy)
    
    # Create and return splitter instance
    return factory(options, markdown_levels)


__all__ = ["build_text_splitter"]
