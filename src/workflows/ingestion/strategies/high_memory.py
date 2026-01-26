from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Iterable, List

from src.backends.storage.cache.ingestion import IngestionCacheManager
from src.workflows.ingestion.options import IngestionOptions
from src.workflows.ingestion.phases import PhaseManager, PreprocessedFileRecord
from src.workflows.ingestion.pipeline import IngestionPipeline
from src.workflows.ingestion.preprocessor import FilePreprocessor
from src.workflows.ingestion.strategies.base import IngestionStrategy


class HighMemoryStrategy(IngestionStrategy):
    """Phased ingestion strategy that keeps concurrency inside each phase."""

    def __init__(self, config: object, cache_manager: IngestionCacheManager | None = None) -> None:
        super().__init__(config, cache_manager)
        self.preprocess_workers = max(
            1,
            getattr(config, "INGESTION_PREPROCESS_WORKERS", getattr(config, "RAG_PARALLEL_WORKERS", 4)),
        )
        self.embedding_workers = max(
            1,
            getattr(config, "RAG_PARALLEL_WORKERS", getattr(config, "INGESTION_PREPROCESS_WORKERS", 4)),
        )

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
        failed = 0
        skipped = 0

        if not queue:
            phase_manager.record_preprocessed_files(preprocessed, skipped=0, failed=0)
            return preprocessed

        with ThreadPoolExecutor(max_workers=self.preprocess_workers) as executor:
            futures: set = set()
            future_to_path: dict = {}
            while queue or futures:
                while queue and len(futures) < self.preprocess_workers:
                    next_path = queue.popleft()
                    cached = self._reuse_preprocess_status(next_path, phase_manager)
                    if cached:
                        if cached.processed_path not in seen:
                            seen.add(cached.processed_path)
                            preprocessed.append(cached)
                        continue
                    if self._should_skip_failed(phase_manager, next_path):
                        skipped += 1
                        continue
                    future = executor.submit(self._preprocess_single, next_path, preprocessor)
                    futures.add(future)
                    future_to_path[future] = next_path

                if not futures:
                    continue

                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                futures.difference_update(done)

                for future in done:
                    original_path = future_to_path.pop(future, None)
                    try:
                        records = future.result()
                    except Exception as exc:  # pragma: no cover - best-effort logging
                        self.logger.warning("Preprocessing task failed: %s", exc)
                        if original_path:
                            phase_manager.set_preprocess_status(original_path, "failed", error=str(exc))
                        failed += 1
                        continue

                    if not records:
                        if original_path:
                            phase_manager.set_preprocess_status(
                                original_path,
                                "failed",
                                error="preprocessor_returned_empty",
                            )
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

        phase_manager.record_preprocessed_files(preprocessed, skipped=skipped, failed=failed)
        return preprocessed

    def embedding_phase(
        self,
        preprocessed_records: List[PreprocessedFileRecord],
        pipeline: IngestionPipeline,
        options: IngestionOptions,
        phase_manager: PhaseManager,
    ) -> dict:
        self._prepare_pipeline_workers(pipeline, self.embedding_workers)
        file_paths = [record.processed_path for record in preprocessed_records]
        result = self._run_ingestion(pipeline, file_paths, options, phase_manager)
        phase_manager.record_ingestion_summary(result)
        return result
