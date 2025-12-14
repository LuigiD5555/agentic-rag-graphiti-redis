from __future__ import annotations

import os
from typing import Iterable, List


def sort_paths_by_size_desc(paths: Iterable[str]) -> List[str]:
    """
    Order paths from largest to smallest file size.

    Ties on size are broken alphabetically (case-insensitive) to ensure
    deterministic processing. Missing/inaccessible files are treated as size 0.
    """
    sizes: dict[str, int] = {}
    for path in paths:
        try:
            sizes[path] = os.path.getsize(path)
        except OSError:
            sizes[path] = 0

    return sorted(
        paths,
        key=lambda p: (-sizes[p], p.lower()),
    )


__all__ = ["sort_paths_by_size_desc"]
