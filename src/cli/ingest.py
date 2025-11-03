"""
Object-oriented CLI to ingest documents and code into a vector database using embeddings.

Design goals:
- Clear separation of concerns:
  * IngestionOptions          -> Pure configuration container
  * FileDiscoveryService      -> Filesystem scanning and filtering
  * IngestionOrchestrator     -> Wires services and runs ingestion
  * IngestionCLI              -> CLI facade (argparse + logging)
- Auditable logs and robust defaults.

Usage examples:
    # Use directories from .env (DOCS_INCLUDE_DIRS or DOCS_PATH)
    python -m src.main --ingest

    # Explicit roots and custom extensions
    python -m src.main --ingest /mnt/Documents/Documents /mnt/MoreDocs --exts .md .pdf .txt

    # Dry-run (only list what would be ingested)
    python -m src.main --ingest /data/docs --dry-run --log-level DEBUG
"""
from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterable, List, Set, Tuple

from src.config.settings import Config
from src.providers.lmstudio.model_manager import ModelManager
from src.providers.lmstudio.embeddings import EmbeddingService
from src.ingestion.pipeline import IngestionPipeline
from src.vectorstores import get_vector_store


# ------------------------------- Data model -------------------------------

@dataclass(frozen=True)
class IngestionOptions:
    """
    Immutable container for ingestion parameters.

    Attributes:
        root_paths: Root directories or individual files to ingest.
        allowed_extensions: File extensions to include (lowercase, with leading dot). Empty set means "all".
        excluded_directory_names: Directory *names* (not paths) to skip (e.g., {".git","node_modules"}).
        follow_symbolic_links: Whether to follow symbolic links to directories in os.walk.
        excluded_path_globs: Glob expressions (relative to cada raíz) to excluir rutas.
        dry_run: If True, list candidates only; do not ingest.
        per_file_mode: If True, ingest files one by one (more granular logs).
        maximum_files: 0 means no limit; otherwise cut candidate list to this number.
        log_level_name: Logging level name ("DEBUG", "INFO", ...).
    """
    root_paths: Tuple[str, ...]
    allowed_extensions: Set[str] = field(default_factory=set)
    excluded_directory_names: Set[str] = field(default_factory=set)
    excluded_path_globs: Set[str] = field(default_factory=set)
    follow_symbolic_links: bool = False
    dry_run: bool = False
    per_file_mode: bool = False
    maximum_files: int = 0
    log_level_name: str = "INFO"


# --------------------------- Utility / helpers ----------------------------

def _normalize_extension(ext: str) -> str:
    """Normalize a file extension to lowercase and ensure it starts with a dot."""
    normalized = ext.strip().lower()
    return normalized if normalized.startswith(".") else f".{normalized}"


# --------------------------- File discovery layer -------------------------

class FileDiscoveryService:
    """Service that walks the filesystem and selects candidate files for ingestion."""

    def discover(
        self,
        roots: Iterable[str],
        allowed_extensions: Set[str],
        excluded_directory_names: Set[str],
        excluded_path_globs: Set[str],
        follow_symbolic_links: bool,
    ) -> Tuple[List[str], int]:
        """Traverse roots and return candidate file paths and visited directory count."""
        files: List[str] = []
        visited_dirs = 0

        for raw_root in roots:
            root = os.path.abspath(raw_root)
            if not os.path.exists(root):
                logging.warning("Root does not exist: %s", root)
                continue

            if os.path.isfile(root):
                rel_file = os.path.basename(root)
                if self._matches_any_glob(rel_file, excluded_path_globs):
                    continue
                _, ext = os.path.splitext(root)
                if not allowed_extensions or ext.lower() in allowed_extensions:
                    files.append(root)
                continue

            for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symbolic_links):
                visited_dirs += 1
                rel_dirpath = os.path.relpath(dirpath, root)
                if rel_dirpath == ".":
                    rel_dirpath = ""

                if rel_dirpath and self._matches_any_glob(rel_dirpath, excluded_path_globs):
                    dirnames[:] = []
                    continue

                pruned_dirnames = []
                for dirname in dirnames:
                    if dirname in excluded_directory_names:
                        continue
                    relative_dir = dirname if not rel_dirpath else os.path.join(rel_dirpath, dirname)
                    if self._matches_any_glob(relative_dir, excluded_path_globs):
                        continue
                    pruned_dirnames.append(dirname)
                dirnames[:] = pruned_dirnames
                for filename in filenames:
                    _, ext = os.path.splitext(filename)
                    if allowed_extensions and ext.lower() not in allowed_extensions:
                        continue
                    relative_file = filename if not rel_dirpath else os.path.join(rel_dirpath, filename)
                    if self._matches_any_glob(relative_file, excluded_path_globs):
                        continue
                    files.append(os.path.join(dirpath, filename))

        files = sorted(set(files))
        return files, visited_dirs

    @staticmethod
    def _matches_any_glob(relative_path: str, patterns: Set[str]) -> bool:
        if not patterns:
            return False

        normalized = relative_path.replace("\\", "/")
        normalized = normalized.lstrip("./")
        normalized = normalized.strip("/")
        candidate = normalized or "."
        candidate_path = PurePosixPath(candidate)
        basename = normalized.rsplit("/", 1)[-1] if normalized else ""
        basename_path = PurePosixPath(basename or ".")

        for pattern in patterns:
            normalized_pattern = pattern.replace("\\", "/").strip()
            if not normalized_pattern:
                normalized_pattern = "."
            normalized_pattern = normalized_pattern.lstrip("./")
            if normalized_pattern.startswith("/"):
                normalized_pattern = normalized_pattern[1:]
            normalized_pattern = normalized_pattern.rstrip("/")
            if not normalized_pattern:
                normalized_pattern = "."
            if candidate_path.match(normalized_pattern):
                return True
            if basename and basename_path.match(normalized_pattern):
                return True
        return False


