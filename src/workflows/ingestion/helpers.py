"""Validation helpers for translating CLI args into ingestion options."""
import argparse
import os

from src.workflows.ingestion.options import IngestionOptions
from src.workflows.query.audit import get_logger

logger = get_logger(__name__)


def _detect_available_volumes() -> list[str]:
    """
    Detect which volumes are currently available.
    
    This function checks for external volumes defined in EXTERNAL_VOLUMES
    configuration and determines if they're using fallback directories.
    
    Returns:
        List of available volume paths
    """
    available = []
    
    try:
        # Try to load external volumes configuration
        from src.utils.volume_monitor import load_external_volumes_config
        
        volumes_config = load_external_volumes_config()
        
        # Only add paths that are actually accessible
        def check_and_add_path(path: str, description: str) -> bool:
            """Check if path exists and is accessible, add to available if it is."""
            if not os.path.exists(path):
                logger.debug(f"{description} {path} does not exist")
                return False
            
            try:
                # Try to list directory to check accessibility
                os.listdir(path)
                logger.info(f"{description} {path} is available")
                available.append(path)
                return True
            except OSError as exc:
                logger.warning(f"{description} {path} not accessible ({exc})")
                return False
        
        for vol_config in volumes_config:
            name = vol_config.get("name", "Unknown")
            mount_point = vol_config.get("mount", "")
            primary = vol_config.get("primary", "")
            fallback = vol_config.get("fallback", "")
            
            if not mount_point:
                continue
            
            # Check if mount point exists and is accessible
            if not check_and_add_path(mount_point, f"Volume '{name}'"):
                # Try fallback if primary mount is not accessible
                if fallback and os.path.exists(fallback):
                    check_and_add_path(fallback, f"Fallback for '{name}'")
                else:
                    logger.debug(f"Volume '{name}' is not mounted and no fallback available")
                    
    except ImportError:
        logger.debug("Volume monitor module not available, skipping external volume detection")
    except Exception as e:
        logger.warning(f"Failed to detect external volumes: {e}")
    
    return available


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
        # Try to use the path manager as the primary source of document paths
        try:
            from src.utils.path_manager import get_enabled_document_paths
            base_paths = get_enabled_document_paths()
            logger.info(f"Using {len(base_paths)} enabled paths from path manager")
        except ImportError:
            logger.debug("Path manager not available, falling back to config")
            cfg_paths = getattr(config, "DOCS_PATHS", None) or []
            base_paths = list(cfg_paths) if cfg_paths else ["/mnt/Documents/Documents"]

        # Add available external volumes dynamically, but avoid duplicates
        external_volumes = _detect_available_volumes()
        for vol in external_volumes:
            if vol not in base_paths:
                base_paths.append(vol)
                logger.debug(f"Added external volume: {vol}")
            else:
                logger.debug(f"Volume {vol} already in paths, skipping duplicate")

        root_paths = tuple(base_paths)

    if getattr(args, "exts", None) is not None:
        allowed_extensions = {_normalize_ext(e) for e in args.exts}
        allowed_extensions.discard("")
    else:
        cfg_exts = getattr(config, "DOCS_FILE_EXTS", []) or []
        allowed_extensions = {_normalize_ext(e) for e in cfg_exts} if cfg_exts else set()
        allowed_extensions.discard("")

    # Always start with built-in defaults, then add user-specified exclusions
    excluded_directory_names = set()

    # Prefer runtime config (Django-style settings object). Fallback to the
    # module-level defaults if the caller provided a plain module.
    built_in_exclusions = getattr(config, "DEFAULT_EXCLUDED_FILES", None)
    if built_in_exclusions:
        excluded_directory_names.update(set(built_in_exclusions))
    else:
        try:
            # Lazily import to avoid import-order issues during startup.
            from src.settings import _DEFAULT_EXCLUDED_FILES  # type: ignore

            excluded_directory_names.update(_DEFAULT_EXCLUDED_FILES)
        except ImportError:
            pass

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
        stream_ingest=(
            bool(getattr(args, "streaming", False))
            if getattr(args, "streaming", None) is not None
            else bool(getattr(config, "INGEST_STREAMING", True))
        ),
        log_level_name=(getattr(args, "log_level", None) or getattr(config, "INGEST_LOG_LEVEL", "INFO") or "INFO"),
        scan_progress_every=int(getattr(args, "scan_progress", 0) or 0),
        strategy=getattr(args, "strategy", None),
        phased_ingestion=getattr(args, "phased_ingestion", None),
        max_ram_usage_percent=(
            int(getattr(args, "max_ram_percent"))
            if getattr(args, "max_ram_percent", None) is not None
            else None
        ),
        run_id=getattr(args, "run_id", None),
    )


__all__ = ["build_ingestion_options_from_args"]
