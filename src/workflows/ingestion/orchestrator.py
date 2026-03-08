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
from src.ingestion.ledger.ledger_repository import LedgerRepository
from src.backends.storage.vector import get_vector_store
from src.workflows.query.embeddings_factory import get_embedding_service
from src.backends.llm.factory import ProviderFactory
from src.utils.file_operations import sort_paths_by_size_desc
from src.workflows.query.conf import sync_settings_json
from src.conf import settings as runtime_settings

# New optimization components
from src.workflows.ingestion.wave_planner import create_default_wave_orchestrator
from src.workflows.ingestion.watermark_cleanup import create_default_cleanup

# Checkpoint system
from src.workflows.ingestion.checkpoint.scan_checkpointer import ScanCheckpointer
from src.workflows.ingestion.checkpoint.ingest_queue import IngestQueue
from src.workflows.ingestion.checkpoint.chunk_registry import ChunkRegistry

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

        # LedgerRepository — single source of truth for file-skip decisions
        self._ledger = LedgerRepository()

        # Initialize scan checkpointer for resumable scanning
        scan_checkpointer = None
        if getattr(self._config, "SCAN_CHECKPOINT_ENABLED", True):
            try:
                scan_checkpointer = ScanCheckpointer()
                logger.info("Scan checkpoint system enabled")
            except Exception as e:
                logger.warning("Failed to initialize scan checkpointer: %s", e)

        # Initialize discovery service (uses cache internally)
        self._discovery = FileDiscoveryService(
            cache_manager=self._cache_manager,
            scan_checkpointer=scan_checkpointer
        )

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

        # ------------------------------------------------------------------
        # Integrity check: detect vector store / ledger desync.
        #
        # If the ledger has DONE entries but Weaviate is empty, it means the
        # vector store was wiped (volume deleted, manual collection drop, etc.)
        # without resetting the ledger. Without this check every file would be
        # skipped as "already ingested" and the KB would stay empty forever.
        # ------------------------------------------------------------------
        self._reconcile_ledger_with_vector_store()

        # --reclassify: invalidate all score-cache entries before scanning
        if getattr(options, "reclassify", False):
            try:
                from src.workflows.ingestion.discovery.score_cache import invalidate_all_scores
                f_del, d_del = invalidate_all_scores()
                logger.info(
                    "--reclassify: invalidated %d file scores and %d directory scores",
                    f_del, d_del
                )
            except Exception as exc:
                logger.warning("--reclassify: invalidation failed: %s", exc)

        # Initialize coverage tracking if enabled
        coverage_enabled = getattr(self._config, "INGESTION_COVERAGE_ENABLED", False)
        coverage_report = None
        
        if coverage_enabled:
            try:
                # Initialize coverage tracker
                from src.workflows.ingestion.coverage_tracker import (
                    init_global_coverage_tracker,
                    start_coverage_tracking,
                )
                coverage_output_dir = getattr(
                    self._config, "INGESTION_COVERAGE_OUTPUT_DIR", "tools/debug/coverage/coverage_reports"
                )
                init_global_coverage_tracker(source_dirs=['src'], output_dir=coverage_output_dir)
                start_coverage_tracking()
                logger.info("Coverage tracking enabled for this ingestion run")
            except Exception as e:
                logger.warning(f"Failed to initialize coverage tracking: {e}")
                coverage_enabled = False

        # Phase 1: Discovery
        logger.info("Starting discovery phase...")
        discovery_opts = self._to_discovery_options(options)
        
        # Use resumable discovery if run_id is provided (for resuming)
        if options.run_id and hasattr(self._discovery, 'discover_resumable'):
            discovered_files, visited_dirs, scan_run_id = self._discovery.discover_resumable(
                discovery_opts, 
                scan_run_id=options.run_id,
                use_cache=True
            )
            logger.info("Resumed scan run: %s", scan_run_id)
        else:
            discovered_files, visited_dirs = self._discovery.discover(discovery_opts, use_cache=True)
            
        strategy_run_id = options.run_id or str(uuid.uuid4())
        phase_manager = self._build_phase_manager(strategy_run_id)
        sorted_files = sort_paths_by_size_desc(discovered_files)
        phase_manager.record_discovered_files(sorted_files, visited_dirs)

        if not sorted_files:
            logger.info("No files to process. Exiting.")
            
            # Generate coverage report if enabled
            if coverage_enabled:
                coverage_report = self._generate_coverage_report()
            
            return {
                "status": "no_files",
                "run_id": strategy_run_id,
                "discovery": {"total_files": 0, "visited_dirs": visited_dirs},
                "pipeline": {"processed_files": 0},
                "coverage": coverage_report,
            }

        logger.info("Discovered %d file(s) from %d directories.", len(discovered_files), visited_dirs)

        if getattr(options, "dry_run", False):
            logger.info("Dry-run flagged; skipping preprocessing and ingestion.")
            
            # Generate coverage report if enabled
            if coverage_enabled:
                coverage_report = self._generate_coverage_report()
            
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
                "coverage": coverage_report,
            }

        pipeline_result, strategy_name = self._execute_phased_ingestion(
            sorted_files,
            options,
            phase_manager,
        )

        # Generate coverage report if enabled
        if coverage_enabled:
            coverage_report = self._generate_coverage_report()

        return {
            "status": "completed",
            "run_id": strategy_run_id,
            "strategy": strategy_name,
            "discovery": {"total_files": len(sorted_files), "visited_dirs": visited_dirs},
            "pipeline": pipeline_result,
            "coverage": coverage_report,
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
        
        # Try to use resumable scanning with persistent run_id for autoscan
        # This prevents re-scanning already visited directories
        scan_run_id = None
        discovered_files = []
        visited_dirs = 0
        
        # Generate a persistent run_id for autoscan based on root paths
        if not options.run_id and hasattr(self._discovery, 'discover_resumable'):
            # Create a deterministic run_id based on root paths for autoscan
            import hashlib
            root_paths_str = ','.join(sorted(options.root_paths))
            scan_run_id = f"autoscan_{hashlib.md5(root_paths_str.encode()).hexdigest()[:16]}"
            logger.info("Using persistent scan run_id for autoscan: %s", scan_run_id)
            
            # Try to resume existing scan or start new one
            discovered_files, visited_dirs, new_run_id = self._discovery.discover_resumable(
                discovery_opts, 
                scan_run_id=scan_run_id,
                use_cache=True
            )
            logger.info("Resumable scan completed: files=%d, dirs=%d", len(discovered_files), visited_dirs)
        else:
            # Fallback to regular discovery
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
                "scan_run_id": scan_run_id,
                "discovery": {"changed_files": 0, "visited_dirs": visited_dirs},
                "pipeline": {"processed_files": 0},
            }

        logger.info("Detected %d file(s) for processing...", len(sorted_files))

        if getattr(options, "dry_run", False):
            logger.info("Dry-run flagged; skipping incremental ingestion.")
            return {
                "status": "dry_run",
                "run_id": strategy_run_id,
                "scan_run_id": scan_run_id,
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
            "scan_run_id": scan_run_id,
            "strategy": strategy_name,
            "discovery": {"changed_files": len(sorted_files), "visited_dirs": visited_dirs},
            "pipeline": pipeline_result,
        }

    def _reconcile_ledger_with_vector_store(self) -> None:
        """Detect and auto-heal a ledger / vector-store desync.

        The problem this fixes
        ----------------------
        The ledger (SQLite) tracks which files have been fully ingested.
        When the user wipes Weaviate (deletes the volume, drops the collection,
        or runs a manual reset) the ledger is NOT touched. On the next ingestion
        run every file is skipped as "already ingested" because the ledger says
        UPSERT=DONE — but Weaviate is empty, so the KB stays empty forever.

        Detection
        ---------
        1. Ask the ledger how many files it believes are fully ingested.
        2. Ask Weaviate how many objects it actually holds.
        3. If the ledger says > 0 done but Weaviate has 0 objects → desync.

        Healing
        -------
        Call ledger.invalidate_all() to reset every UPSERT stage to PENDING
        and clear last_seen_fingerprint. Also delete the ingestion_catalog.json
        so the catalog-level check does not block files either.
        The next ingestion run will process every file from scratch.
        """
        try:
            ledger_done = self._ledger.count_done_upserts()
            if ledger_done == 0:
                return

            vector_store = get_vector_store(self._config)
            weaviate_count = self._count_weaviate_objects(vector_store)

            if weaviate_count > 0:
                return

            logger.warning(
                "INTEGRITY: Ledger has %d DONE entries but Weaviate is empty. "
                "Auto-invalidating ledger so all files will be re-ingested.",
                ledger_done,
            )
            reset = self._ledger.invalidate_all()
            self._reset_ingestion_catalog()
            logger.warning(
                "INTEGRITY: Reset complete — %d ledger entries cleared, "
                "ingestion catalog wiped. Full re-ingestion will run.",
                reset,
            )
        except Exception as exc:
            logger.warning("INTEGRITY: Reconciliation check failed (non-fatal): %s", exc)

    def _count_weaviate_objects(self, vector_store) -> int:
        """Return the total number of objects in Weaviate across all tenants.
        Returns 0 on any error so we never falsely skip files.
        """
        try:
            cfg = self._config
            client = getattr(vector_store, "client", None)
            schema = getattr(vector_store, "schema", None)
            if client is None and schema is not None:
                client = getattr(schema, "client", None)
            if client is None:
                return 0

            class_name = getattr(cfg, "WEAVIATE_CLASS", "RAGDocument")
            multi_tenancy = getattr(cfg, "WEAVIATE_MULTI_TENANCY", True)
            collection = client.collections.get(class_name)
            total = 0

            if multi_tenancy:
                tenants = collection.tenants.get()
                for t in tenants:
                    try:
                        resp = collection.with_tenant(t.name).aggregate.over_all(total_count=True)
                        total += resp.total_count or 0
                    except Exception:
                        pass
            else:
                resp = collection.aggregate.over_all(total_count=True)
                total = resp.total_count or 0

            return total
        except Exception as exc:
            logger.debug("_count_weaviate_objects failed: %s", exc)
            return 0

    def _reset_ingestion_catalog(self) -> None:
        """Delete ingestion_catalog.json so the catalog-level skip check is cleared."""
        import os
        from src.workflows.ingestion.pipeline.pipeline import CATALOG_PATH
        try:
            if os.path.exists(CATALOG_PATH):
                os.remove(CATALOG_PATH)
                logger.info("INTEGRITY: Deleted ingestion_catalog.json")
        except Exception as exc:
            logger.warning("INTEGRITY: Could not delete ingestion_catalog.json: %s", exc)

    def _build_pipeline(self) -> IngestionPipeline:
        """
        Construct the ingestion pipeline with all required services.

        Returns:
            Fully-initialized IngestionPipeline instance.
        """
        logger.info("Initializing services (LM Studio, EmbeddingService, VectorStore, Pipeline)...")

        # Initialize provider and embedding service
        provider = ProviderFactory(self._config)
        embedding_service = get_embedding_service(self._config, provider, context="ingest")

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

        ingest_queue = IngestQueue()
        chunk_registry = ChunkRegistry()

        pipeline = IngestionPipeline.from_options(
            embedding_service=embedding_service,
            vector_store=vector_store,
            options=pipeline_options,
            cache_manager=self._cache_manager,
            ingest_queue=ingest_queue,
            chunk_registry=chunk_registry,
        )
        pipeline.ledger = self._ledger

        # Wire Neo4j knowledge-graph extraction when enabled.
        if getattr(self._config, "NEO4J_ENABLED", False):
            try:
                from src.backends.storage.graph.neo4j_repository import Neo4jRepository
                from src.backends.storage.graph.neo4j_schema import ensure_schema

                neo4j_repo = Neo4jRepository(self._config)
                ensure_schema(neo4j_repo.driver)
                pipeline.neo4j_repo = neo4j_repo
                pipeline.chat_service = provider.chat()
                logger.info("Neo4j entity extraction wired into ingestion pipeline.")
            except Exception as exc:
                logger.warning(
                    "Failed to initialize Neo4j for ingestion entity extraction (non-fatal): %s", exc
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

        # Initialize optimization components
        wave_orchestrator = None
        watermark_cleanup = None

        # Determine whether to use the optimized components
        use_optimized_pipeline = getattr(self._config, "OPTIMIZED_INGESTION_ENABLED", True)

        if use_optimized_pipeline:
            try:
                # Wave Planner
                wave_orchestrator = create_default_wave_orchestrator()
                logger.info("Wave Planner enabled for wave-based processing")

                # Watermark Cleanup
                watermark_cleanup = create_default_cleanup(self._config)
                logger.info("Watermark Cleanup enabled for disk management")

            except Exception as e:
                logger.warning("Error initializing optimized components: %s", e)
                logger.info("Continuing with standard pipeline")
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
        
        # Use the Wave Planner if enabled
        if use_optimized_pipeline and wave_orchestrator:
            try:
                # Run wave-based preprocessing
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
                    "Wave-based preprocessing completed: %d waves, %d files",
                    wave_result.get('successful_waves', 0),
                    len(preprocessed_records)
                )
            except Exception as e:
                logger.error("Wave preprocessing error: %s", e)
                logger.info("Continuing with standard preprocessing")
                preprocessed_records = strategy.preprocess_phase(file_paths, options, preprocessor, phase_manager)
        else:
            preprocessed_records = strategy.preprocess_phase(file_paths, options, preprocessor, phase_manager)
        
        logger.info("Preprocessing completed for %d files (run=%s)", len(preprocessed_records), phase_id)

        pipeline = self._build_pipeline()
        pipeline.disable_preprocessing = True
        
        logger.info("Starting ingestion phase (run=%s)", phase_id)
        
        # Run the embedding phase with optimized components
        if use_optimized_pipeline:
            try:
                # Run embedding with Wave Planner if enabled
                if wave_orchestrator:
                    wave_result = wave_orchestrator.execute_waves(
                        [getattr(rec, 'original_path', '') for rec in preprocessed_records],
                        process_callback=lambda wave_files: strategy.embedding_phase(
                            [rec for rec in preprocessed_records 
                             if getattr(rec, 'original_path', '') in wave_files],
                            pipeline, options, phase_manager
                        )
                    )
                    
                    # Consolidate results from all waves
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
                logger.error("Optimized pipeline error: %s", e)
                logger.info("Continuing with standard pipeline")
                result = strategy.embedding_phase(preprocessed_records, pipeline, options, phase_manager)
        else:
            result = strategy.embedding_phase(preprocessed_records, pipeline, options, phase_manager)
        
        logger.info("Ingestion phase finished (run=%s)", phase_id)

        # Run Watermark Cleanup if enabled
        if use_optimized_pipeline and watermark_cleanup:
            try:
                # Clean up preprocessed files (only temp copies, not originals)
                for record in preprocessed_records:
                    original_path = getattr(record, 'original_path', None)
                    processed_path = getattr(record, 'processed_path', None)
                    if processed_path and processed_path != original_path:
                        watermark_cleanup.cleanup_completed_file(processed_path, immediate=True)
                
                # Run general cleanup if needed
                disk_usage = watermark_cleanup.get_disk_usage()
                if disk_usage.usage_percent >= watermark_cleanup.watermark_percent:
                    cleanup_result = watermark_cleanup.run_cleanup(aggressive=False)
                    logger.info(
                        "Watermark cleanup executed: %.2f MB freed",
                        cleanup_result.get('freed_mb', 0)
                    )
            except Exception as e:
                logger.warning("Watermark Cleanup error: %s", e)
        else:
            self._cleanup_preprocessed_outputs(preprocessed_records, result)

        return result, strategy.__class__.__name__

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

    def _generate_coverage_report(self) -> Optional[Dict[str, Any]]:
        """
        Generate coverage report using the global coverage tracker.
        
        Returns:
            Coverage report dictionary or None if coverage tracking is not enabled
        """
        try:
            from src.workflows.ingestion.coverage_tracker import (
                stop_coverage_tracking,
                generate_coverage_reports,
                get_orphaned_code_analysis,
            )
            
            # Stop coverage tracking and generate reports
            stop_coverage_tracking()
            reports = generate_coverage_reports()
            
            if not reports:
                return None
            
            # Get orphaned code analysis
            orphaned_analysis = get_orphaned_code_analysis() or {}
            
            # Combine reports into a summary
            coverage_report = {
                "reports_generated": True,
                "report_paths": reports,
                "orphaned_code_analysis": orphaned_analysis,
                "summary": {
                    "orphaned_files": orphaned_analysis.get("total_orphaned_files", 0),
                    "orphaned_lines": orphaned_analysis.get("total_orphaned_lines", 0),
                    "total_files": orphaned_analysis.get("total_files", 0),
                }
            }
            
            logger.info(
                "Coverage report generated: %d orphaned files, %d orphaned lines",
                coverage_report["summary"]["orphaned_files"],
                coverage_report["summary"]["orphaned_lines"]
            )
            
            return coverage_report
            
        except Exception as e:
            logger.warning(f"Failed to generate coverage report: {e}")
            return {
                "reports_generated": False,
                "error": str(e)
            }