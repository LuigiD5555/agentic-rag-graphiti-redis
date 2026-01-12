"""Markdown header helpers."""

from typing import List, Optional, Tuple


def normalize_markdown_headers(levels: Optional[object]) -> List[Tuple[str, str]]:
    """Normalize markdown header configuration into a list of (separator, label) pairs."""
    if levels is None:
        return [("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]

    if isinstance(levels, dict):
        return [(str(header), str(label)) for header, label in levels.items()]

    if isinstance(levels, (list, tuple)):
        normalized: List[Tuple[str, str]] = []
        for entry in levels:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ValueError("markdown_levels entries must be (separator, label) pairs.")
            header, label = entry
            normalized.append((str(header), str(label)))
        return normalized

    raise TypeError("markdown_levels must be None, a dict, or a sequence of (separator, label) pairs.")


__all__ = ["normalize_markdown_headers"]
