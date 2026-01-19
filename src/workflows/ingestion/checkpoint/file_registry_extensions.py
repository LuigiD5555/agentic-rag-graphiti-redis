"""Extensions to FileMetadata for checkpoint support.

This module provides helper functions for:
- Tracking which run_id last saw each file (for deletion detection)
- Associating files with scan and ingestion runs
- Managing chunk relationships
"""

from typing import TYPE_CHECKING, Optional, List, Set
import time

if TYPE_CHECKING:
    import redis

from src.workflows.query.audit import get_logger
from src.backends.storage.cache.ingestion.models import FileMetadata
from src.backends.storage.cache.ingestion.redis_operations import RedisOperations

log = get_logger(__name__)


class FileRegistryExtensions(RedisOperations):
    """Extended operations for file tracking with run_id support."""

    # Additional key prefixes
    RUN_FILES_PREFIX = "ingestion:run:{run_id}:files"  # SET of file paths seen in run
    FILE_RUNS_PREFIX = "ingestion:file_runs:"  # ZSET of run_id:timestamp for each file

    def mark_file_seen_in_run(self, file_path: str, run_id: str) -> None:
        """Mark that a file was seen in a specific run.

        This enables deletion detection: files not seen in recent runs
        can be identified as deleted from source.

        Args:
            file_path: File path
            run_id: Run identifier
        """
        # Add file to run's file set
        run_files_key = self.RUN_FILES_PREFIX.format(run_id=run_id)
        self.redis.sadd(run_files_key, file_path)
        self.redis.expire(run_files_key, self.ttl)

        # Track run history for this file (sorted set by timestamp)
        file_runs_key = f"{self.FILE_RUNS_PREFIX}{file_path}"
        self.redis.zadd(file_runs_key, {run_id: time.time()})
        self.redis.expire(file_runs_key, self.ttl)

    def get_files_in_run(self, run_id: str) -> Set[str]:
        """Get all files seen in a specific run.

        Args:
            run_id: Run identifier

        Returns:
            Set of file paths
        """
        run_files_key = self.RUN_FILES_PREFIX.format(run_id=run_id)
        return set(self.redis.smembers(run_files_key))

    def get_file_run_history(self, file_path: str, limit: int = 10) -> List[tuple[str, float]]:
        """Get recent runs that saw this file.

        Args:
            file_path: File path
            limit: Maximum number of runs to return

        Returns:
            List of (run_id, timestamp) tuples, most recent first
        """
        file_runs_key = f"{self.FILE_RUNS_PREFIX}{file_path}"
        # Get runs sorted by timestamp (descending)
        runs = self.redis.zrevrange(file_runs_key, 0, limit - 1, withscores=True)
        return [(run_id, score) for run_id, score in runs]

    def update_file_with_run_info(
        self,
        file_path: str,
        scan_run_id: Optional[str] = None,
        ingestion_run_id: Optional[str] = None,
        chunk_ids: Optional[List[str]] = None
    ) -> bool:
        """Update file metadata with run and chunk information.

        Args:
            file_path: File path
            scan_run_id: Optional scan run identifier
            ingestion_run_id: Optional ingestion run identifier
            chunk_ids: Optional list of chunk identifiers

        Returns:
            True if updated successfully
        """
        metadata = self.get_file_metadata(file_path)
        if not metadata:
            log.warning("Cannot update file %s: metadata not found", file_path)
            return False

        # Update fields
        if scan_run_id:
            metadata.scan_run_id = scan_run_id

        if ingestion_run_id:
            metadata.ingestion_run_id = ingestion_run_id

        if chunk_ids is not None:
            metadata.chunk_ids = ",".join(chunk_ids)

        # Save updated metadata
        return self.set_file_metadata(metadata)

    def get_file_chunk_ids(self, file_path: str) -> List[str]:
        """Get chunk IDs associated with a file.

        Args:
            file_path: File path

        Returns:
            List of chunk IDs
        """
        metadata = self.get_file_metadata(file_path)
        if not metadata or not metadata.chunk_ids:
            return []

        return metadata.chunk_ids.split(",")

    def find_deleted_files(
        self,
        previous_run_id: str,
        current_run_id: str
    ) -> Set[str]:
        """Find files that existed in previous run but not in current run.

        This identifies deleted files that should be removed from vector store.

        Args:
            previous_run_id: Previous scan run identifier
            current_run_id: Current scan run identifier

        Returns:
            Set of file paths that were deleted
        """
        previous_files = self.get_files_in_run(previous_run_id)
        current_files = self.get_files_in_run(current_run_id)

        deleted = previous_files - current_files

        if deleted:
            log.info(
                "Detected %d deleted file(s) (not in %s but in %s)",
                len(deleted), current_run_id, previous_run_id
            )

        return deleted

    def mark_files_for_deletion(self, file_paths: Set[str]) -> int:
        """Mark files as deleted in cache.

        Args:
            file_paths: Set of file paths to mark as deleted

        Returns:
            Number of files marked
        """
        count = 0

        for file_path in file_paths:
            metadata = self.get_file_metadata(file_path)
            if metadata:
                metadata.status = "deleted"
                metadata.last_processed = time.time()
                if self.set_file_metadata(metadata):
                    count += 1

        log.info("Marked %d file(s) as deleted in cache", count)
        return count

    def get_files_by_scan_run(self, scan_run_id: str) -> List[str]:
        """Get all files discovered by a specific scan run.

        Args:
            scan_run_id: Scan run identifier

        Returns:
            List of file paths
        """
        return list(self.get_files_in_run(scan_run_id))

    def get_files_by_ingestion_run(self, ingestion_run_id: str) -> List[FileMetadata]:
        """Get all files processed by a specific ingestion run.

        This requires scanning all file keys (expensive).

        Args:
            ingestion_run_id: Ingestion run identifier

        Returns:
            List of FileMetadata objects
        """
        # This is expensive - ideally maintain a separate index
        # For now, get from run's file set
        file_paths = self.get_files_in_run(ingestion_run_id)

        result = []
        for file_path in file_paths:
            metadata = self.get_file_metadata(file_path)
            if metadata and metadata.ingestion_run_id == ingestion_run_id:
                result.append(metadata)

        return result


__all__ = ["FileRegistryExtensions"]
