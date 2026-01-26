import gc
from collections import deque
from pathlib import Path
from typing import Iterable, List

from src.backends.storage.cache.ingestion import IngestionCacheManager
from src.workflows.ingestion.options import IngestionOptions
from src.workflows.ingestion.phases import PhaseManager, PreprocessedFileRecord
from src.workflows.ingestion.pipeline import IngestionPipeline
from src.workflows.ingestion.preprocessor import FilePreprocessor
from src.workflows.ingestion.strategies.base import IngestionStrategy


class LowMemoryStrategy(IngestionStrategy):
    """Sequential ingestion strategy that keeps memory use low."""

    def __init__(self, config: object, cache_manager: IngestionCacheManager | None = None) -> None:
        super().__init__(config, cache_manager)
        self.batch_size = max(1, getattr(config, "INGESTION_LOW_MEMORY_BATCH_SIZE", 1))

    def preprocess_phase(
        self,
        file_paths: Iterable[str],
        options: IngestionOptions,
        preprocessor: FilePreprocessor,
        phase_manager: PhaseManager,
    ) -> List[PreprocessedFileRecord]:
        queue = deque(file_paths)
        preprocessed: List[PreprocessedFileRecord] = []
        seen: set[str] = set()
        processed_since_gc = 0
        failed = 0
        skipped = 0

        while queue:
            path = queue.popleft()
            cached = self._reuse_preprocess_status(path, phase_manager)
            if cached:
                if cached.processed_path not in seen:
                    seen.add(cached.processed_path)
                    preprocessed.append(cached)
                continue
            if self._should_skip_failed(phase_manager, path):
                skipped += 1
                continue
            records = self._preprocess_single(path, preprocessor)
            if not records:
                phase_manager.set_preprocess_status(path, "failed", error="preprocessor_returned_empty")
                failed += 1
                continue

            for record in records:
                phase_manager.set_preprocess_status(
                    record.original_path,
                    "ok",
                    processed_path=record.processed_path,
                )
                if record.processed_path in seen:
                    continue
                seen.add(record.processed_path)

                if Path(record.processed_path).is_dir():
                    queue.extend(self._enumerate_directory(record.processed_path))
                    continue

                preprocessed.append(record)
                processed_since_gc += 1

            if processed_since_gc >= self.batch_size:
                gc.collect()
                processed_since_gc = 0

        phase_manager.record_preprocessed_files(preprocessed, skipped=skipped, failed=failed)
        return preprocessed

    def embedding_phase(
        self,
        preprocessed_records: List[PreprocessedFileRecord],
        pipeline: IngestionPipeline,
        options: IngestionOptions,
        phase_manager: PhaseManager,
    ) -> dict:
        self._prepare_pipeline_workers(pipeline, 1)
        file_paths = [record.processed_path for record in preprocessed_records]
        result = self._run_ingestion(pipeline, file_paths, options, phase_manager)
        phase_manager.record_ingestion_summary(result)
        return result
