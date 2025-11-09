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
from pathlib import PurePosixPath
from typing import Iterable, List, Set, Tuple

from src.config.settings import Config
from src.providers.factory import ProviderFactory
from src.ingestion.pipeline import IngestionPipeline
from src.cli.options import IngestionOptions, DiscoveryOptions, PipelineOptions
from src.utils.decorators import timed, logged
from src.vectorstores import get_vector_store


# --------------------------- Utility / helpers ----------------------------

def _normalize_extension(ext: str) -> str:
    """Normalize a file extension to lowercase and ensure it starts with a dot."""
    normalized = ext.strip().lower()
    return normalized if normalized.startswith(".") else f".{normalized}"


# --------------------------- File discovery layer -------------------------

class FileDiscoveryService:
    """Service that walks the filesystem and selects candidate files for ingestion."""

    # --- Strategies (simple interchangeable filters) ---
    class _Strategy:
        def allow_dir(self, rel_dirpath: str, dirname: str) -> bool:  # pragma: no cover - interface
            return True

        def allow_file(self, rel_dirpath: str, filename: str) -> bool:  # pragma: no cover - interface
            return True

    class _IgnoreDirsStrategy(_Strategy):
        def __init__(self, excluded: Set[str]):
            self._excluded = excluded

        def allow_dir(self, rel_dirpath: str, dirname: str) -> bool:
            return dirname not in self._excluded

    class _ExtFilterStrategy(_Strategy):
        def __init__(self, allowed_exts: Set[str]):
            self._allowed = allowed_exts

        def allow_file(self, rel_dirpath: str, filename: str) -> bool:
            if not self._allowed:
                return True
            _, ext = os.path.splitext(filename)
            return ext.lower() in self._allowed

    class _GlobExclusionStrategy(_Strategy):
        def __init__(self, patterns: Set[str]):
            self._patterns = patterns

        def allow_dir(self, rel_dirpath: str, dirname: str) -> bool:
            if not self._patterns:
                return True
            relative = dirname if not rel_dirpath else os.path.join(rel_dirpath, dirname)
            return not FileDiscoveryService._matches_any_glob(relative, self._patterns)

        def allow_file(self, rel_dirpath: str, filename: str) -> bool:
            if not self._patterns:
                return True
            relative = filename if not rel_dirpath else os.path.join(rel_dirpath, filename)
            return not FileDiscoveryService._matches_any_glob(relative, self._patterns)

    @logged("Starting file discovery")
    @timed()
    def discover(self, opts: DiscoveryOptions) -> Tuple[List[str], int]:
        """
        Traverse roots and return candidate file paths and visited directory count.

        Args:
            opts: DiscoveryOptions controlling traversal and filters.

        Returns:
            (files, visited_dir_count)
        """
        files: List[str] = []
        visited_dirs = 0

        for raw_root in opts.roots:
            root = os.path.abspath(raw_root)
            if not os.path.exists(root):
                logging.warning("Root does not exist: %s", root)
                continue

            if os.path.isfile(root):
                rel_file = os.path.basename(root)
                if self._matches_any_glob(rel_file, opts.excluded_globs):
                    continue
                _, ext = os.path.splitext(root)
                if self._is_allowed_ext(ext, opts.allowed_exts):
                    files.append(root)
                continue

            # Build filters for this traversal
            filters = self._build_filters(opts)

            # Walk directory tree
            for dirpath, dirnames, filenames in os.walk(root, followlinks=opts.follow_symlinks):
                visited_dirs += 1

                # Scan progress (incremental feedback)
                if opts.progress_every and (visited_dirs % opts.progress_every == 0):
                    logging.info("Scanning… visited=%d dir(s), current=%s", visited_dirs, dirpath)

                rel_dirpath = os.path.relpath(dirpath, root)
                if rel_dirpath == ".":
                    rel_dirpath = ""

                if rel_dirpath and self._matches_any_glob(rel_dirpath, opts.excluded_globs):
                    dirnames[:] = []
                    continue

                # In-place filter to prune traversal (by strategies)
                pruned_dirnames = [d for d in dirnames if all(s.allow_dir(rel_dirpath, d) for s in filters)]
                dirnames[:] = pruned_dirnames

                for filename in filenames:
                    if not all(s.allow_file(rel_dirpath, filename) for s in filters):
                        continue
                    files.append(os.path.join(dirpath, filename))

        # Normalize and de-duplicate deterministically
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

    @staticmethod
    def _is_allowed_ext(ext: str, allowed: Set[str]) -> bool:
        if not allowed:
            return True
        return ext.lower() in allowed

    # Strategy builder
    def _build_filters(self, opts: DiscoveryOptions) -> List["FileDiscoveryService._Strategy"]:
        filters: List[FileDiscoveryService._Strategy] = []
        if opts.excluded_dirs:
            filters.append(FileDiscoveryService._IgnoreDirsStrategy(opts.excluded_dirs))
        if opts.excluded_globs:
            filters.append(FileDiscoveryService._GlobExclusionStrategy(opts.excluded_globs))
        filters.append(FileDiscoveryService._ExtFilterStrategy(opts.allowed_exts))
        return filters


