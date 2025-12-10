"""Persistent catalog for tracking ingested files and directories."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestionCatalog:
    """Tracks ingestion metadata per directory and file to detect changes."""

    def __init__(self, storage_path: str | os.PathLike[str]):
        self._path = Path(storage_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._state: Dict[str, Any] = self._load()
        self._dirty = False

    def _load(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {"directories": {}}
        try:
            return json.loads(self._path.read_text())
        except json.JSONDecodeError:
            return {"directories": {}}

    def save(self) -> None:
        if not self._dirty:
            return
        temp_path = self._path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(self._state, indent=2, sort_keys=True))
        temp_path.replace(self._path)
        self._dirty = False

    def record_directory(self, directory_path: str, file_paths: Iterable[str]) -> None:
        """Record the latest view of a directory."""
        directory = os.path.abspath(directory_path)
        paths = sorted(os.path.abspath(p) for p in file_paths)
        entry = self._state["directories"].setdefault(directory, {"files": {}})
        entry["expected_files"] = len(paths)
        entry["listed_files"] = paths
        entry["last_observed_at"] = _utcnow()
        self._dirty = True

    def should_process_file(self, file_info: Dict[str, Any]) -> bool:
        """Return True if the file appears new or modified."""
        directory = os.path.abspath(str(file_info.get("parent_directory") or ""))
        if not directory:
            return True
        entry = self._state["directories"].get(directory)
        if not entry:
            return True
        files = entry.get("files") or {}
        stored = files.get(file_info.get("file_path"))
        if not stored:
            return True
        size = file_info.get("file_size_bytes")
        modified = file_info.get("file_modified_at")
        if size is not None and stored.get("file_size_bytes") != size:
            return True
        if modified and stored.get("file_modified_at") != modified:
            return True
        return False

    def record_file_ingestion(
        self,
        file_info: Dict[str, Any],
        *,
        chunk_total: int,
        directory_total: Optional[int],
    ) -> None:
        directory = os.path.abspath(str(file_info.get("parent_directory") or ""))
        if not directory:
            return
        entry = self._state["directories"].setdefault(directory, {"files": {}})
        files = entry.setdefault("files", {})
        file_path = file_info.get("file_path")
        files[file_path] = {
            "file_size_bytes": file_info.get("file_size_bytes"),
            "file_modified_at": file_info.get("file_modified_at"),
            "file_id": file_info.get("file_id"),
            "chunk_total": chunk_total,
            "directory_total_files": directory_total,
            "updated_at": _utcnow(),
        }
        entry["total_files"] = max(directory_total or 0, entry.get("total_files") or 0)
        entry["last_completed_file"] = file_path
        entry["last_completed_at"] = _utcnow()
        self._dirty = True

    def list_missing_files(
        self,
        observed_paths: Iterable[str],
        observed_directories: Iterable[str],
    ) -> List[Dict[str, Any]]:
        """Return catalog entries for files that disappeared from disk."""
        observed = {os.path.abspath(p) for p in observed_paths}
        observed_dirs = {os.path.abspath(d) for d in observed_directories}
        missing: List[Dict[str, Any]] = []
        for directory, entry in list(self._state.get("directories", {}).items()):
            if observed_dirs and directory not in observed_dirs:
                continue
            files = entry.get("files") or {}
            raw_listed = entry.get("listed_files")
            listed_available = raw_listed is not None
            listed = {os.path.abspath(p) for p in (raw_listed or [])}
            for file_path, meta in list(files.items()):
                abs_path = os.path.abspath(file_path)
                if abs_path in observed:
                    continue
                if listed_available and abs_path in listed:
                    continue
                if os.path.exists(abs_path):
                    continue
                missing.append(
                    {
                        "directory": directory,
                        "file_path": file_path,
                        "file_id": meta.get("file_id"),
                    }
                )
        return missing

    def mark_archived(self, file_path: str) -> None:
        """Remove a file entry after it has been archived."""
        abs_path = os.path.abspath(file_path)
        for directory, entry in list(self._state.get("directories", {}).items()):
            files = entry.get("files") or {}
            if abs_path in files:
                files.pop(abs_path, None)
                entry["total_files"] = max(0, (entry.get("total_files") or 0) - 1)
                self._dirty = True
                if not files:
                    self._state["directories"].pop(directory, None)
                return
