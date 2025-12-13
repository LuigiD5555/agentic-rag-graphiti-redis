from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

from src import logger
from src.ingestion.options import PipelineOptions
from src.ingestion.catalog import IngestionCatalog
from src.rag.interfaces.embedding_interface import EmbeddingInterface
from src.rag.interfaces.vector_interface import VectorInterface
from src.rag.audit.decorators import logged, timed
from src.rag.utils import EmbeddingProgress

from .file_processor import process_candidate_file
from .splitters import SplitterStrategy, build_text_splitter
from .state_helpers import finalize_ingestion_run, record_directory_listing
from .text_utils import effective_limit


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
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.options = options

        self.owner_id = options.owner_id
        self.visibility = options.visibility
        self.allowed_user_ids = list(options.allowed_user_ids)
        self.tenant_id = options.tenant_id

        self.chunk_size = options.chunk_size
        self.chunk_overlap = options.chunk_overlap
        self.splitter_strategy = options.splitter_strategy or SplitterStrategy.TOKEN
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

    @classmethod
    def from_options(
        cls,
        embedding_service: EmbeddingInterface,
        vector_store: VectorInterface,
        options: PipelineOptions,
    ) -> "IngestionPipeline":
        return cls(
            embedding_service=embedding_service,
            vector_store=vector_store,
            options=options,
        )

    @logged("Ingesting candidate paths")
    @timed()
    def ingest_paths(self, paths: List[str]) -> None:
        self._observed_files = set()
        self._observed_directories = set()
        self._existing_hash_cache = set()
        self.progress.reset()
        total_paths = len(paths)
        try:
            for path_index, path in enumerate(paths, start=1):
                abs_path = os.path.abspath(path)
                try:
                    if not os.path.exists(abs_path):
                        logger.error("Path does not exist: %s", abs_path)
                        continue

                    if os.path.isfile(abs_path):
                        directory = os.path.dirname(abs_path) or os.path.abspath(".")
                        record_directory_listing(self, directory, [abs_path])
                        process_candidate_file(
                            self,
                            abs_path,
                            file_index=1,
                            total_files=1,
                            directory_path=directory,
                        )
                        continue

                    for root, _, files in os.walk(abs_path):
                        sorted_files = sorted(files)
                        full_paths = [os.path.join(root, name) for name in sorted_files]
                        record_directory_listing(self, root, full_paths)
                        for file_index, filename in enumerate(sorted_files, start=1):
                            full_path = os.path.join(root, filename)
                            process_candidate_file(
                                self,
                                full_path,
                                file_index=file_index,
                                total_files=len(sorted_files),
                                directory_path=root,
                            )
                finally:
                    pct = (path_index / total_paths * 100) if total_paths else 100.0
                    logger.debug("Ingest progress: %.2f%% (%d/%d) %s", pct, path_index, total_paths, abs_path)
        finally:
            finalize_ingestion_run(self)