# ------------------------ Orchestration / application ---------------------

class IngestionOrchestrator:
    """Wires services (LM Studio, embeddings, vector store, pipeline) and executes ingestion."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._discovery = FileDiscoveryService()

    def run(self, options: IngestionOptions) -> None:
        """Execute the ingestion flow end-to-end, respecting provided options."""
        # Guard clauses
        if not options.root_paths:
            raise ValueError("At least one root path must be provided.")
        if all(not os.path.exists(p) for p in options.root_paths):
            raise FileNotFoundError("None of the provided root paths exist.")

        self._log_discovery_intro(options)
        candidates, visited_dirs = self._discover_files(options)
        candidates = self._cap_candidates(candidates, options.maximum_files)

        logging.info("Visited directories: %d", visited_dirs)
        logging.info("Candidate files found: %d", len(candidates))

        if options.dry_run:
            self._report_dry_run(candidates)
            return

        pipeline = self._build_pipeline()
        ingested, failed = self._ingest(candidates, pipeline, per_file=options.per_file_mode)
        self._report_final(ingested, failed)

    def _log_discovery_intro(self, options: IngestionOptions) -> None:
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

    def _discover_files(self, options: IngestionOptions) -> Tuple[List[str], int]:
        disc_opts = DiscoveryOptions(
            roots=options.root_paths,
            allowed_exts=options.allowed_extensions,
            excluded_dirs=options.excluded_directory_names,
            excluded_globs=options.excluded_path_globs,
            follow_symlinks=options.follow_symbolic_links,
            progress_every=max(0, int(options.scan_progress_every or 0)),
        )
        return self._discovery.discover(disc_opts)

    @staticmethod
    def _cap_candidates(candidates: List[str], maximum: int) -> List[str]:
        if not maximum or maximum <= 0:
            return candidates
        return candidates[:maximum]

    def _build_pipeline(self) -> IngestionPipeline:
        logging.info("Initializing services (LM Studio, EmbeddingService, VectorStore, Pipeline)…")
        provider = ProviderFactory(self._config)
        embedding_service = provider.embeddings()
        vector_store = get_vector_store(self._config)
        pipeline_options = PipelineOptions(
            chunk_size=self._config.CHUNK_SIZE,
            chunk_overlap=self._config.CHUNK_OVERLAP,
            tenant_id=(self._config.WEAVIATE_DEFAULT_TENANT or None),
        )
        return IngestionPipeline.from_options(
            embedding_service=embedding_service,
            vector_store=vector_store,
            options=pipeline_options,
        )

    @staticmethod
    def _ingest(candidates: List[str], pipeline: IngestionPipeline, per_file: bool) -> Tuple[int, int]:
        logging.info("Starting ingestion. Files to ingest: %d", len(candidates))
        ingested = 0
        failed = 0

        if per_file:
            for index, path in enumerate(candidates, start=1):
                logging.info("[%-5d/%-5d] Ingesting: %s", index, len(candidates), path)
                try:
                    pipeline.ingest_paths([path])
                    ingested += 1
                except (OSError, ValueError, RuntimeError) as exc:
                    failed += 1
                    logging.error("Failed to ingest %s: %s", path, exc)
            return ingested, failed

        try:
            pipeline.ingest_paths(candidates)
            ingested = len(candidates)
        except (OSError, ValueError, RuntimeError) as exc:
            failed = len(candidates)
            logging.error("Batch ingestion failed: %s", exc)
        return ingested, failed

    @staticmethod
    def _report_dry_run(candidates: List[str]) -> None:
        for path in candidates:
            print(path)
        logging.info("Dry-run complete. No ingestion performed.")

    @staticmethod
    def _report_final(ingested: int, failed: int) -> None:
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
            "--scan-progress",
            type=int,
            default=0,
            help="Log a progress line every N visited directories during scan (0 = disabled).",
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
        # Roots (priority: CLI > DOCS_INCLUDE_DIRS > DOCS_PATH)
        if args.paths:
            root_paths = tuple(args.paths)
        else:
            include_dirs = getattr(self._config, "DOCS_INCLUDE_DIRS", []) or []
            if include_dirs:
                root_paths = tuple(include_dirs)
            else:
                root_paths = (getattr(self._config, "DOCS_PATH", "/mnt/Documents/Documents"),)

        # Extensions (priority: CLI --exts > DOCS_FILE_EXTS > all)
        if args.exts is not None:
            allowed_extensions = {_normalize_extension(e) for e in args.exts}
        else:
            cfg_exts = getattr(self._config, "DOCS_FILE_EXTS", []) or []
            allowed_extensions = {_normalize_extension(e) for e in cfg_exts} if cfg_exts else set()

        # Exclude dirs (priority: CLI --exclude-dirs > DOCS_EXCLUDE_DIRS > defaults)
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
            scan_progress_every=int(args.scan_progress or 0),
        )


# ------------------------------- Entrypoint -------------------------------

def main() -> None:
    """Entrypoint for `python -m src.main --ingest ...`."""
    IngestionCLI().run()


if __name__ == "__main__":
    main()
