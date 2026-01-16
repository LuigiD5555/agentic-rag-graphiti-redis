"""Orchestrates end-to-end ingestion into the vector store."""
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.workflows.query.audit import get_logger
from src.workflows.ingestion.discovery.service import FileDiscoveryService
from src.workflows.ingestion.pipeline import IngestionPipeline
from src.workflows.ingestion.options import IngestionOptions, PipelineOptions, DiscoveryOptions
from src.workflows.ingestion.phases import PhaseManager
from src.workflows.ingestion.preprocessor import get_ingestion_preprocessor
from src.workflows.ingestion.strategies import select_strategy
from src.backends.storage.cache.ingestion.manager import IngestionCacheManager
from src.backends.storage.vector import get_vector_store
from src.workflows.query.embeddings_factory import get_embedding_service
from src.backends.llm.factory import ProviderFactory
from src.utils.file_operations import sort_paths_by_size_desc
from src.workflows.query.conf import sync_settings_json
from src.conf import settings as runtime_settings

logger = get_logger(__name__)


class IngestionOrchestrator:
    """High-level orchestrator coordinating ingestion flow and reporting."""

    def __init__(self, config: Optional[Any] = None) -> None:
        """
        Create a new orchestrator.

        Args:
            config: Runtime settings object (preferred). If not provided, uses the global
                runtime settings from ``src.conf.settings``.
        """
        self._config = config or runtime_settings

        # Initialize Redis cache manager
        self._cache_manager = IngestionCacheManager.from_settings(self._export_settings_dict(self._config))

        # Initialize discovery service (uses Redis cache internally)
        self._discovery = FileDiscoveryService(cache_manager=self._cache_manager)

        logger.info("IngestionOrchestrator initialized with Redis caching.")

    @staticmethod
    def _export_settings_dict(config: Any) -> Dict[str, Any]:
        """
        Export a settings object or module to a plain dict for components that expect dict-style access.

        Args:
            config: A runtime settings object (Pydantic BaseSettings preferred) or a module-like object.

        Returns:
            A dictionary with public attributes/fields.
        """
        if hasattr(config, "model_dump"):
            return config.model_dump()  # type: ignore[no-any-return]
        if hasattr(config, "__dict__"):
            return {k: v for k, v in config.__dict__.items() if not str(k).startswith("_")}
        return {k: getattr(config, k) for k in dir(config) if not str(k).startswith("_")}

    @staticmethod
    def _to_discovery_options(options: IngestionOptions) -> DiscoveryOptions:
        """
        Convert IngestionOptions to DiscoveryOptions.

        Args:
            options: Ingestion options

        Returns:
            Discovery options
        """
        return DiscoveryOptions(
            roots=options.root_paths,
            enabled_paths=options.enabled_paths,
            allowed_exts=options.allowed_extensions,
            excluded_dirs=options.excluded_directory_names,
            excluded_globs=options.excluded_path_globs,
            follow_symlinks=options.follow_symbolic_links,
            progress_every=options.scan_progress_every,
        )

    def run(self, options: IngestionOptions) -> None:
        """Run ingestion pipeline with the given options."""
        self.run_with_report(options)

    def run_with_report(self, options: IngestionOptions) -> dict:
        """
        Run ingestion pipeline with the given options and return a report.

        Args:
            options: Ingestion options controlling scan, filters, and pipeline behavior.

        Returns:
            Report dict with summary of scan + ingest stages.
        """
        # Ensure settings are synced before running
        sync_settings_json()

        # Phase 1: Discovery
        logger.info("Starting discovery phase...")
        discovery_opts = self._to_discovery_options(options)
        discovered_files, visited_dirs = self._discovery.discover(discovery_opts, use_cache=True)
        strategy_run_id = options.run_id or str(uuid.uuid4())
        phase_manager = self._build_phase_manager(strategy_run_id)
        sorted_files = sort_paths_by_size_desc(discovered_files)
        phase_manager.record_discovered_files(sorted_files, visited_dirs)

        if not sorted_files:
            logger.info("No files to process. Exiting.")
            return {
                "status": "no_files",
                "run_id": strategy_run_id,
                "discovery": {"total_files": 0, "visited_dirs": visited_dirs},
                "pipeline": {"processed_files": 0},
            }

        logger.info("Discovered %d file(s) from %d directories.", len(discovered_files), visited_dirs)

        if getattr(options, "dry_run", False):
            logger.info("Dry-run flagged; skipping preprocessing and ingestion.")
            return {
                "status": "dry_run",
                "run_id": strategy_run_id,
                "discovery": {"total_files": len(sorted_files), "visited_dirs": visited_dirs},
                "pipeline": {
                    "processed_files": 0,
                    "ingested": 0,
                    "failed": 0,
                    "candidates": len(sorted_files),
                },
            }

        pipeline_result, strategy_name = self._execute_phased_ingestion(
            sorted_files,
            options,
            phase_manager,
        )

        return {
            "status": "completed",
            "run_id": strategy_run_id,
            "strategy": strategy_name,
            "discovery": {"total_files": len(sorted_files), "visited_dirs": visited_dirs},
            "pipeline": pipeline_result,
        }

    def run_incremental_scan(self, options: IngestionOptions) -> dict:
        """
        Run an incremental scan using Redis cache to detect changes and process only changed files.

        Args:
            options: Ingestion options controlling scan behavior.

        Returns:
            Report dict with summary of scan + ingest stages.
        """
        # Ensure settings are synced before running
        sync_settings_json()

        logger.info("Starting incremental scan...")

        # Use discovery with cache enabled - it will detect changes automatically
        discovery_opts = self._to_discovery_options(options)
        discovered_files, visited_dirs = self._discovery.discover(discovery_opts, use_cache=True)
        strategy_run_id = options.run_id or str(uuid.uuid4())
        phase_manager = self._build_phase_manager(strategy_run_id)

        # Sort changed files by size (small to large for efficiency)
        sorted_files = sort_paths_by_size_desc(discovered_files)
        phase_manager.record_discovered_files(sorted_files, visited_dirs)

        if not sorted_files:
            logger.info("No changed files detected. Exiting.")
            return {
                "status": "no_changes",
                "run_id": strategy_run_id,
                "discovery": {"changed_files": 0, "visited_dirs": visited_dirs},
                "pipeline": {"processed_files": 0},
            }

        logger.info("Detected %d file(s) for processing...", len(sorted_files))

        if getattr(options, "dry_run", False):
            logger.info("Dry-run flagged; skipping incremental ingestion.")
            return {
                "status": "dry_run",
                "run_id": strategy_run_id,
                "discovery": {"changed_files": len(sorted_files), "visited_dirs": visited_dirs},
                "pipeline": {
                    "processed_files": 0,
                    "ingested": 0,
                    "failed": 0,
                    "candidates": len(sorted_files),
                },
            }

        pipeline_result, strategy_name = self._execute_phased_ingestion(
            sorted_files,
            options,
            phase_manager,
        )

        return {
            "status": "completed",
            "run_id": strategy_run_id,
            "strategy": strategy_name,
            "discovery": {"changed_files": len(sorted_files), "visited_dirs": visited_dirs},
            "pipeline": pipeline_result,
        }

    def _build_pipeline(self) -> IngestionPipeline:
        """
        Construct the ingestion pipeline with all required services.

        Returns:
            Fully-initialized IngestionPipeline instance.
        """
        logger.info("Initializing services (LM Studio, EmbeddingService, VectorStore, Pipeline)...")

        # Initialize provider and embedding service
        provider = ProviderFactory(self._config)
        embedding_service = get_embedding_service(self._config, provider)

        # Initialize vector store
        vector_store = get_vector_store(self._config)

        pipeline_options = PipelineOptions(
            chunk_size=getattr(self._config, "CHUNK_SIZE", 800),
            chunk_overlap=getattr(self._config, "CHUNK_OVERLAP", 50),
            embedding_token_limit=getattr(self._config, "EMBEDDING_MAX_TOKENS", 0) or 0,
            tenant_id=(
                getattr(self._config, "WEAVIATE_DEFAULT_TENANT", None)
                if getattr(self._config, "WEAVIATE_MULTI_TENANCY", False)
                else None
            ),
            owner_id=getattr(self._config, "INGESTION_OWNER_ID", None),
            visibility=getattr(self._config, "INGESTION_VISIBILITY", "private"),
            allowed_user_ids=list(getattr(self._config, "INGESTION_ALLOWED_USER_IDS", ()) or ()),
            splitter_strategy=getattr(self._config, "INGESTION_SPLITTER_STRATEGY", None),
            tokenizer_model_name=getattr(self._config, "INGESTION_TOKENIZER_MODEL", "gpt-4o-mini"),
            markdown_levels=getattr(self._config, "INGESTION_MARKDOWN_LEVELS", None),
            semantic_embeddings=getattr(self._config, "INGESTION_SEMANTIC_EMBEDDINGS", None),
            include_duplicates_patterns=tuple(getattr(self._config, "INGEST_DUPLICATE_PATTERNS", ()) or ()),
        )

        pipeline = IngestionPipeline.from_options(
            embedding_service=embedding_service,
            vector_store=vector_store,
            options=pipeline_options,
            cache_manager=self._cache_manager,
        )

        logger.info("Ingestion pipeline built successfully.")
        return pipeline

    def _build_phase_manager(self, run_id: str) -> PhaseManager:
        ttl = getattr(
            self._config, 
            "INGESTION_PHASE_TTL_SECONDS", 
            getattr(self._config, "INGESTION_PHASE_TTL", 24 * 60 * 60)
        )
        return PhaseManager(cache_manager=self._cache_manager, run_id=run_id, ttl=ttl)

    def _execute_phased_ingestion(
        self,
        file_paths: List[str],
        options: IngestionOptions,
        phase_manager: PhaseManager,
    ) -> tuple[dict, str]:
        """Run preprocessing and ingestion phases in order, using the configured strategy."""
        phased_enabled = getattr(options, "phased_ingestion", None)
        if phased_enabled is None:
            phased_enabled = getattr(self._config, "PHASED_INGESTION_ENABLED", True)

        if not phased_enabled:
            logger.warning(
                "Phased ingestion disabled for run=%s; falling back to legacy pipeline.",
                phase_manager.run_id,
            )
            pipeline = self._build_pipeline()
            result = pipeline.process_batch(file_paths, options)
            phase_manager.record_ingestion_summary(result)
            return result, "legacy"

        strategy = select_strategy(
            self._config,
            self._cache_manager,
            strategy_override=getattr(options, "strategy", None),
            max_ram_override=getattr(options, "max_ram_usage_percent", None),
        )
        phase_id = phase_manager.run_id
        logger.info("Using strategy %s for run %s", strategy.__class__.__name__, phase_id)

        preprocessor = get_ingestion_preprocessor()
        logger.info("Starting preprocessing phase (run=%s)", phase_id)
        preprocessed_records = strategy.preprocess_phase(file_paths, options, preprocessor, phase_manager)
        logger.info("Preprocessing completed for %d files (run=%s)", len(preprocessed_records), phase_id)

        pipeline = self._build_pipeline()
        pipeline.disable_preprocessing = True
        self._configure_resumable_ingestion(pipeline)
        logger.info("Starting ingestion phase (run=%s)", phase_id)
        result = strategy.embedding_phase(preprocessed_records, pipeline, options, phase_manager)
        logger.info("Ingestion phase finished (run=%s)", phase_id)

        self._cleanup_preprocessed_outputs(preprocessed_records, result)

        return result, strategy.__class__.__name__

    def _configure_resumable_ingestion(self, pipeline: IngestionPipeline) -> None:
        if not getattr(self._config, "INGESTION_RESUMABLE_ENABLED", False):
            return
        if not self._cache_manager:
            logger.warning("Resumable ingestion requested but cache manager is unavailable.")
            return
        redis_client = getattr(self._cache_manager, "redis", None)
        if not redis_client:
            logger.warning("Resumable ingestion requested but Redis client is unavailable.")
            return

        try:
            from src.workflows.ingestion.checkpoint import IngestQueue, ChunkRegistry

            pipeline.ingest_queue = IngestQueue(redis_client)
            pipeline.chunk_registry = ChunkRegistry(redis_client)
            logger.info("Resumable ingestion enabled (IngestQueue + ChunkRegistry)")
        except Exception as exc:  # pragma: no cover - best-effort
            logger.warning("Failed to enable resumable ingestion: %s", exc)

    def _cleanup_preprocessed_outputs(self, records: List[Any], result: dict) -> None:
        if not getattr(self._config, "INGESTION_CLEANUP_PREPROCESSED", True):
            return
        if result.get("failed", 0) > 0:
            logger.info("Skipping preprocessed cleanup due to failures.")
            return

        base_dir = Path(getattr(self._config, "PREPROCESSING_WORK_DIR", "/tmp")).resolve()
        cleaned = 0
        for record in records:
            original = getattr(record, "original_path", None)
            processed = getattr(record, "processed_path", None)
            if not processed or processed == original:
                continue
            try:
                path = Path(processed)
                if path.is_file() and base_dir in path.resolve().parents:
                    path.unlink(missing_ok=True)
                    cleaned += 1
            except Exception as exc:  # pragma: no cover - best-effort cleanup
                logger.debug("Failed to clean preprocessed file %s: %s", processed, exc)
        if cleaned:
            logger.info("Cleaned %d preprocessed file(s).", cleaned)
