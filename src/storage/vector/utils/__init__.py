"""Helpers for preparing documents and metadata before persisting to storage."""

from .chunking import prepare_embedding_segments
from .file_metadata import gather_file_metadata, coerce_datetime
from .file_ordering import sort_paths_by_size_desc
from .metadata_utils import prune_metadata
from .storage_utils import vector_store_contains, vector_store_batch_contains
from .text_utils import (
    sanitize_text,
    generate_hash,
    generate_hash_presanitized,
    truncate_to_token_limit,
    truncate_to_token_limit_presanitized,
    effective_limit,
)

__all__ = [
    "prepare_embedding_segments",
    "gather_file_metadata",
    "coerce_datetime",
    "sort_paths_by_size_desc",
    "prune_metadata",
    "vector_store_contains",
    "vector_store_batch_contains",
    "sanitize_text",
    "generate_hash",
    "generate_hash_presanitized",
    "truncate_to_token_limit",
    "truncate_to_token_limit_presanitized",
    "effective_limit",
]
