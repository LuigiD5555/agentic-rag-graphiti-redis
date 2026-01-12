"""Orchestrates end-to-end ingestion into the vector store."""
from typing import Any, Dict, List, Optional

from src.workflows.query.audit import get_logger
from src.workflows.ingestion.discovery.service import FileDiscoveryService
from src.workflows.ingestion.pipeline import IngestionPipeline
from src.workflows.ingestion.options import IngestionOptions, PipelineOptions, DiscoveryOptions
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

        if not discovered_files:
            logger.info("No files to process. Exiting.")
            return {
                "status": "no_files",
                "discovery": {"total_files": 0, "visited_dirs": visited_dirs},
                "pipeline": {"processed_files": 0},
            }

        logger.info("Discovered %d file(s) from %d directories.", len(discovered_files), visited_dirs)

        # Sort files by size for efficient processing
        sorted_files = sort_paths_by_size_desc(discovered_files)

        # Phase 2: Pipeline Execution
        pipeline = self._build_pipeline()
        results = pipeline.process_batch(sorted_files, options)

        return {
            "status": "completed",
            "discovery": {"total_files": len(discovered_files), "visited_dirs": visited_dirs},
            "pipeline": results,
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

        if not discovered_files:
            logger.info("No changed files detected. Exiting.")
            return {
                "status": "no_changes",
                "discovery": {"changed_files": 0, "visited_dirs": visited_dirs},
                "pipeline": {"processed_files": 0},
            }

        logger.info("Detected %d file(s) for processing...", len(discovered_files))

        # Sort changed files by size (small to large for efficiency)
        sorted_files = sort_paths_by_size_desc(discovered_files)

        # Build and run pipeline
        pipeline = self._build_pipeline()
        results = pipeline.process_batch(sorted_files, options)

        return {
            "status": "completed",
            "discovery": {"changed_files": len(discovered_files), "visited_dirs": visited_dirs},
            "pipeline": results,
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
