import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Any, Dict, List, Optional, Set

from src import logger
from src.workflows.ingestion.options import PipelineOptions
from src.workflows.ingestion.catalog import IngestionCatalog
from src.backends.storage.cache.ingestion import IngestionCacheManager
from src.workflows.query.interfaces.embedding_interface import EmbeddingInterface
from src.workflows.query.interfaces.vector_interface import VectorInterface
from src.workflows.query.audit.decorators import logged, timed
from src.workflows.query.audit import EmbeddingProgress
from src.workflows.query.audit import ProgressBar

from .file_processor import process_candidate_file
from .splitters import SplitterStrategy, build_text_splitter
from .state_helpers import finalize_ingestion_run, record_directory_listing
from src.utils.text import effective_limit
from src.workflows.ingestion.adaptive_workers import (
    AdaptiveWorkerController,
    is_adaptive_enabled,
    get_adaptive_batch_size,
)

# Importaciones para type hints de nuevos componentes
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.workflows.ingestion.resource_pools import IngestionPools


CATALOG_PATH = os.environ.get(
    "INGESTION_CATALOG_PATH",
    os.path.join("data", "ingestion_catalog.json"),
)


class IngestionPipeline:
    """Pipeline for ingesting documents and generating embeddings using modern splitters."""

    def __init__(
        self,
        embedding_service: EmbeddingInterface,
        vector_store: VectorInterface,
        options: PipelineOptions,
        cache_manager: Optional[IngestionCacheManager] = None,
        ingest_queue=None,
        chunk_registry=None,
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.options = options

        # Cache manager for incremental ingestion
        self.cache_manager = cache_manager

        # Checkpoint components for resumable ingestion
        self.ingest_queue = ingest_queue
        self.chunk_registry = chunk_registry

        # New optimization components
        self.resource_pools = None
        self.idempotency_manager = None
        self.ledger = None  # LedgerRepository — set by orchestrator

        self.owner_id = options.owner_id
        self.visibility = options.visibility
        self.allowed_user_ids = list(options.allowed_user_ids)
        self.tenant_id = options.tenant_id

        self.chunk_size = options.chunk_size
        self.chunk_overlap = options.chunk_overlap

        # Default to a fully offline-safe strategy.
        #
        # TokenTextSplitter relies on tiktoken (and therefore on external encoding files)
        # which can be downloaded at runtime. In offline environments this causes the
        # ingestion pipeline to fail before it even starts.
        self.splitter_strategy = options.splitter_strategy or SplitterStrategy.RECURSIVE

        # Prefer explicit tokenizer model, otherwise reuse embedding model name if available.
        self.tokenizer_model_name = options.tokenizer_model_name or getattr(
            embedding_service, "model_name", None
        ) or getattr(embedding_service, "_model_name", None)

        self.markdown_levels = options.markdown_levels
        self.semantic_embeddings = options.semantic_embeddings

        self.text_splitter = build_text_splitter(self.splitter_strategy, options, self.markdown_levels)
        self.catalog = IngestionCatalog(CATALOG_PATH)
        self._observed_files: Set[str] = set()
        self._observed_directories: Set[str] = set()
        self._file_context: Dict[str, Optional[Any]] = {
            "file_index": None,
            "total_files": None,
            "directory_path": None,
        }
        self._current_file_info: Optional[Dict[str, Any]] = None

        # Cache of hashes seen/known to exist to avoid duplicate embeddings within a run.
        self._existing_hash_cache: Set[str] = set()

        self.embedding_token_limit = max(0, getattr(options, "embedding_token_limit", 0))
        self.embedding_effective_limit = effective_limit(self.embedding_token_limit)

        self.progress = EmbeddingProgress()
        self.progress.set_chunk_tokens(self.embedding_effective_limit or self.chunk_size or 500)

        # Thread-safety locks for parallel processing
        self._hash_cache_lock = Lock()
        self._catalog_lock = Lock()
        self._progress_lock = Lock()

        # Max parallel workers (default: 4, set to 1 to disable parallelization)
        self._max_workers = max(1, int(os.environ.get("RAG_PARALLEL_WORKERS", "4")))
        self.disable_preprocessing = False

    def start_ingestion_run(self) -> None:
        """Reset per-run state before ingesting."""
        self._observed_files = set()
        self._observed_directories = set()
        self._existing_hash_cache = set()
        self._file_context = {
            "file_index": None,
            "total_files": None,
            "directory_path": None,
        }
        self._current_file_info = None
        self.progress.reset()

    def finish_ingestion_run(self) -> None:
        """Finalize the ingestion run and persist catalog state."""
        finalize_ingestion_run(self)

    @classmethod
    def from_options(
        cls,
        embedding_service: EmbeddingInterface,
        vector_store: VectorInterface,
        options: PipelineOptions,
        cache_manager: Optional[IngestionCacheManager] = None,
        ingest_queue=None,
        chunk_registry=None,
    ) -> "IngestionPipeline":
        return cls(
            embedding_service=embedding_service,
            vector_store=vector_store,
            options=options,
            cache_manager=cache_manager,
            ingest_queue=ingest_queue,
            chunk_registry=chunk_registry,
        )

    def hash_exists(self, content_hash: str) -> bool:
        """Thread-safe check if hash exists in cache."""
        with self._hash_cache_lock:
            return content_hash in self._existing_hash_cache

    def add_hash(self, content_hash: str) -> None:
        """Thread-safe addition of hash to cache."""
        with self._hash_cache_lock:
            self._existing_hash_cache.add(content_hash)

    def _process_single_file_safe(
        self,
        full_path: str,
        file_index: int,
        total_files: int,
        directory_path: str,
    ) -> tuple[str, bool, Optional[str]]:
        """Thread-safe wrapper for processing a single file.

        Returns:
            Tuple of (file_path, success, error_message)
        """
        try:
            process_candidate_file(
                self,
                full_path,
                file_index=file_index,
                total_files=total_files,
                directory_path=directory_path,
            )
            return (full_path, True, None)
        except Exception as e:
            error_msg = f"Error processing {full_path}: {e}"
            logger.error(error_msg)
            return (full_path, False, str(e))

    def ingest_files(
        self,
        file_paths: List[str],
        *,
        directory_path: Optional[str] = None,
        per_file: bool = False,
    ) -> tuple[int, int]:
        """Ingest a list of file paths without rescanning the filesystem."""
        if not file_paths:
            return 0, 0

        total_files = len(file_paths)
        ingested = 0
        failed = 0

        if per_file or self._max_workers <= 1:
            for idx, full_path in enumerate(file_paths, start=1):
                dir_path = directory_path or os.path.dirname(full_path)
                _, success, _ = self._process_single_file_safe(
                    full_path,
                    idx,
                    total_files,
                    dir_path,
                )
                if success:
                    ingested += 1
                else:
                    failed += 1
            return ingested, failed

        bar: ProgressBar | None = None
        if total_files > 0:
            bar = ProgressBar(
                total=total_files,
                stream=sys.stdout,
                prefix="Ingest",
                rewrite=None,
                min_interval_seconds=1.0,
            )

        adaptive = is_adaptive_enabled()
        controller = AdaptiveWorkerController(
            min_workers=max(1, min(2, self._max_workers)),
            max_workers=self._max_workers,
        )
        batch_size = get_adaptive_batch_size() if adaptive else len(file_paths)

        try:
            completed_count = 0
            # Process in sub-batches so the worker count can be re-evaluated
            # between batches when adaptive mode is on.
            for batch_start in range(0, total_files, batch_size):
                sub_batch = file_paths[batch_start:batch_start + batch_size]
                workers = controller.get_workers() if adaptive else self._max_workers

                with ThreadPoolExecutor(max_workers=workers) as executor:
                    future_to_file = {
                        executor.submit(
                            self._process_single_file_safe,
                            full_path,
                            batch_start + idx + 1,
                            total_files,
                            directory_path or os.path.dirname(full_path),
                        ): full_path
                        for idx, full_path in enumerate(sub_batch)
                    }

                    for future in as_completed(future_to_file):
                        file_path = future_to_file[future]
                        _, success, _ = future.result()
                        completed_count += 1
                        if success:
                            ingested += 1
                        else:
                            failed += 1

                        if bar:
                            bar.update(
                                completed_count,
                                message=os.path.basename(file_path) or file_path,
                            )
        finally:
            if bar:
                bar.finish(message="done")

        return ingested, failed

    def ingest_files_resumable(
        self,
        file_paths: List[str],
        run_id: str,
        scan_run_id: Optional[str] = None,
        consumer_name: Optional[str] = None,
    ) -> tuple[int, int, int]:
        """Ingest files using persistent queue for resumability.

        This method uses IngestQueue for persistent job tracking and enables:
        - Resuming after crashes or interruptions
        - Retry logic with exponential backoff
        - Dead letter queue for permanently failed jobs

        Args:
            file_paths: List of file paths to ingest
            run_id: Ingestion run identifier
            scan_run_id: Optional scan run that discovered these files
            consumer_name: Optional consumer name (defaults to hostname+pid)

        Returns:
            Tuple of (ingested_count, failed_count, enqueued_count)
        """
        if not self.ingest_queue:
            raise RuntimeError("IngestQueue not configured. Use ingest_files() instead.")

        if not file_paths:
            return 0, 0, 0

        # Generate consumer name if not provided
        if not consumer_name:
            import socket
            hostname = socket.gethostname()
            pid = os.getpid()
            consumer_name = f"{hostname}_{pid}"

        # Enqueue all files for processing
        logger.info(
            "Enqueueing %d file(s) for resumable ingestion (run_id=%s)",
            len(file_paths),
            run_id
        )

        job_ids = self.ingest_queue.enqueue_batch(
            file_paths=file_paths,
            run_id=run_id,
            scan_run_id=scan_run_id,
        )

        logger.info("Enqueued %d job(s), starting processing", len(job_ids))

        # Process jobs from queue
        ingested = 0
        failed = 0
        total_processed = 0

        # Create progress bar
        bar: ProgressBar | None = None
        if len(file_paths) > 0:
            bar = ProgressBar(
                total=len(file_paths),
                stream=sys.stdout,
                prefix="Ingest",
                rewrite=None,
                min_interval_seconds=1.0,
            )

        adaptive = is_adaptive_enabled()
        controller = AdaptiveWorkerController(
            min_workers=max(1, min(2, self._max_workers)),
            max_workers=self._max_workers,
        )

        try:
            # Process until queue is empty
            while True:
                workers = controller.get_workers() if adaptive else self._max_workers

                # Dequeue jobs (blocking with 1 second timeout)
                jobs = self.ingest_queue.dequeue(
                    consumer_name=consumer_name,
                    count=workers,
                    block=1000,  # 1 second timeout
                )

                if not jobs:
                    # Check if there are abandoned jobs to claim
                    abandoned = self.ingest_queue.claim_abandoned(
                        consumer_name=consumer_name,
                        count=workers,
                    )

                    if not abandoned:
                        # No more jobs, we're done
                        break

                    jobs = abandoned

                # Process jobs (in parallel if workers > 1)
                if workers <= 1:
                    # Sequential processing
                    for job_id, job in jobs:
                        success, error = self._process_job(job)
                        total_processed += 1

                        if success:
                            ingested += 1
                            self.ingest_queue.acknowledge(job_id, success=True)
                        else:
                            failed += 1
                            self.ingest_queue.acknowledge(job_id, success=False, error=error)

                        if bar:
                            bar.update(
                                total_processed,
                                message=os.path.basename(job.file_path) or job.file_path,
                            )
                else:
                    # Parallel processing
                    with ThreadPoolExecutor(max_workers=workers) as executor:
                        future_to_job = {
                            executor.submit(self._process_job, job): (job_id, job)
                            for job_id, job in jobs
                        }

                        for future in as_completed(future_to_job):
                            job_id, job = future_to_job[future]
                            success, error = future.result()
                            total_processed += 1

                            if success:
                                ingested += 1
                                self.ingest_queue.acknowledge(job_id, success=True)
                            else:
                                failed += 1
                                self.ingest_queue.acknowledge(job_id, success=False, error=error)

                            if bar:
                                bar.update(
                                    total_processed,
                                    message=os.path.basename(job.file_path) or job.file_path,
                                )

            logger.info(
                "Resumable ingestion completed: %d ingested, %d failed (run_id=%s)",
                ingested,
                failed,
                run_id,
            )

        finally:
            if bar:
                bar.finish(message="done")

        return ingested, failed, len(job_ids)

    def process_batch(self, file_paths: List[str], options: PipelineOptions | Any) -> Dict[str, Any]:
        """
        Process a pre-discovered batch of files and return a summary dict.

        This is used by the ingestion orchestrator after discovery.
        """
        self.start_ingestion_run()
        try:
            if not file_paths:
                return {"processed_files": 0, "ingested": 0, "failed": 0}

            max_files = getattr(options, "maximum_files", 0) or 0
            if max_files > 0:
                file_paths = file_paths[:max_files]

            directories: Dict[str, List[str]] = {}
            for path in file_paths:
                directory = os.path.dirname(path) or os.path.abspath(".")
                directories.setdefault(directory, []).append(path)

            for directory, files in directories.items():
                record_directory_listing(self, directory, files)

            if getattr(options, "dry_run", False):
                return {
                    "processed_files": 0,
                    "ingested": 0,
                    "failed": 0,
                    "candidates": len(file_paths),
                }

            ingested, failed = self.ingest_files(
                file_paths,
                per_file=bool(getattr(options, "per_file_mode", False)),
            )
            return {
                "processed_files": ingested + failed,
                "ingested": ingested,
                "failed": failed,
            }
        finally:
            self.finish_ingestion_run()

    def _process_job(self, job) -> tuple[bool, Optional[str]]:
        """Process a single ingestion job.

        Args:
            job: Ingestion job instance

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Process the file
            _, success, error = self._process_single_file_safe(
                full_path=job.file_path,
                file_index=1,  # Not meaningful in queue context
                total_files=1,  # Not meaningful in queue context
                directory_path=os.path.dirname(job.file_path),
            )

            if success:
                logger.debug("Successfully processed job: %s", job.file_path)
                return True, None
            else:
                logger.warning("Failed to process job: %s (error=%s)", job.file_path, error)
                return False, error

        except Exception as e:
            error_msg = f"Error processing job {job.file_path}: {e}"
            logger.error(error_msg)
            return False, str(e)

    @logged("Ingesting candidate paths")
    @timed()
    def ingest_paths(self, paths: List[str]) -> None:
        self.start_ingestion_run()

        # Collect all files to process from all paths
        all_files_to_process: List[tuple[str, str]] = []  # (full_path, directory_path)

        for path in paths:
            abs_path = os.path.abspath(path)
            if not os.path.exists(abs_path):
                logger.error("Path does not exist: %s", abs_path)
                continue

            if os.path.isfile(abs_path):
                directory = os.path.dirname(abs_path) or os.path.abspath(".")
                record_directory_listing(self, directory, [abs_path])
                all_files_to_process.append((abs_path, directory))
            else:
                # Directory: walk and collect all files
                for root, _, files in os.walk(abs_path):
                    sorted_files = sorted(files)
                    full_paths = [os.path.join(root, name) for name in sorted_files]
                    record_directory_listing(self, root, full_paths)
                    for filename in sorted_files:
                        full_path = os.path.join(root, filename)
                        all_files_to_process.append((full_path, root))

        total_files = len(all_files_to_process)
        if total_files == 0:
            logger.info("No files to process")
            finalize_ingestion_run(self)
            return

        logger.info(
            "Processing %d files with %d parallel workers",
            total_files,
            self._max_workers,
        )

        bar: ProgressBar | None = None
        if total_files > 0:
            bar = ProgressBar(
                total=total_files,
                stream=sys.stdout,
                prefix="Ingest",
                rewrite=None,
                min_interval_seconds=1.0,
            )

        try:
            completed_count = 0
            failed_count = 0

            # Use ThreadPoolExecutor for parallel processing
            with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                # Submit all files for processing
                future_to_file = {
                    executor.submit(
                        self._process_single_file_safe,
                        full_path,
                        idx + 1,
                        total_files,
                        directory_path,
                    ): (full_path, idx + 1)
                    for idx, (full_path, directory_path) in enumerate(all_files_to_process)
                }

                # Process results as they complete
                for future in as_completed(future_to_file):
                    full_path, file_idx = future_to_file[future]
                    file_path, success, error = future.result()

                    completed_count += 1
                    if not success:
                        failed_count += 1

                    if bar:
                        bar.update(
                            completed_count,
                            message=os.path.basename(file_path) or file_path,
                        )

                    pct = (completed_count / total_files * 100) if total_files else 100.0
                    logger.debug(
                        "Ingest progress: %.2f%% (%d/%d) %s",
                        pct,
                        completed_count,
                        total_files,
                        file_path,
                    )

            if failed_count > 0:
                logger.warning(
                    "Completed with %d failures out of %d files",
                    failed_count,
                    total_files,
                )
        finally:
            if bar:
                bar.finish(message="done")
            self.finish_ingestion_run()
