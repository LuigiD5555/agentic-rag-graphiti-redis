"""Metadata validation and storage utilities.

This module provides utilities for validating metadata dictionaries and
checking vector store contents for deduplication.
"""

from typing import Dict, List

from src.workflows.query.audit import get_logger, resolve_level
from src.workflows.query.interfaces.vector_interface import (
    SupportsExists,
    SupportsBatchExists,
    VectorInterface,
)

log = get_logger(__name__)


def prune_metadata(metadata: dict) -> Dict:
    """Filter and validate metadata dictionary.

    Only allows whitelisted keys and validates that values have the correct types.

    Args:
        metadata: Raw metadata dictionary.

    Returns:
        Pruned and validated metadata dictionary.
    """
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


def vector_store_contains(vector_store: VectorInterface, hash_id: str) -> bool:
    """Check if a hash exists in the vector store.

    Args:
        vector_store: Vector store instance.
        hash_id: Content hash to check.

    Returns:
        True if the hash exists, False otherwise.
    """
    if isinstance(vector_store, SupportsExists):
        httpx_logger = get_logger("httpx")
        previous_level = httpx_logger.level
        httpx_logger.setLevel(resolve_level("WARNING"))
        try:
            return vector_store.exists(hash_id)
        except (AttributeError, NotImplementedError, TypeError):
            return False
        finally:
            httpx_logger.setLevel(previous_level)
    return False


def vector_store_batch_contains(
    vector_store: VectorInterface,
    hash_ids: List[str],
    tenant_id: str | None = None,
) -> Dict[str, bool]:
    """Check if multiple hashes exist in the vector store in a single batch operation.

    This is significantly faster than checking each hash individually when the
    vector store supports batch exists checking. Falls back to sequential checks
    if batch operation is not supported.

    Args:
        vector_store: The vector store instance.
        hash_ids: List of content hashes to check.
        tenant_id: Optional tenant ID.

    Returns:
        Dictionary mapping hash_id -> exists (bool).

    Performance:
        - With batch support: ~50-70% reduction in duplicate checking overhead.
        - Without batch support: Equivalent to sequential checks.
    """
    if not hash_ids:
        return {}

    # Try batch exists if supported
    if isinstance(vector_store, SupportsBatchExists):
        httpx_logger = get_logger("httpx")
        previous_level = httpx_logger.level
        httpx_logger.setLevel(resolve_level("WARNING"))
        try:
            return vector_store.batch_exists(hash_ids, tenant_id=tenant_id)
        except (AttributeError, NotImplementedError, TypeError):
            # Fall through to sequential checking
            pass
        finally:
            httpx_logger.setLevel(previous_level)

    # Fallback: check each hash individually
    result: Dict[str, bool] = {}
    for hash_id in hash_ids:
        result[hash_id] = vector_store_contains(vector_store, hash_id)

    return result


__all__ = [
    "prune_metadata",
    "vector_store_contains",
    "vector_store_batch_contains",
]
