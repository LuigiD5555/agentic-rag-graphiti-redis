import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from src.backends.storage.cache.ingestion import IngestionCacheManager
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


@dataclass
class PreprocessedFileRecord:
    """Metadata about a file that was prepared during the preprocessing phase."""

    original_path: str
    processed_path: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-friendly dict."""
        return {
            "original_path": self.original_path,
            "processed_path": self.processed_path,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "PreprocessedFileRecord":
        """Deserialize from JSON-friendly dict."""
        return cls(
            original_path=raw["original_path"],
            processed_path=raw["processed_path"],
            metadata=dict(raw.get("metadata") or {}),
        )

    @property
    def is_directory(self) -> bool:
        """Whether the processed path points to a directory."""
        return self.processed_path.endswith(os.path.sep) or Path(self.processed_path).is_dir()


class PhaseManager:
    """Track discovery/preprocessing/ingestion state for a single ingestion run."""

    DISCOVERY_STAGE = "discovery"
    PREPROCESS_STAGE = "preprocess"
    INGEST_STAGE = "ingest"

    def __init__(
        self,
        cache_manager: Optional[IngestionCacheManager] = None,
        run_id: Optional[str] = None,
        ttl: int = 24 * 60 * 60,
    ) -> None:
        """Initialize a manager for a single ingestion run."""
        self.run_id = run_id or str(uuid4())
        self.ttl = ttl
        self.cache_manager = cache_manager
        self._memory_store: Dict[str, str] = {}

    def _key(self, phase: str) -> str:
        return f"ingestion:phase:{self.run_id}:{phase}"

    def _preprocess_status_key(self) -> str:
        return f"ingestion:phase:{self.run_id}:preprocess:status"

    def _persist(self, phase: str, value: Any) -> None:
        payload = json.dumps(value)
        self._memory_store[self._key(phase)] = payload

    def _load(self, phase: str) -> Optional[Dict[str, Any]]:
        raw = self._memory_store.get(self._key(phase))

        if not raw:
            return None

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.debug("Malformed phase payload for %s", phase)
            return None

    def record_discovered_files(self, file_paths: Iterable[str], visited_dirs: int) -> None:
        """Store discovery output for later phases or resumption."""
        payload = {
            "timestamp": time.time(),
            "visited_dirs": visited_dirs,
            "files": list(file_paths),
        }
        self._persist(self.DISCOVERY_STAGE, payload)

    def get_discovered_files(self) -> Optional[Dict[str, Any]]:
        """Retrieve the last discovery payload for this run."""
        return self._load(self.DISCOVERY_STAGE)

    def record_preprocessed_files(
        self,
        records: Iterable[PreprocessedFileRecord],
        skipped: int = 0,
        failed: int = 0,
    ) -> None:
        """Store preprocessing results."""
        payload = {
            "timestamp": time.time(),
            "processed": [record.to_dict() for record in records],
            "skipped": skipped,
            "failed": failed,
        }
        self._persist(self.PREPROCESS_STAGE, payload)

    def get_preprocessed_files(self) -> List[PreprocessedFileRecord]:
        """Return preprocessed records for this run (if any)."""
        payload = self._load(self.PREPROCESS_STAGE)
        if not payload:
            return []
        return [PreprocessedFileRecord.from_dict(item) for item in payload.get("processed", [])]

    def set_preprocess_status(
        self,
        original_path: str,
        status: str,
        processed_path: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        payload = {
            "status": status,
            "processed_path": processed_path,
            "error": error,
            "timestamp": time.time(),
        }
        raw = self._memory_store.get(self._preprocess_status_key(), "{}")
        try:
            current = json.loads(raw)
        except json.JSONDecodeError:
            current = {}
        current[original_path] = payload
        self._memory_store[self._preprocess_status_key()] = json.dumps(current)

    def get_preprocess_status(self, original_path: str) -> Optional[Dict[str, Any]]:
        raw = self._memory_store.get(self._preprocess_status_key())
        if not raw:
            return None
        try:
            current = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return current.get(original_path)

    def record_ingestion_summary(self, summary: Dict[str, Any]) -> None:
        """Persist ingestion summary for debugging or resume."""
        payload = {
            "timestamp": time.time(),
            "summary": summary,
        }
        self._persist(self.INGEST_STAGE, payload)

    def get_summary(self) -> Optional[Dict[str, Any]]:
        """Retrieve stored summary for this run."""
        return self._load(self.INGEST_STAGE)
