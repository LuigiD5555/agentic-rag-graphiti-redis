"""Orchestration layer for ingestion."""

import os
from typing import List

from src.ingestion.discovery import FileDiscoveryService
from src.storage.cache.ingestion import IngestionCacheManager
from src.ingestion.options import DiscoveryOptions, IngestionOptions, PipelineOptions
from src.ingestion.pipeline import IngestionPipeline
from src.providers.factory import ProviderFactory
from src.rag.audit import get_logger
from src.rag.conf import Config
from src.rag.embeddings_factory import get_embedding_service
from src.storage.vector import get_vector_store
from src.utils.file_operations import sort_paths_by_size_desc  # Now sorts ascending (small→large)

log = get_logger(__name__)


class IngestionOrchestrator:
    """Wires services (LM Studio, embeddings, vector store, pipeline) and executes ingestion."""

    def __init__(self, config: Config) -> None:
        self._config = config

        # Initialize Redis cache manager
        settings_dict = {k: getattr(config, k) for k in dir(config) if not k.startswith('_')}
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

    @staticmethod
    def _cap_candidates(candidates: List[str], maximum: int) -> List[str]:
        if not maximum or maximum <= 0:
            return candidates
        return candidates[:maximum]

    def _build_pipeline(self) -> IngestionPipeline:
        log.info("Initializing services (LM Studio, EmbeddingService, VectorStore, Pipeline)…")
        provider = ProviderFactory(self._config)
        embedding_service = get_embedding_service(self._config, provider)
        vector_store = get_vector_store(self._config)
        pipeline_options = PipelineOptions(
            chunk_size=self._config.CHUNK_SIZE,
            chunk_overlap=self._config.CHUNK_OVERLAP,
            embedding_token_limit=self._config.EMBEDDING_MAX_TOKENS,
            tenant_id=(self._config.WEAVIATE_DEFAULT_TENANT or None),
            include_duplicates_patterns=getattr(self._config, 'DUPLICATES_DOC_EXCEPTIONS', ()),
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
