from __future__ import annotations

from typing import Dict


def prune_metadata(metadata: dict) -> Dict:
    allowed_keys = {
        "content",
        "source",
        "visibility",
        "owner_id",
        "allowed_user_ids",
        "hash",
        "file_path",
        "file_name",
        "file_extension",
        "parent_directory",
        "file_size_bytes",
        "file_modified_at",
        "file_id",
        "chunk_index",
        "chunk_total",
        "ingested_at",
        "directory_file_index",
        "directory_total_files",
        "archived",
    }
    pruned: dict = {}

    def _set_str(key: str) -> None:
        value = metadata.get(key)
        if isinstance(value, str):
            pruned[key] = value

    def _set_int(key: str) -> None:
        value = metadata.get(key)
        if isinstance(value, int) and value >= 0:
            pruned[key] = value

    _set_str("content")
    _set_str("source")
    _set_str("visibility")
    _set_str("owner_id")

    value = metadata.get("allowed_user_ids")
    if value is None:
        pass
    elif isinstance(value, list):
        pruned["allowed_user_ids"] = [str(x) for x in value]
    elif isinstance(value, str):
        pruned["allowed_user_ids"] = [value]

    _set_str("hash")
    _set_str("file_path")
    _set_str("file_name")
    _set_str("file_extension")
    _set_str("parent_directory")
    _set_int("file_size_bytes")
    _set_str("file_modified_at")
    _set_str("file_id")
    _set_int("chunk_index")
    _set_int("chunk_total")
    _set_str("ingested_at")
    _set_int("directory_file_index")
    _set_int("directory_total_files")
    value = metadata.get("archived")
    if isinstance(value, bool):
        pruned["archived"] = value

    for key in list(pruned.keys()):
        if key not in allowed_keys:
            pruned.pop(key, None)

    return pruned


__all__ = ["prune_metadata"]
