"""Pipeline utilities for text processing and language routing.

This package contains utilities specific to the ingestion pipeline that are not
generally useful across the entire codebase.
"""

from .language_routing import TextProfiler, detect_script_families
from .splitting import prepare_embedding_segments
from .text_reading import TextReadResult, read_text_with_fallbacks

__all__ = [
    "TextProfiler",
    "TextReadResult",
    "detect_script_families",
    "prepare_embedding_segments",
    "read_text_with_fallbacks",
]
