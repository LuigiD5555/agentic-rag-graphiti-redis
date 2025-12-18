"""Validation helpers for translating CLI args into ingestion options."""
import argparse

from src.ingestion.options import IngestionOptions
from src.settings import _DEFAULT_EXCLUDED_FILES


def build_ingestion_options_from_args(args: argparse.Namespace, config: object) -> IngestionOptions:
    """Derive IngestionOptions from CLI args and Config, with graceful fallbacks."""

    def _normalize_ext(ext: str) -> str:
        normalized = str(ext or "").strip().lower()
        if not normalized:
            return ""
        return normalized if normalized.startswith(".") else f".{normalized}"

    if getattr(args, "paths", None):
        root_paths = tuple(args.paths)
    else:
        cfg_paths = getattr(config, "DOCS_PATHS", None) or []
        root_paths = tuple(cfg_paths) if cfg_paths else ("/mnt/Documents/Documents",)

    if getattr(args, "exts", None) is not None:
        allowed_extensions = {_normalize_ext(e) for e in args.exts}
        allowed_extensions.discard("")
    else:
        cfg_exts = getattr(config, "DOCS_FILE_EXTS", []) or []
        allowed_extensions = {_normalize_ext(e) for e in cfg_exts} if cfg_exts else set()
        allowed_extensions.discard("")

    # Always start with built-in defaults, then add user-specified exclusions
    excluded_directory_names = _DEFAULT_EXCLUDED_FILES.copy()

    if getattr(args, "exclude_dirs", None) is not None:
        # CLI args provided - merge with defaults
        excluded_directory_names.update(args.exclude_dirs)
    else:
        # Check config for additional exclusions
        cfg_excludes = getattr(config, "DOCS_EXCLUDE_DIRS", ()) or ()
        if cfg_excludes:
            excluded_directory_names.update(cfg_excludes)

    if getattr(args, "exclude_patterns", None) is not None:
        excluded_path_globs = set(args.exclude_patterns)
    else:
        cfg_patterns = getattr(config, "DOCS_EXCLUDE_GLOBS", ()) or ()
        excluded_path_globs = set(cfg_patterns)

    # Load enabled paths from config
    if getattr(args, "enabled_paths", None) is not None:
        enabled_paths = tuple(args.enabled_paths)
    else:
        cfg_enabled = getattr(config, "DOCS_ENABLED_PATHS", ()) or ()
        enabled_paths = tuple(cfg_enabled)

    follow_symbolic_links = bool(
        getattr(args, "follow_symlinks", False) or getattr(config, "DOCS_FOLLOW_SYMLINKS", False)
    )

    return IngestionOptions(
        root_paths=root_paths,
        enabled_paths=enabled_paths,
        allowed_extensions=allowed_extensions,
        excluded_directory_names=excluded_directory_names,
        excluded_path_globs=excluded_path_globs,
        follow_symbolic_links=follow_symbolic_links,
        dry_run=bool(getattr(args, "dry_run", False)),
        per_file_mode=bool(getattr(args, "per_file", False)),
        maximum_files=int(getattr(args, "max_files", 0) or 0),
        log_level_name=(getattr(args, "log_level", None) or getattr(config, "INGEST_LOG_LEVEL", "INFO") or "INFO"),
        scan_progress_every=int(getattr(args, "scan_progress", 0) or 0),
    )


__all__ = ["build_ingestion_options_from_args"]
