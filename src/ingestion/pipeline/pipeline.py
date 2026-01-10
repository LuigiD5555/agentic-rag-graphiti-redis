import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Any, Dict, List, Optional, Set

from src import logger
from src.ingestion.options import PipelineOptions
from src.ingestion.catalog import IngestionCatalog
from src.storage.cache.ingestion import IngestionCacheManager
from src.rag.interfaces.embedding_interface import EmbeddingInterface
from src.rag.interfaces.vector_interface import VectorInterface
from src.rag.audit.decorators import logged, timed
from src.rag.audit import EmbeddingProgress
from src.rag.audit import ProgressBar

from .file_processor import process_candidate_file
from .splitters import SplitterStrategy, build_text_splitter
from .state_helpers import finalize_ingestion_run, record_directory_listing
from src.utils.text import effective_limit
from src.rag.conf import Config

_config = Config()


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
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.options = options

        # Redis-based cache for incremental ingestion
        self.cache_manager = cache_manager

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
    ) -> "IngestionPipeline":
        return cls(
            embedding_service=embedding_service,
            vector_store=vector_store,
            options=options,
            cache_manager=cache_manager,
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

        try:
            completed_count = 0
            with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                future_to_file = {
                    executor.submit(
                        self._process_single_file_safe,
                        full_path,
                        idx + 1,
                        total_files,
                        directory_path or os.path.dirname(full_path),
                    ): (full_path, idx + 1)
                    for idx, full_path in enumerate(file_paths)
                }

                for future in as_completed(future_to_file):
                    file_path, _ = future_to_file[future]
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
