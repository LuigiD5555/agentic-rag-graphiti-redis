"""Pareto analysis for temporal files.

Analyzes chunk usage patterns to identify the most relevant chunks (80/20 rule).
"""
import logging
from typing import List, Dict, Any, Optional, Tuple

from src.workflows.query.temporal.store import TemporalStore

logger = logging.getLogger(__name__)


class ParetoAnalyzer:
    """Analyzes chunk usage to identify top performers."""

    def __init__(
        self,
        store: Optional[TemporalStore] = None,
        top_percent: int = 20,
        min_queries: int = 5,
    ):
        """Initialize Pareto analyzer.

        Args:
            store: TemporalStore instance (optional)
            top_percent: Percentage of top chunks to promote (default: 20)
            min_queries: Minimum queries required for Pareto analysis (default: 5)
        """
        self.store = store or TemporalStore()
        self.top_percent = top_percent
        self.min_queries = min_queries

    def analyze_file(
        self,
        thread_id: str,
        file_id: str,
    ) -> Dict[str, Any]:
        """Analyze chunk usage for a file using Pareto principle."""
        file_info = self.store.get_temporal_file_info(thread_id, file_id)

        if not file_info:
            logger.warning("File %s not found in thread %s", file_id, thread_id)
            return {
                "eligible": False,
                "error": "File not found",
            }

        query_count = int(file_info.get("query_count", 0))
        if query_count < self.min_queries:
            logger.debug(
                "File %s has %s queries (min: %s), not eligible for Pareto analysis",
                file_id,
                query_count,
                self.min_queries,
            )
            return {
                "eligible": False,
                "query_count": query_count,
                "min_queries_required": self.min_queries,
            }

        chunk_scores = file_info.get("chunk_scores", {})
        if not chunk_scores:
            logger.warning("No chunk scores found for file %s", file_id)
            return {
                "eligible": False,
                "error": "No chunk scores available",
            }

        sorted_chunks = sorted(
            chunk_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        total_chunks = len(sorted_chunks)
        top_n = max(1, int(total_chunks * (self.top_percent / 100)))

        top_chunks = []
        for rank, (chunk_id, score) in enumerate(sorted_chunks[:top_n], start=1):
            top_chunks.append({
                "chunk_id": chunk_id,
                "score": score,
                "rank": rank,
            })

        top_chunk_ids = [c["chunk_id"] for c in top_chunks]

        top_chunk_score_sum = sum(c["score"] for c in top_chunks)
        total_score_sum = sum(score for _, score in sorted_chunks)
        score_percentage = (top_chunk_score_sum / total_score_sum * 100) if total_score_sum > 0 else 0

        logger.info(
            "Pareto analysis for %s: %d/%d chunks (%d%%) account for %.1f%% of relevance score",
            file_id,
            top_n,
            total_chunks,
            self.top_percent,
            score_percentage,
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
        """Check if a file should be promoted using Pareto analysis."""
        analysis = self.analyze_file(thread_id, file_id)

        if not analysis.get("eligible"):
            return False, analysis.get("error", "Not eligible for Pareto analysis")

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
        """Get all files in a thread that are eligible for Pareto promotion."""
        file_ids = self.store.list_temporal_files(thread_id)
        if not file_ids:
            return []

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
    store: Optional[TemporalStore] = None,
    top_percent: int = 20,
    min_queries: int = 5,
) -> ParetoAnalyzer:
    """Factory function to create ParetoAnalyzer."""
    return ParetoAnalyzer(
        store=store,
        top_percent=top_percent,
        min_queries=min_queries,
    )
