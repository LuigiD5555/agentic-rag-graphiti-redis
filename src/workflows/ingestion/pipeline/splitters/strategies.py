"""Splitter strategy identifiers (offline-first)."""

from enum import Enum


class SplitterStrategy(str, Enum):
    RECURSIVE = "recursive"
    MARKDOWN_HEADERS = "md_headers"
    SEMANTIC = "semantic"


__all__ = ["SplitterStrategy"]
