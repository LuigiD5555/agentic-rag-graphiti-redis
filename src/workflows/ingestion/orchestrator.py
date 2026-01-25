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

# Nuevos componentes de optimización
from src.workflows.ingestion.wave_planner import create_default_wave_orchestrator
from src.workflows.ingestion.resource_pools import get_global_ingestion_pools
from src.workflows.ingestion.watermark_cleanup import create_default_cleanup
from src.workflows.ingestion.idempotency import create_default_idempotency_manager

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

        # Initialize cache manager (SQLite-only control plane)
        self._cache_manager = IngestionCacheManager.from_settings(self._export_settings_dict(self._config))

        # Initialize discovery service (uses cache internally)
        self._discovery = FileDiscoveryService(cache_manager=self._cache_manager)

        logger.info("IngestionOrchestrator initialized with control-plane caching.")

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
        Run an incremental scan using cached metadata to detect changes and process only changed files.

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

        # Early return for non-phased ingestion
        if not phased_enabled:
            logger.warning(
                "Phased ingestion disabled for run=%s; falling back to legacy pipeline.",
                phase_manager.run_id,
            )
            pipeline = self._build_pipeline()
            result = pipeline.process_batch(file_paths, options)
            phase_manager.record_ingestion_summary(result)
            return result, "legacy"

        # Inicializar componentes de optimización
        wave_orchestrator = None
        resource_pools = None
        watermark_cleanup = None
        idempotency_manager = None
        
        # Verificar si se deben usar los nuevos componentes
        use_optimized_pipeline = getattr(self._config, "OPTIMIZED_INGESTION_ENABLED", True)
        
        if use_optimized_pipeline:
            try:
                # Wave Planner (Fase 3)
                wave_orchestrator = create_default_wave_orchestrator()
                logger.info("Wave Planner habilitado para procesamiento por olas")
                
                # Resource Pools (Fase 4)
                resource_pools = get_global_ingestion_pools(self._config)
                logger.info("Resource Pools habilitados para control de concurrencia")
                
                # Watermark Cleanup (Fase 5)
                watermark_cleanup = create_default_cleanup(self._config)
                logger.info("Watermark Cleanup habilitado para gestión de disco")
                
                # Idempotency Manager (Fase 6)
                idempotency_manager = create_default_idempotency_manager(self._config)
                logger.info("Idempotency Manager habilitado para reintentos seguros")
                
            except Exception as e:
                logger.warning("Error inicializando componentes optimizados: %s", e)
                logger.info("Continuando con pipeline estándar")
                use_optimized_pipeline = False

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
        
        # Usar Wave Planner si está habilitado
        if use_optimized_pipeline and wave_orchestrator:
            try:
                # Ejecutar preprocesamiento por olas
                wave_result = wave_orchestrator.execute_waves(
                    file_paths,
                    process_callback=lambda wave_files: strategy.preprocess_phase(
                        wave_files, options, preprocessor, phase_manager
                    )
                )
                preprocessed_records = []
                for wave_summary in wave_result.get('wave_summaries', []):
                    if wave_summary.get('result'):
                        preprocessed_records.extend(wave_summary['result'])
                
                logger.info(
                    "Preprocesamiento por olas completado: %d olas, %d archivos",
                    wave_result.get('successful_waves', 0),
                    len(preprocessed_records)
                )
            except Exception as e:
                logger.error("Error en preprocesamiento por olas: %s", e)
                logger.info("Continuando con preprocesamiento estándar")
                preprocessed_records = strategy.preprocess_phase(file_paths, options, preprocessor, phase_manager)
        else:
            preprocessed_records = strategy.preprocess_phase(file_paths, options, preprocessor, phase_manager)
        
        logger.info("Preprocessing completed for %d files (run=%s)", len(preprocessed_records), phase_id)

        pipeline = self._build_pipeline()
        pipeline.disable_preprocessing = True
        
        # Configurar Resource Pools en el pipeline si están habilitados
        if use_optimized_pipeline and resource_pools:
            try:
                pipeline.resource_pools = resource_pools
                logger.info("Resource Pools configurados en el pipeline")
            except Exception as e:
                logger.warning("Error configurando Resource Pools: %s", e)
        
        self._configure_resumable_ingestion(pipeline)
        logger.info("Starting ingestion phase (run=%s)", phase_id)
        
        # Ejecutar fase de embedding con componentes optimizados
        if use_optimized_pipeline:
            try:
                # Configurar Idempotency Manager en el pipeline
                if idempotency_manager:
                    pipeline.idempotency_manager = idempotency_manager
                
                # Ejecutar embedding con Wave Planner si está habilitado
                if wave_orchestrator:
                    wave_result = wave_orchestrator.execute_waves(
                        [getattr(rec, 'original_path', '') for rec in preprocessed_records],
                        process_callback=lambda wave_files: strategy.embedding_phase(
                            [rec for rec in preprocessed_records 
                             if getattr(rec, 'original_path', '') in wave_files],
                            pipeline, options, phase_manager
                        )
                    )
                    
                    # Consolidar resultados de todas las olas
                    result = {
                        'processed_files': 0,
                        'ingested': 0,
                        'failed': 0,
                        'wave_summary': wave_result
                    }
                    
                    for wave_summary in wave_result.get('wave_summaries', []):
                        wave_result_data = wave_summary.get('result')
                        if wave_result_data:
                            result['processed_files'] += wave_result_data.get('processed_files', 0)
                            result['ingested'] += wave_result_data.get('ingested', 0)
                            result['failed'] += wave_result_data.get('failed', 0)
                else:
                    result = strategy.embedding_phase(preprocessed_records, pipeline, options, phase_manager)
                
            except Exception as e:
                logger.error("Error en pipeline optimizado: %s", e)
                logger.info("Continuando con pipeline estándar")
                result = strategy.embedding_phase(preprocessed_records, pipeline, options, phase_manager)
        else:
            result = strategy.embedding_phase(preprocessed_records, pipeline, options, phase_manager)
        
        logger.info("Ingestion phase finished (run=%s)", phase_id)

        # Ejecutar limpieza con Watermark Cleanup si está habilitado
        if use_optimized_pipeline and watermark_cleanup:
            try:
                # Limpiar archivos preprocesados
                for record in preprocessed_records:
                    processed_path = getattr(record, 'processed_path', None)
                    if processed_path:
                        watermark_cleanup.cleanup_completed_file(processed_path, immediate=True)
                
                # Ejecutar limpieza general si es necesario
                disk_usage = watermark_cleanup.get_disk_usage()
                if disk_usage.usage_percent >= watermark_cleanup.watermark_percent:
                    cleanup_result = watermark_cleanup.run_cleanup(aggressive=False)
                    logger.info(
                        "Watermark cleanup ejecutado: %.2f MB liberados",
                        cleanup_result.get('freed_mb', 0)
                    )
            except Exception as e:
                logger.warning("Error en Watermark Cleanup: %s", e)
        else:
            self._cleanup_preprocessed_outputs(preprocessed_records, result)

        return result, strategy.__class__.__name__

    def _configure_resumable_ingestion(self, pipeline: IngestionPipeline) -> None:
        # Early returns for guard conditions
        if not getattr(self._config, "INGESTION_RESUMABLE_ENABLED", False):
            return

        logger.warning(
            "Resumable ingestion is disabled (external cache removed). Use non-resumable ingestion or RabbitMQ pipeline."
        )

    def _cleanup_preprocessed_outputs(self, records: List[Any], result: dict) -> None:
        # Early returns for guard conditions
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
