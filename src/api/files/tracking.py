"""SQLite-based tracking for file uploads and chunk relevance."""

import hashlib
import logging
from typing import Dict, List, Optional, Any

from src.workflows.query.temporal.store import TemporalStore

logger = logging.getLogger(__name__)


class FileTracker:
    """Tracks file uploads and chunk usage via SQLite control plane."""

    def __init__(
        self,
        store: Optional[TemporalStore] = None,
        promotion_threshold: int = 3,
        pareto_min_queries: int = 5,
        ttl_seconds: int = 86400,
    ):
        """Initialize file tracker.

        Args:
            store: TemporalStore instance (optional).
            promotion_threshold: Number of uploads before auto-promotion.
            pareto_min_queries: Minimum queries before Pareto analysis.
            ttl_seconds: TTL for temporal files and tenants.
        """
        self.store = store or TemporalStore()
        self.promotion_threshold = promotion_threshold
        self.pareto_min_queries = pareto_min_queries
        self.ttl_seconds = ttl_seconds

        logger.info(
            "FileTracker initialized: promotion_threshold=%s, pareto_min_queries=%s, ttl=%ss",
            promotion_threshold,
            pareto_min_queries,
            ttl_seconds,
        )

    @staticmethod
    def compute_file_hash(content: bytes) -> str:
        """Compute SHA256 hash of file content."""
        return hashlib.sha256(content).hexdigest()

    def track_file_upload(
        self,
        file_hash: str,
        thread_id: str,
        file_id: str,
        filename: str,
        chunk_ids: List[str],
    ) -> Dict[str, Any]:
        """Track a file upload and return promotion info."""
        upload_info = self.store.increment_file_upload(file_hash, thread_id, filename)
        self.store.upsert_temporal_file(
            thread_id=thread_id,
            file_id=file_id,
            file_hash=file_hash,
            filename=filename,
            chunk_ids=chunk_ids,
            ttl_seconds=self.ttl_seconds,
        )

        tenant_name = f"temp_{thread_id}"
        self.store.ensure_tenant(tenant_name, ttl_seconds=self.ttl_seconds)

        upload_count = int(upload_info["upload_count"])
        is_already_promoted = bool(int(upload_info.get("promoted", 0)))
        should_promote = upload_count >= self.promotion_threshold

        result = {
            "file_hash": file_hash,
            "upload_count": upload_count,
            "should_auto_promote": should_promote and not is_already_promoted,
            "is_promoted": is_already_promoted,
            "chunk_count": len(chunk_ids),
        }

        logger.info(
            "Tracked file upload: %s (hash=%s..., uploads=%s, auto_promote=%s)",
            filename,
            file_hash[:8],
            upload_count,
            result["should_auto_promote"],
        )

        return result

    def track_chunk_usage(
        self,
        thread_id: str,
        file_id: str,
        chunk_id: str,
        relevance_score: float,
        query: str,
    ) -> None:
        """Track chunk usage in a query."""
        self.store.increment_query_count(thread_id, file_id)
        new_score = self.store.increment_chunk_score(
            thread_id=thread_id,
            file_id=file_id,
            chunk_id=chunk_id,
            delta=relevance_score,
        )
        logger.debug(
            "Tracked chunk usage: file=%s, chunk=%s, score=%.3f, total=%.3f",
            file_id,
            chunk_id,
            relevance_score,
            new_score,
        )

    def get_file_info(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Get information about a file."""
        return self.store.get_file_upload_info(file_hash)

    def get_temporal_file_info(
        self, thread_id: str, file_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get information about a temporal file."""
        return self.store.get_temporal_file_info(thread_id, file_id)

    def list_temporal_files(self, thread_id: str) -> List[str]:
        """List all temporal file IDs for a thread."""
        return self.store.list_temporal_files(thread_id)

    def should_run_pareto_analysis(self, thread_id: str, file_id: str) -> bool:
        """Check if Pareto analysis should be run for a file."""
        info = self.get_temporal_file_info(thread_id, file_id)
        if not info:
            return False
        query_count = int(info.get("query_count", 0))
        return query_count >= self.pareto_min_queries

    def mark_pareto_promoted(self, file_hash: str, file_id: Optional[str] = None) -> None:
        """Mark a file as Pareto-promoted."""
        self.store.mark_promoted(file_hash, mode="pareto")
        logger.info("Marked file %s as Pareto-promoted", file_hash[:8])

    def mark_full_promoted(self, file_hash: str) -> None:
        """Mark a file as fully promoted to permanent KB."""
        self.store.mark_promoted(file_hash, mode="full")
        logger.info("Marked file %s as fully promoted", file_hash[:8])

    def get_stats(self) -> Dict[str, Any]:
        """Get overall tracking statistics."""
        return self.store.get_stats()


def create_file_tracker(
    store: Optional[TemporalStore] = None,
    promotion_threshold: int = 3,
    pareto_min_queries: int = 5,
    ttl_seconds: int = 86400,
) -> FileTracker:
    """Factory function to create FileTracker."""
    return FileTracker(
        store=store,
        promotion_threshold=promotion_threshold,
        pareto_min_queries=pareto_min_queries,
        ttl_seconds=ttl_seconds,
    )