# ------------------------ Orchestration / application ---------------------

class IngestionOrchestrator:
    """Wires services (LM Studio, embeddings, vector store, pipeline) and executes ingestion."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._discovery = FileDiscoveryService()

    def run(self, options: IngestionOptions) -> None:
        """Execute the ingestion flow end-to-end, respecting provided options."""
        if not options.root_paths:
            raise ValueError("At least one root path must be provided.")
        if all(not os.path.exists(p) for p in options.root_paths):
            raise FileNotFoundError("None of the provided root paths exist.")

        logging.info("Roots to scan (%d): %s", len(options.root_paths), list(options.root_paths))
        logging.info(
            "Allowed extensions: %s",
            sorted(options.allowed_extensions) if options.allowed_extensions else "(all)",
        )
        logging.info(
            "Excluded dir names: %s",
            sorted(options.excluded_directory_names) if options.excluded_directory_names else "(none)",
        )
        logging.info(
            "Excluded path patterns: %s",
            sorted(options.excluded_path_globs) if options.excluded_path_globs else "(none)",
        )

        candidates, visited_dirs = self._discovery.discover(
            roots=options.root_paths,
            allowed_extensions=options.allowed_extensions,
            excluded_directory_names=options.excluded_directory_names,
            excluded_path_globs=options.excluded_path_globs,
            follow_symbolic_links=options.follow_symbolic_links,
        )

        total_candidates = len(candidates)
        if options.maximum_files and total_candidates > options.maximum_files:
            candidates = candidates[: options.maximum_files]

        logging.info("Visited directories: %d", visited_dirs)
        logging.info(
            "Candidate files found: %d%s",
            total_candidates,
            f" (limited to first {len(candidates)})"
            if options.maximum_files and total_candidates > options.maximum_files
            else "",
        )

        if options.dry_run:
            for path in candidates:
                print(path)
            logging.info("Dry-run complete. No ingestion performed.")
            return

        logging.info("Initializing services (LM Studio, EmbeddingService, VectorStore, Pipeline)…")
        model_manager = ModelManager(self._config)
        embedding_service = EmbeddingService(self._config, model_manager)
        vector_store = get_vector_store(self._config)
        pipeline = IngestionPipeline(
            embedding_service=embedding_service,
            vector_store=vector_store,
            chunk_size=self._config.CHUNK_SIZE,
            chunk_overlap=self._config.CHUNK_OVERLAP,
            tenant_id=(self._config.WEAVIATE_DEFAULT_TENANT or None),
        )

        logging.info("Starting ingestion. Files to ingest: %d", len(candidates))
        ingested = 0
        failed = 0

        if options.per_file_mode:
            for index, path in enumerate(candidates, start=1):
                logging.info("[%-5d/%-5d] Ingesting: %s", index, len(candidates), path)
                try:
                    pipeline.ingest_paths([path])
                    ingested += 1
                except (OSError, ValueError, RuntimeError) as exc:
                    failed += 1
                    logging.error("Failed to ingest %s: %s", path, exc)
        else:
            try:
                pipeline.ingest_paths(candidates)
                ingested = len(candidates)
            except (OSError, ValueError, RuntimeError) as exc:
                failed = len(candidates)
                logging.error("Batch ingestion failed: %s", exc)

        logging.info("Ingestion finished. ingested=%d, failed=%d", ingested, failed)


# ------------------------------- CLI facade -------------------------------

class IngestionCLI:
    """CLI facade that parses arguments, configures logging, and executes the orchestrator."""

    def __init__(self) -> None:
        self._config = Config()
        self._parser = self._build_parser()

    def run(self) -> None:
        """Parse CLI args, configure logging, build options, and run ingestion."""
        args = self._parser.parse_args()
        self._configure_logging(args.log_level)
        options = self._build_options_from_args(args)
        IngestionOrchestrator(self._config).run(options)

    def _build_parser(self) -> argparse.ArgumentParser:
        """Create and return the ArgumentParser configured for this CLI."""
        parser = argparse.ArgumentParser(description="Ingest documents and code into a vector DB.")
        parser.add_argument(
            "paths",
            nargs="*",
            help="Root directories or files. If omitted, uses DOCS_INCLUDE_DIRS or DOCS_PATH from .env.",
        )
        parser.add_argument(
            "--exts",
            nargs="+",
            default=None,
            help="Extensions to include (e.g., .md .pdf .txt). If omitted, uses DOCS_FILE_EXTS from .env.",
        )
        parser.add_argument(
            "--exclude-dirs",
            nargs="+",
            default=None,
            help="Directory NAMES to exclude (e.g., .git node_modules __pycache__).",
        )
        parser.add_argument(
            "--exclude-patterns",
            nargs="+",
            default=None,
            help="Glob patterns (relative paths) to exclude, e.g. '*.log' 'data/cache/*'.",
        )
        parser.add_argument(
            "--follow-symlinks",
            action="store_true",
            help="Follow symlinks while scanning.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only list what would be ingested; do not call the pipeline.",
        )
        parser.add_argument(
            "--per-file",
            action="store_true",
            help="Ingest one file at a time (more logs, slower). Default is batch.",
        )
        parser.add_argument(
            "--max-files",
            type=int,
            default=0,
            help="Limit the number of files to ingest (0 = no limit).",
        )
        parser.add_argument(
            "--log-level",
            default=None,
            help="Python log level (DEBUG, INFO, WARNING, ERROR). Defaults to .env INGEST_LOG_LEVEL or INFO.",
        )
        return parser

    def _configure_logging(self, level_from_cli: str | None) -> None:
        """Configure basic logging using CLI or .env fallback."""
        log_level_name = (level_from_cli or getattr(self._config, "INGEST_LOG_LEVEL", "INFO") or "INFO").upper()
        level_value = getattr(logging, log_level_name, logging.INFO)
        logging.basicConfig(level=level_value, format="%(levelname)s: %(message)s")
        logging.debug("Logging configured at level=%s", log_level_name)

    def _build_options_from_args(self, args: argparse.Namespace) -> IngestionOptions:
        """Derive IngestionOptions from CLI args and Config, with graceful fallbacks."""
        # Roots (prioridad: CLI > DOCS_INCLUDE_DIRS > DOCS_PATH)
        if args.paths:
            root_paths = tuple(args.paths)
        else:
            include_dirs = getattr(self._config, "DOCS_INCLUDE_DIRS", []) or []
            if include_dirs:
                root_paths = tuple(include_dirs)
            else:
                root_paths = (getattr(self._config, "DOCS_PATH", "/mnt/Documents/Documents"),)

        # Extensions (prioridad: CLI --exts > DOCS_FILE_EXTS > todas)
        if args.exts is not None:
            allowed_extensions = {_normalize_extension(e) for e in args.exts}
        else:
            cfg_exts = getattr(self._config, "DOCS_FILE_EXTS", []) or []
            allowed_extensions = {_normalize_extension(e) for e in cfg_exts} if cfg_exts else set()

        # Exclude dirs (prioridad: CLI --exclude-dirs > DOCS_EXCLUDE_DIRS > defaults)
        if args.exclude_dirs is not None:
            excluded_directory_names = set(args.exclude_dirs)
        else:
            cfg_excludes = getattr(self._config, "DOCS_EXCLUDE_DIRS", ()) or ()
            excluded_directory_names = set(cfg_excludes)

        if args.exclude_patterns is not None:
            excluded_path_globs = set(args.exclude_patterns)
        else:
            cfg_patterns = getattr(self._config, "DOCS_EXCLUDE_GLOBS", ()) or ()
            excluded_path_globs = set(cfg_patterns)

        follow_symbolic_links = bool(args.follow_symlinks or getattr(self._config, "DOCS_FOLLOW_SYMLINKS", False))

        return IngestionOptions(
            root_paths=root_paths,
            allowed_extensions=allowed_extensions,
            excluded_directory_names=excluded_directory_names,
            excluded_path_globs=excluded_path_globs,
            follow_symbolic_links=follow_symbolic_links,
            dry_run=bool(args.dry_run),
            per_file_mode=bool(args.per_file),
            maximum_files=int(args.max_files or 0),
            log_level_name=(args.log_level or getattr(self._config, "INGEST_LOG_LEVEL", "INFO") or "INFO"),
        )


# ------------------------------- Entrypoint -------------------------------

def main() -> None:
    """Entrypoint for `python -m src.main --ingest ...`."""
    IngestionCLI().run()


if __name__ == "__main__":
    main()
