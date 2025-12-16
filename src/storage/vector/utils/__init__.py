"""Helpers for preparing documents and metadata before persisting to storage."""

from src.utils.splitting import prepare_embedding_segments
from src.utils.file_operations import gather_file_metadata, sort_paths_by_size_desc
from src.utils.text import (
    coerce_datetime,
    sanitize_text,
    generate_hash_presanitized,
    truncate_to_token_limit,
    truncate_to_token_limit_presanitized,
    effective_limit,
)
from src.utils.hashing import generate_hash
from src.utils.metadata import prune_metadata, vector_store_contains, vector_store_batch_contains

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
