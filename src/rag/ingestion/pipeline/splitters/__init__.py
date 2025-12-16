"""Text splitter package.

Offline-first design:
- No TokenTextSplitter (tiktoken can download files).
- Strategies are explicit, no silent fallbacks.
"""

from .strategies import SplitterStrategy
from .builders import build_text_splitter
from .markdown import normalize_markdown_headers
from .semantic import build_semantic_splitter
from .split import split_documents, split_documents_with_progress

__all__ = [
    "SplitterStrategy",
    "build_text_splitter",
    "normalize_markdown_headers",
    "build_semantic_splitter",
    "split_documents",
    "split_documents_with_progress",
]
