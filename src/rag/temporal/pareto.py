"""Pareto analysis for temporal files.

Analyzes chunk usage patterns to identify the most relevant chunks (80/20 rule).
"""
import logging
from typing import List, Dict, Any, Optional, Tuple

import redis

logger = logging.getLogger(__name__)


class ParetoAnalyzer:
    """Analyzes chunk usage to identify top performers."""

    def __init__(
        self,
        redis_client: redis.Redis,
        top_percent: int = 20,
        min_queries: int = 5,
    ):
        """Initialize Pareto analyzer.

        Args:
            redis_client: Redis client instance
            top_percent: Percentage of top chunks to promote (default: 20)
            min_queries: Minimum queries required for Pareto analysis (default: 5)
        """
        self.redis = redis_client
        self.top_percent = top_percent
        self.min_queries = min_queries

    def analyze_file(
        self,
        thread_id: str,
        file_id: str,
    ) -> Dict[str, Any]:
        """Analyze chunk usage for a file using Pareto principle.

        Args:
            thread_id: Thread identifier
            file_id: File identifier

        Returns:
            Dictionary with analysis results:
            - eligible: bool (whether file has enough queries)
            - total_chunks: int
            - query_count: int
            - top_chunks: List[Dict] (chunks in top 20% by relevance)
            - top_chunk_ids: List[str]
            - promotion_eligible: bool
        """
        # Get file info
        file_key = f"temp_file:{thread_id}:{file_id}"
        file_info = self.redis.hgetall(file_key)

        if not file_info:
            logger.warning(f"File {file_id} not found in thread {thread_id}")
            return {
                "eligible": False,
                "error": "File not found",
            }

        # Decode Redis bytes
        file_info = {k.decode(): v.decode() for k, v in file_info.items()}

        # Check query count
        query_count = int(file_info.get("query_count", 0))
        if query_count < self.min_queries:
            logger.debug(
                f"File {file_id} has {query_count} queries (min: {self.min_queries}), "
                "not eligible for Pareto analysis"
            )
            return {
                "eligible": False,
                "query_count": query_count,
                "min_queries_required": self.min_queries,
            }

        # Get chunk scores
        chunk_scores_key = f"{file_key}:chunk_scores"
        chunk_scores_raw = self.redis.hgetall(chunk_scores_key)

        if not chunk_scores_raw:
            logger.warning(f"No chunk scores found for file {file_id}")
            return {
                "eligible": False,
                "error": "No chunk scores available",
            }

        # Parse chunk scores
        chunk_scores = {
            k.decode(): float(v.decode())
            for k, v in chunk_scores_raw.items()
        }

        # Sort chunks by score (descending)
        sorted_chunks = sorted(
            chunk_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        total_chunks = len(sorted_chunks)

        # Calculate top N% chunks
        top_n = max(1, int(total_chunks * (self.top_percent / 100)))

        top_chunks = []
        for rank, (chunk_id, score) in enumerate(sorted_chunks[:top_n], start=1):
            top_chunks.append({
                "chunk_id": chunk_id,
                "score": score,
                "rank": rank,
            })

        top_chunk_ids = [c["chunk_id"] for c in top_chunks]

        # Calculate metrics
        top_chunk_score_sum = sum(c["score"] for c in top_chunks)
        total_score_sum = sum(score for _, score in sorted_chunks)
        score_percentage = (top_chunk_score_sum / total_score_sum * 100) if total_score_sum > 0 else 0

        logger.info(
            f"Pareto analysis for {file_id}: {top_n}/{total_chunks} chunks "
            f"({self.top_percent}%) account for {score_percentage:.1f}% of relevance score"
        )

        return {
            "eligible": True,
            "query_count": query_count,
            "total_chunks": total_chunks,
            "top_chunks": top_chunks,
            "top_chunk_ids": top_chunk_ids,
            "top_chunk_count": len(top_chunk_ids),
            "score_percentage": score_percentage,
            "promotion_eligible": True,
        }

    def should_promote_file(
        self,
        thread_id: str,
        file_id: str,
    ) -> Tuple[bool, str]:
        """Check if a file should be promoted using Pareto analysis.

        Args:
            thread_id: Thread identifier
            file_id: File identifier

        Returns:
            Tuple of (should_promote: bool, reason: str)
        """
        analysis = self.analyze_file(thread_id, file_id)

        if not analysis.get("eligible"):
            return False, analysis.get("error", "Not eligible for Pareto analysis")

        # File is eligible for Pareto promotion
        top_chunk_count = analysis["top_chunk_count"]
        total_chunks = analysis["total_chunks"]
        score_percentage = analysis["score_percentage"]

        return True, (
            f"Pareto promotion eligible: {top_chunk_count}/{total_chunks} chunks "
            f"({self.top_percent}%) account for {score_percentage:.1f}% of relevance"
        )

    def get_all_promotable_files(
        self,
        thread_id: str,
    ) -> List[Dict[str, Any]]:
        """Get all files in a thread that are eligible for Pareto promotion.

        Args:
            thread_id: Thread identifier

        Returns:
            List of dictionaries with file_id and analysis results
        """
        # Get all files in thread
        temp_files_key = f"temp_files:{thread_id}"
        file_ids_raw = self.redis.smembers(temp_files_key)

        if not file_ids_raw:
            return []

        file_ids = [f.decode() for f in file_ids_raw]

        promotable_files = []
        for file_id in file_ids:
            should_promote, reason = self.should_promote_file(thread_id, file_id)

            if should_promote:
                analysis = self.analyze_file(thread_id, file_id)
                promotable_files.append({
                    "file_id": file_id,
                    "reason": reason,
                    "analysis": analysis,
                })

        return promotable_files


def create_pareto_analyzer(
    redis_client: redis.Redis,
    top_percent: int = 20,
    min_queries: int = 5,
) -> ParetoAnalyzer:
    """Factory function to create ParetoAnalyzer.

    Args:
        redis_client: Redis client
        top_percent: Percentage of top chunks to promote
        min_queries: Minimum queries required

    Returns:
        ParetoAnalyzer instance
    """
    return ParetoAnalyzer(
        redis_client=redis_client,
        top_percent=top_percent,
        min_queries=min_queries,
    )
