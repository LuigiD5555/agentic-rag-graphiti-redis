from __future__ import annotations

import os
from typing import Any, Dict, Optional

from src import logger
from src.storage.vector.ingestion.loaders import CODE_LOADER_SPECS, TEXT_LOADER_SPECS, PlainTextLoader
from src.storage.vector.utils import gather_file_metadata

from .code_processor import process_code_document
from .loader_helpers import should_skip_path
from .state_helpers import register_observed_file
from .text_processor import process_text_document


def process_candidate_file(
    pipeline: Any,
    full_path: str,
    *,
    file_index: Optional[int] = None,
    total_files: Optional[int] = None,
    directory_path: Optional[str] = None,
) -> None:
    if should_skip_path(full_path):
        return

    directory = directory_path or os.path.dirname(full_path)
    file_info = gather_file_metadata(full_path)
    register_observed_file(pipeline, full_path)

    if not pipeline.catalog.should_process_file(file_info):
        logger.info("Skipping %s; no changes detected.", full_path)
        pipeline._current_file_info = None
        return

    pipeline.progress.register_file(full_path, file_info.get("file_size_bytes"))

    pipeline._file_context = {
        "file_index": file_index,
        "total_files": total_files,
        "directory_path": directory,
    }
    pipeline._current_file_info = file_info
    logger.info("Processing candidate file: %s", full_path)

    for extensions, loader_cls in TEXT_LOADER_SPECS:
        if full_path.endswith(extensions):
            process_text_document(pipeline, loader_cls(full_path))
            return

    for extensions, loader_cls in CODE_LOADER_SPECS:
        if full_path.endswith(extensions):
            process_code_document(pipeline, loader_cls(full_path))
            return

    process_text_document(pipeline, PlainTextLoader(full_path))


__all__ = ["process_candidate_file"]
