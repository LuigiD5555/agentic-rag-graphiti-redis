"""
Centralized utilities for the RAG Agentic Graphiti project.

This package contains reusable utility functions organized by functionality:
- hashing: File, directory, and text hashing utilities
- text: Text processing, sanitization, and token management
- splitting: Document splitting and chunking utilities
- file_operations: File metadata and path operations
- metadata: Metadata validation and storage utilities
- path_discovery: Path discovery, exclusions, and filtering
- language_routing: Script detection and language-specific splitting
- progress: Progress tracking and reporting utilities
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

from .splitting import (
    prepare_embedding_segments,
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
    load_enabled_paths_from_files,
)

from .language_routing import (
    ScriptFamily,
    TextProfile,
    SplitPolicy,
    TextProfiler,
    CjkTextSplitter,
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
    # Splitting
    "prepare_embedding_segments",
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
    "load_enabled_paths_from_files",
    # Language Routing
    "ScriptFamily",
    "TextProfile",
    "SplitPolicy",
    "TextProfiler",
    "CjkTextSplitter",
]
