from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, List, Optional

from src.backends.storage.cache.ingestion import IngestionCacheManager
from src.workflows.ingestion.options import IngestionOptions
from src.workflows.ingestion.phases import PhaseManager, PreprocessedFileRecord
from src.workflows.ingestion.pipeline import IngestionPipeline
from src.workflows.ingestion.preprocessor import FilePreprocessor
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class IngestionStrategy(ABC):
    """Strategy interface that orchestrates the phased ingestion flow."""

    def __init__(self, config: object, cache_manager: Optional[IngestionCacheManager] = None) -> None:
        self.config = config
        self.cache_manager = cache_manager
        self.logger = log

    @abstractmethod
    def preprocess_phase(
        self,
        file_paths: Iterable[str],
        options: IngestionOptions,
        preprocessor: FilePreprocessor,
        phase_manager: PhaseManager,
    ) -> List[PreprocessedFileRecord]:
        """Prepare files sequentially or concurrently before ingestion."""

    @abstractmethod
    def embedding_phase(
        self,
        preprocessed_records: List[PreprocessedFileRecord],
        pipeline: IngestionPipeline,
        options: IngestionOptions,
        phase_manager: PhaseManager,
    ) -> dict:
        """Run ingestion over the preprocessed files."""

    def _preprocess_single(
        self,
        file_path: str,
        preprocessor: FilePreprocessor,
    ) -> List[PreprocessedFileRecord]:
        """Run the preprocessor and capture the output path(s)."""
        try:
            processed = preprocessor.preprocess(Path(file_path))
        except Exception as exc:  # pragma: no cover - best-effort logging
            self.logger.warning("Preprocessing exception for %s: %s", file_path, exc)
            return []

        if processed is None:
            self.logger.warning("Preprocessing failed for %s (tool returned None)", file_path)
            return []

        processed_path = str(processed)
        return [
            PreprocessedFileRecord(
                original_path=file_path,
                processed_path=processed_path,
            )
        ]

    def _should_retry_failed(self) -> bool:
        return bool(getattr(self.config, "INGESTION_PREPROCESS_RETRY_FAILED", True))

    def _reuse_preprocess_status(
        self,
        file_path: str,
        phase_manager: PhaseManager,
    ) -> Optional[PreprocessedFileRecord]:
        status = phase_manager.get_preprocess_status(file_path)
        if not status:
            return None

        if status.get("status") == "ok":
            processed_path = status.get("processed_path") or file_path
            if Path(processed_path).exists():
                return PreprocessedFileRecord(
                    original_path=file_path,
                    processed_path=processed_path,
                    metadata={"resumed": True},
                )
        return None

    def _should_skip_failed(self, phase_manager: PhaseManager, file_path: str) -> bool:
        status = phase_manager.get_preprocess_status(file_path)
        if not status:
            return False
        return status.get("status") == "failed" and not self._should_retry_failed()

    def _enumerate_directory(self, directory: str) -> List[str]:
        """List all files under the directory for further processing."""
        root = Path(directory)
        if not root.is_dir():
            return []
        return [str(path) for path in root.rglob("*") if path.is_file()]

    def _prepare_pipeline_workers(self, pipeline: IngestionPipeline, workers: int) -> None:
        """Adjust the pipeline's worker count for the ingestion phase."""
        pipeline._max_workers = max(1, workers)

    def _run_ingestion(
        self,
        pipeline: IngestionPipeline,
        file_paths: List[str],
        options: IngestionOptions,
        phase_manager: PhaseManager,
    ) -> dict:
        """Run ingestion using resumable queue when configured."""
        if not getattr(pipeline, "ingest_queue", None):
            return pipeline.process_batch(file_paths, options)

        pipeline.start_ingestion_run()
        try:
            ingested, failed, enqueued = pipeline.ingest_files_resumable(
                file_paths,
                run_id=phase_manager.run_id,
            )
            return {
                "processed_files": ingested + failed,
                "ingested": ingested,
                "failed": failed,
                "enqueued": enqueued,
            }
        finally:
            pipeline.finish_ingestion_run()
