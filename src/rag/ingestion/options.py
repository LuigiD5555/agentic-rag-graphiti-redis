from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import for type hints only
    from src.rag.ingestion.pipeline import SplitterStrategy


@dataclass(frozen=True)
class DiscoveryOptions:
    """
    Parameters that control filesystem discovery.

    Attributes:
        roots: Root directories or individual files to inspect.
        enabled_paths: Specific paths to enable (whitelist). If empty, all roots are enabled.
        allowed_exts: File extensions to include (lowercase, with leading dot). Empty set means "all".
        excluded_dirs: Directory names to prune during traversal (e.g., {".git", "node_modules"}).
        excluded_globs: Path-like glob patterns (relative to each root) to exclude.
        follow_symlinks: Whether to follow symlinked directories.
        progress_every: Log a scan progress line every N visited directories (0 disables).
    """
    roots: Tuple[str, ...]
    enabled_paths: Tuple[str, ...] = field(default_factory=tuple)
    allowed_exts: Set[str] = field(default_factory=set)
    excluded_dirs: Set[str] = field(default_factory=set)
    excluded_globs: Set[str] = field(default_factory=set)
    follow_symlinks: bool = False
    progress_every: int = 0


@dataclass(frozen=True)
class IngestionOptions:
    """
    End-to-end ingestion options (discovery + execution).

    Attributes:
        root_paths: Root directories or files to ingest.
        enabled_paths: Specific paths to enable (whitelist). If empty, all root_paths are enabled.
        allowed_extensions: Included extensions for discovery.
        excluded_directory_names: Directory names to exclude during scan.
        excluded_path_globs: Glob-like relative patterns to exclude.
        follow_symbolic_links: Follow symlinks during discovery.
        dry_run: Only list candidates; do not ingest.
        per_file_mode: Ingest one file at a time (more logs, slower) vs batch.
        maximum_files: Cap number of files to ingest (0 = no limit).
        log_level_name: Logging level name.
        scan_progress_every: Scan progress cadence (0 disables).
    """
    root_paths: Tuple[str, ...]
    enabled_paths: Tuple[str, ...] = field(default_factory=tuple)
    allowed_extensions: Set[str] = field(default_factory=set)
    excluded_directory_names: Set[str] = field(
        default_factory=lambda: {
            ".git",
            ".hg",
            ".svn",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            ".idea",
            ".vscode",
        }
    )
    excluded_path_globs: Set[str] = field(default_factory=set)
    follow_symbolic_links: bool = False
    dry_run: bool = False
    per_file_mode: bool = False
    maximum_files: int = 0
    log_level_name: str = "INFO"
    scan_progress_every: int = 0


@dataclass(frozen=True)
class PipelineOptions:
    """Configuration for IngestionPipeline construction."""

    chunk_size: int
    chunk_overlap: int
    embedding_token_limit: int = 0
    tenant_id: Optional[str] = None
    owner_id: Optional[str] = None
    visibility: str = "private"
    allowed_user_ids: List[str] = field(default_factory=list)
    splitter_strategy: Optional["SplitterStrategy"] = None
    tokenizer_model_name: str = "gpt-4o-mini"
    markdown_levels: Optional[object] = None
    semantic_embeddings: Optional[object] = None


__all__ = ["DiscoveryOptions", "IngestionOptions", "PipelineOptions"]
