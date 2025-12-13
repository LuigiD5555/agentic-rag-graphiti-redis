"""Orchestration layer for the ingestion CLI."""

import logging
import os
from typing import List

from src.cli.options import DiscoveryOptions, IngestionOptions, PipelineOptions
from src.config.settings import Config
from src.ingestion.pipeline import IngestionPipeline
from src.providers.factory import ProviderFactory
from src.storage.vector import get_vector_store

from .discovery import FileDiscoveryService


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

    def _discover_files(self, options: IngestionOptions):
        disc_opts = DiscoveryOptions(
            roots=options.root_paths,
            allowed_exts=options.allowed_extensions,
            excluded_dirs=options.excluded_directory_names,
            excluded_globs=options.excluded_path_globs,
            follow_symlinks=options.follow_symbolic_links,
            progress_every=0,
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
            embedding_token_limit=self._config.EMBEDDING_MAX_TOKENS,
            tenant_id=(self._config.WEAVIATE_DEFAULT_TENANT or None),
        )
        return IngestionPipeline.from_options(
            embedding_service=embedding_service,
            vector_store=vector_store,
            options=pipeline_options,
        )

    @staticmethod
    def _ingest(candidates: List[str], pipeline: IngestionPipeline, per_file: bool):
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
