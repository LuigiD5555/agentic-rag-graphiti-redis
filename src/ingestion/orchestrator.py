"""Orchestration layer for ingestion."""

import os
from typing import List

from src.ingestion.discovery import FileDiscoveryService
from src.storage.cache.ingestion import IngestionCacheManager
from src.ingestion.options import DiscoveryOptions, IngestionOptions, PipelineOptions
from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.pipeline.state_helpers import record_directory_listing
from src.providers.factory import ProviderFactory
from src.rag.audit import get_logger
import src.settings as settings
from src.rag.embeddings_factory import get_embedding_service
from src.storage.vector import get_vector_store
from src.utils.file_operations import sort_paths_by_size_desc  # Now sorts ascending (small->large)

log = get_logger(__name__)


class IngestionOrchestrator:
    """Wires services (LM Studio, embeddings, vector store, pipeline) and executes ingestion."""

    def __init__(self) -> None:
        # Initialize Redis cache manager
        # Use settings object attributes
        settings_dict = {k: getattr(settings, k) for k in dir(settings) if not k.startswith('_')}
        self._cache_manager = IngestionCacheManager.from_settings(settings_dict)

        # Initialize discovery service with cache manager
        self._discovery = FileDiscoveryService(cache_manager=self._cache_manager)

    def run(self, options: IngestionOptions) -> None:
        """Execute the ingestion flow end-to-end, respecting provided options."""
        if not options.root_paths:
            raise ValueError("At least one root path must be provided.")
        if all(not os.path.exists(p) for p in options.root_paths):
            raise FileNotFoundError("None of the provided root paths exist.")

        self._log_discovery_intro(options)
        if options.stream_ingest:
            if options.dry_run:
                candidates = self._stream_discover(options)
                log.info("Visited directories: %d", self._discovery.last_visited_dirs)
                log.info("Candidate files found: %d", candidates)
                return

            pipeline = self._build_pipeline()
            ingested, failed, candidates = self._stream_ingest(options, pipeline)
            log.info("Visited directories: %d", self._discovery.last_visited_dirs)
            log.info("Candidate files found: %d", candidates)
            self._report_final(ingested, failed)
            return

        candidates, visited_dirs = self._discover_files(options)
        candidates = sort_paths_by_size_desc(candidates)
        candidates = self._cap_candidates(candidates, options.maximum_files)

        log.info("Visited directories: %d", visited_dirs)
        log.info("Candidate files found: %d", len(candidates))

        if options.dry_run:
            self._report_dry_run(candidates)
            return

        pipeline = self._build_pipeline()
        ingested, failed = self._ingest(candidates, pipeline, per_file=options.per_file_mode)
        self._report_final(ingested, failed)

    def run_with_report(self, options: IngestionOptions) -> dict:
        """Execute ingestion and return a summary report."""
        if not options.root_paths:
            raise ValueError("At least one root path must be provided.")
        if all(not os.path.exists(p) for p in options.root_paths):
            raise FileNotFoundError("None of the provided root paths exist.")

        self._log_discovery_intro(options)
        if options.stream_ingest:
            if options.dry_run:
                candidates = self._stream_discover(options)
                log.info("Visited directories: %d", self._discovery.last_visited_dirs)
                log.info("Candidate files found: %d", candidates)
                return {
                    "status": "dry_run",
                    "ingested": 0,
                    "failed": 0,
                    "candidates": candidates,
                }

            pipeline = self._build_pipeline()
            ingested, failed, candidates = self._stream_ingest(options, pipeline)
            log.info("Visited directories: %d", self._discovery.last_visited_dirs)
            log.info("Candidate files found: %d", candidates)
            self._report_final(ingested, failed)
            return {
                "status": "ok",
                "ingested": ingested,
                "failed": failed,
                "candidates": candidates,
            }

        candidates, visited_dirs = self._discover_files(options)
        candidates = sort_paths_by_size_desc(candidates)
        candidates = self._cap_candidates(candidates, options.maximum_files)

        log.info("Visited directories: %d", visited_dirs)
        log.info("Candidate files found: %d", len(candidates))

        if options.dry_run:
            self._report_dry_run(candidates)
            return {
                "status": "dry_run",
                "ingested": 0,
                "failed": 0,
                "candidates": len(candidates),
            }

        pipeline = self._build_pipeline()
        ingested, failed = self._ingest(candidates, pipeline, per_file=options.per_file_mode)
        self._report_final(ingested, failed)
        return {
            "status": "ok",
            "ingested": ingested,
            "failed": failed,
            "candidates": len(candidates),
        }

    def _log_discovery_intro(self, options: IngestionOptions) -> None:
        log.info("Roots to scan (%d): %s", len(options.root_paths), list(options.root_paths))
        log.info(
            "Allowed extensions: %s",
            sorted(options.allowed_extensions) if options.allowed_extensions else "(all)",
        )
        log.info(
            "Excluded dir names: %s",
            sorted(options.excluded_directory_names) if options.excluded_directory_names else "(none)",
        )
        log.info(
            "Excluded path patterns: %s",
            sorted(options.excluded_path_globs) if options.excluded_path_globs else "(none)",
        )

    def _discover_files(self, options: IngestionOptions):
        disc_opts = DiscoveryOptions(
            roots=options.root_paths,
            enabled_paths=options.enabled_paths,
            allowed_exts=options.allowed_extensions,
            excluded_dirs=options.excluded_directory_names,
            excluded_globs=options.excluded_path_globs,
            follow_symlinks=options.follow_symbolic_links,
            progress_every=options.scan_progress_every,
        )
        return self._discovery.discover(disc_opts)

    def _stream_discover(self, options: IngestionOptions) -> int:
        disc_opts = DiscoveryOptions(
            roots=options.root_paths,
            enabled_paths=options.enabled_paths,
            allowed_exts=options.allowed_extensions,
            excluded_dirs=options.excluded_directory_names,
            excluded_globs=options.excluded_path_globs,
            follow_symlinks=options.follow_symbolic_links,
            progress_every=options.scan_progress_every,
        )
        max_files = options.maximum_files
        candidates = 0
        seen_files = set()
        stream = self._discovery.discover_stream(disc_opts)
        try:
            for _, files in stream:
                if not files:
                    continue
                new_files = [path for path in files if path not in seen_files]
                if not new_files:
                    continue
                if max_files > 0:
                    remaining = max_files - candidates
                    if remaining <= 0:
                        break
                    new_files = new_files[:remaining]
                for path in new_files:
                    print(path)
                seen_files.update(new_files)
                candidates += len(new_files)
                if max_files > 0 and candidates >= max_files:
                    break
        finally:
            stream.close()
        log.info("Dry-run complete. No ingestion performed.")
        return candidates

    @staticmethod
    def _cap_candidates(candidates: List[str], maximum: int) -> List[str]:
        if not maximum or maximum <= 0:
            return candidates
        return candidates[:maximum]

    def _build_pipeline(self) -> IngestionPipeline:
        log.info("Initializing services (LM Studio, EmbeddingService, VectorStore, Pipeline)...")
        provider = ProviderFactory(settings)
        embedding_service = get_embedding_service(settings, provider)
        vector_store = get_vector_store(settings)
        pipeline_options = PipelineOptions(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            embedding_token_limit=settings.EMBEDDING_MAX_TOKENS,
            tenant_id=(settings.WEAVIATE_DEFAULT_TENANT or None),
            include_duplicates_patterns=getattr(settings, 'DUPLICATES_DOC_EXCEPTIONS', ()),
        )

        # Log cache manager status
        if self._cache_manager.enabled:
            stats = self._cache_manager.get_stats()
            log.info(
                "Redis cache enabled: %d cached files, %d cached directories",
                stats.get('cached_files', 0),
                stats.get('cached_directories', 0)
            )
        else:
            log.warning("Redis cache not available, using in-memory fallback")

        return IngestionPipeline.from_options(
            embedding_service=embedding_service,
            vector_store=vector_store,
            options=pipeline_options,
            cache_manager=self._cache_manager,
        )

    def _stream_ingest(self, options: IngestionOptions, pipeline: IngestionPipeline):
        disc_opts = DiscoveryOptions(
            roots=options.root_paths,
            enabled_paths=options.enabled_paths,
            allowed_exts=options.allowed_extensions,
            excluded_dirs=options.excluded_directory_names,
            excluded_globs=options.excluded_path_globs,
            follow_symlinks=options.follow_symbolic_links,
            progress_every=options.scan_progress_every,
        )
        ingested = 0
        failed = 0
        candidates = 0
        max_files = options.maximum_files
        seen_files = set()
        stream = self._discovery.discover_stream(disc_opts)
        pipeline.start_ingestion_run()
        try:
            for directory, files in stream:
                record_directory_listing(pipeline, directory, files)
                if not files:
                    continue

                new_files = [path for path in files if path not in seen_files]
                if not new_files:
                    continue
                if max_files > 0:
                    remaining = max_files - candidates
                    if remaining <= 0:
                        break
                    new_files = new_files[:remaining]
                if not new_files:
                    continue

                new_files = sort_paths_by_size_desc(new_files)
                seen_files.update(new_files)
                candidates += len(new_files)
                batch_ingested, batch_failed = pipeline.ingest_files(
                    new_files,
                    directory_path=directory,
                    per_file=options.per_file_mode,
                )
                ingested += batch_ingested
                failed += batch_failed

                if max_files > 0 and candidates >= max_files:
                    break
        finally:
            stream.close()
            pipeline.finish_ingestion_run()
        return ingested, failed, candidates

    @staticmethod
    def _ingest(candidates: List[str], pipeline: IngestionPipeline, per_file: bool):
        log.info("Starting ingestion. Files to ingest: %d", len(candidates))
        ingested = 0
        failed = 0
        if per_file:
            for index, path in enumerate(candidates, start=1):
                log.info("[%-5d/%-5d] Ingesting: %s", index, len(candidates), path)
                try:
                    pipeline.ingest_paths([path])
                    ingested += 1
                except (OSError, ValueError, RuntimeError) as exc:
                    failed += 1
                    log.error("Failed to ingest %s: %s", path, exc)
            return ingested, failed

        try:
            pipeline.ingest_paths(candidates)
            ingested = len(candidates)
        except (OSError, ValueError, RuntimeError) as exc:
            failed = len(candidates)
            log.error("Batch ingestion failed: %s", exc)
        return ingested, failed

    @staticmethod
    def _report_dry_run(candidates: List[str]) -> None:
        for path in candidates:
            print(path)
        log.info("Dry-run complete. No ingestion performed.")

    @staticmethod
    def _report_final(ingested: int, failed: int) -> None:
        log.info("Ingestion finished. ingested=%d, failed=%d", ingested, failed)


__all__ = ["IngestionOrchestrator"]
