"""Redis-based tracking for file uploads and chunk relevance.

Tracks:
- File upload frequency (for auto-promotion)
- Chunk relevance scores (for Pareto analysis)
- Temporal file metadata
"""
import hashlib
import logging
import time
from typing import Dict, List, Optional, Any
import redis

logger = logging.getLogger(__name__)


class FileTracker:
    """Tracks file uploads and chunk usage in Redis."""

    def __init__(
        self,
        redis_client: redis.Redis,
        promotion_threshold: int = 3,
        pareto_min_queries: int = 5,
    ):
        """Initialize file tracker.

        Args:
            redis_client: Redis client instance
            promotion_threshold: Number of uploads before auto-promotion
            pareto_min_queries: Minimum queries before Pareto analysis
        """
        self.redis = redis_client
        self.promotion_threshold = promotion_threshold
        self.pareto_min_queries = pareto_min_queries

        logger.info(
            f"FileTracker initialized: promotion_threshold={promotion_threshold}, "
            f"pareto_min_queries={pareto_min_queries}"
        )

    @staticmethod
    def compute_file_hash(content: bytes) -> str:
        """Compute SHA256 hash of file content.

        Args:
            content: File content as bytes

        Returns:
            Hex digest of SHA256 hash
        """
        return hashlib.sha256(content).hexdigest()

    def track_file_upload(
        self,
        file_hash: str,
        thread_id: str,
        file_id: str,
        filename: str,
        chunk_ids: List[str],
    ) -> Dict[str, Any]:
        """Track a file upload.

        Args:
            file_hash: Hash of file content
            thread_id: Thread identifier
            file_id: Unique file identifier
            filename: Original filename
            chunk_ids: List of chunk IDs created from file

        Returns:
            Dictionary with upload info and promotion status
        """
        current_time = time.time()

        # 1. Increment global upload counter for this file
        upload_count_key = f"file_uploads:{file_hash}"
        upload_count = self.redis.hincrby(upload_count_key, "upload_count", 1)

        # 2. Track threads that uploaded this file
        self.redis.sadd(f"{upload_count_key}:threads", thread_id)

        # 3. Set timestamps
        if upload_count == 1:
            self.redis.hset(upload_count_key, "first_uploaded", current_time)
            self.redis.hset(upload_count_key, "filename", filename)

        self.redis.hset(upload_count_key, "last_uploaded", current_time)

        # 4. Store temporal file metadata
        temp_file_key = f"temp_file:{thread_id}:{file_id}"
        self.redis.hset(temp_file_key, "file_hash", file_hash)
        self.redis.hset(temp_file_key, "filename", filename)
        self.redis.hset(temp_file_key, "uploaded_at", current_time)
        self.redis.hset(temp_file_key, "query_count", 0)
        self.redis.hset(temp_file_key, "pareto_promoted", 0)
        self.redis.hset(temp_file_key, "full_promoted", 0)

        # Store chunk IDs as JSON
        import json
        self.redis.hset(temp_file_key, "chunk_ids", json.dumps(chunk_ids))

        # Set TTL (24 hours)
        self.redis.expire(temp_file_key, 86400)

        # 5. Track tenant creation time
        tenant_name = f"temp_{thread_id}"
        tenant_key = f"tenant_created:{tenant_name}"
        if not self.redis.exists(tenant_key):
            self.redis.setex(tenant_key, 86400, current_time)

        # 6. Add to thread's file list
        self.redis.sadd(f"temp_files:{thread_id}", file_id)
        self.redis.expire(f"temp_files:{thread_id}", 86400)

        # 7. Check if should auto-promote
        should_promote = upload_count >= self.promotion_threshold
        is_already_promoted = bool(int(self.redis.hget(upload_count_key, "promoted") or 0))

        result = {
            "file_hash": file_hash,
            "upload_count": upload_count,
            "should_auto_promote": should_promote and not is_already_promoted,
            "is_promoted": is_already_promoted,
            "chunk_count": len(chunk_ids),
        }

        logger.info(
            f"Tracked file upload: {filename} (hash={file_hash[:8]}..., "
            f"uploads={upload_count}, auto_promote={result['should_auto_promote']})"
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
        """Track chunk usage in a query.

        Args:
            thread_id: Thread identifier
            file_id: File identifier
            chunk_id: Chunk identifier
            relevance_score: Relevance score from retrieval
            query: User query
        """
        temp_file_key = f"temp_file:{thread_id}:{file_id}"

        # Increment query count
        self.redis.hincrby(temp_file_key, "query_count", 1)

        # Update chunk relevance score (cumulative)
        chunk_scores_key = f"{temp_file_key}:chunk_scores"
        current_score = float(self.redis.hget(chunk_scores_key, chunk_id) or 0.0)
        new_score = current_score + relevance_score
        self.redis.hset(chunk_scores_key, chunk_id, new_score)

        # Set TTL
        self.redis.expire(chunk_scores_key, 86400)

        logger.debug(
            f"Tracked chunk usage: file={file_id}, chunk={chunk_id}, "
            f"score={relevance_score:.3f}, total={new_score:.3f}"
        )

    def get_file_info(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Get information about a file.

        Args:
            file_hash: File hash

        Returns:
            Dictionary with file info or None if not found
        """
        key = f"file_uploads:{file_hash}"

        if not self.redis.exists(key):
            return None

        info = self.redis.hgetall(key)

        # Decode bytes to strings
        info = {k.decode(): v.decode() for k, v in info.items()}

        # Get threads
        threads = self.redis.smembers(f"{key}:threads")
        info["threads"] = [t.decode() for t in threads]

        return info

    def get_temporal_file_info(
        self, thread_id: str, file_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get information about a temporal file.

        Args:
            thread_id: Thread identifier
            file_id: File identifier

        Returns:
            Dictionary with temporal file info or None if not found
        """
        temp_file_key = f"temp_file:{thread_id}:{file_id}"

        if not self.redis.exists(temp_file_key):
            return None

        info = self.redis.hgetall(temp_file_key)
        info = {k.decode(): v.decode() for k, v in info.items()}

        # Get chunk scores
        chunk_scores_key = f"{temp_file_key}:chunk_scores"
        chunk_scores = self.redis.hgetall(chunk_scores_key)
        if chunk_scores:
            info["chunk_scores"] = {
                k.decode(): float(v.decode()) for k, v in chunk_scores.items()
            }
        else:
            info["chunk_scores"] = {}

        # Parse chunk IDs
        import json
        if "chunk_ids" in info:
            info["chunk_ids"] = json.loads(info["chunk_ids"])

        return info

    def list_temporal_files(self, thread_id: str) -> List[str]:
        """List all temporal file IDs for a thread.

        Args:
            thread_id: Thread identifier

        Returns:
            List of file IDs
        """
        file_ids = self.redis.smembers(f"temp_files:{thread_id}")
        return [fid.decode() for fid in file_ids]

    def should_run_pareto_analysis(self, thread_id: str, file_id: str) -> bool:
        """Check if Pareto analysis should be run for a file.

        Args:
            thread_id: Thread identifier
            file_id: File identifier

        Returns:
            True if Pareto analysis should be run
        """
        temp_file_key = f"temp_file:{thread_id}:{file_id}"

        # Get query count
        query_count = int(self.redis.hget(temp_file_key, "query_count") or 0)

        # Check if already promoted
        pareto_promoted = bool(int(self.redis.hget(temp_file_key, "pareto_promoted") or 0))
        full_promoted = bool(int(self.redis.hget(temp_file_key, "full_promoted") or 0))

        # Run if enough queries and not already promoted
        return (
            query_count >= self.pareto_min_queries
            and not pareto_promoted
            and not full_promoted
        )

    def mark_pareto_promoted(self, thread_id: str, file_id: str) -> None:
        """Mark a file as Pareto-promoted.

        Args:
            thread_id: Thread identifier
            file_id: File identifier
        """
        temp_file_key = f"temp_file:{thread_id}:{file_id}"
        self.redis.hset(temp_file_key, "pareto_promoted", 1)
        logger.info(f"Marked file {file_id} as Pareto-promoted")

    def mark_full_promoted(self, file_hash: str) -> None:
        """Mark a file as fully promoted to permanent KB.

        Args:
            file_hash: File hash
        """
        key = f"file_uploads:{file_hash}"
        self.redis.hset(key, "promoted", 1)
        self.redis.hset(key, "promoted_at", time.time())
        logger.info(f"Marked file {file_hash[:8]}... as fully promoted")

    def get_stats(self) -> Dict[str, Any]:
        """Get overall tracking statistics.

        Returns:
            Dictionary with statistics
        """
        # Count unique files
        file_keys = self.redis.keys("file_uploads:*")
        unique_files = len([k for k in file_keys if b":threads" not in k])

        # Count temporal files
        temp_file_keys = self.redis.keys("temp_file:*")
        temp_files = len([k for k in temp_file_keys if b":chunk_scores" not in k])

        # Count promoted files
        promoted_count = 0
        for key in file_keys:
            if b":threads" not in key:
                promoted = self.redis.hget(key, "promoted")
                if promoted and int(promoted) == 1:
                    promoted_count += 1

        return {
            "unique_files_tracked": unique_files,
            "temporal_files_active": temp_files,
            "fully_promoted_files": promoted_count,
        }


def create_file_tracker(
    redis_client: redis.Redis,
    promotion_threshold: int = 3,
    pareto_min_queries: int = 5,
) -> FileTracker:
    """Factory function to create FileTracker.

    Args:
        redis_client: Redis client instance
        promotion_threshold: Upload count for auto-promotion
        pareto_min_queries: Minimum queries for Pareto analysis

    Returns:
        FileTracker instance
    """
    return FileTracker(
        redis_client=redis_client,
        promotion_threshold=promotion_threshold,
        pareto_min_queries=pareto_min_queries,
    )
