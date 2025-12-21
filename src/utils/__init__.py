"""
Centralized utilities for the RAG Agentic Graphiti project.

This package contains reusable utility functions organized by functionality:
- hashing: File, directory, and text hashing utilities
- text: Text processing, sanitization, and token management
- file_operations: File metadata and path operations
- metadata: Metadata validation and storage utilities
- path_discovery: Path discovery, exclusions, and filtering
- progress: Progress tracking and reporting utilities

Note: Ingestion-specific utilities (text_reading, language_routing, splitting)
have been moved to src.ingestion.pipeline.utils for better organization.
"""

from .hashing import (
    compute_file_hash,
    compute_directory_hash,
    generate_hash,
    generate_hash_presanitized,
)

from .text import (
    sanitize_text,
    effective_limit,
    truncate_to_token_limit,
    truncate_to_token_limit_presanitized,
    coerce_datetime,
)

from .file_operations import (
    gather_file_metadata,
    sort_paths_by_size_desc,
    should_skip_path,
)

from .metadata import (
    prune_metadata,
    vector_store_contains,
    vector_store_batch_contains,
)

from .progress import (
    progress_ratio,
    render_bar,
    ProgressBar,
)

from .path_discovery import (
    parse_list_env,
    value_as_list,
    load_excludes_from_files,
    read_exclude_file,
    classify_exclude_entries,
    is_glob_like,
)

__all__ = [
    # Hashing
    "compute_file_hash",
    "compute_directory_hash",
    "generate_hash",
    "generate_hash_presanitized",
    # Text
    "sanitize_text",
    "effective_limit",
    "truncate_to_token_limit",
    "truncate_to_token_limit_presanitized",
    "coerce_datetime",
    # File Operations
    "gather_file_metadata",
    "sort_paths_by_size_desc",
    "should_skip_path",
    # Metadata
    "prune_metadata",
    "vector_store_contains",
    "vector_store_batch_contains",
    # Progress
    "progress_ratio",
    "render_bar",
    "ProgressBar",
    # Path Discovery
    "parse_list_env",
    "value_as_list",
    "load_excludes_from_files",
    "read_exclude_file",
    "classify_exclude_entries",
    "is_glob_like",
]
