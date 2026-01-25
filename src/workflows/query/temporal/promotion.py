"""File promotion system for temporal RAG.

Handles promotion of temporal files to permanent KB (full or Pareto-based).
"""
import logging
from typing import List, Dict, Any, Optional
from enum import Enum

import weaviate
from weaviate.classes.query import Filter

from src.workflows.query.temporal.store import TemporalStore
from src.workflows.query.temporal.pareto import ParetoAnalyzer

logger = logging.getLogger(__name__)


class PromotionMode(str, Enum):
    """Promotion modes."""
    FULL = "full"
    PARETO = "pareto"


class FilePromoter:
    """Promotes temporal files to permanent KB."""

    def __init__(
        self,
        weaviate_client: weaviate.WeaviateClient,
        store: Optional[TemporalStore],
        collection_name: str,
        default_tenant: Optional[str] = None,
        pareto_analyzer: Optional[ParetoAnalyzer] = None,
    ):
        """Initialize file promoter."""
        self.weaviate_client = weaviate_client
        self.store = store or TemporalStore()
        self.collection_name = collection_name
        self.default_tenant = default_tenant
        self.pareto_analyzer = pareto_analyzer

        logger.info(
            "FilePromoter initialized: collection=%s, default_tenant=%s",
            collection_name,
            default_tenant,
        )

    def promote_file(
        self,
        thread_id: str,
        file_id: str,
        mode: PromotionMode = PromotionMode.FULL,
    ) -> Dict[str, Any]:
        """Promote a file from temporal to permanent storage."""
        try:
            file_info = self.store.get_temporal_file_info(thread_id, file_id)
            if not file_info:
                return {
                    "success": False,
                    "error": "File not found in temporal store",
                }

            all_chunk_ids = file_info.get("chunk_ids", [])
            if not all_chunk_ids:
                return {
                    "success": False,
                    "error": "No chunks found for file",
                }

            if mode == PromotionMode.PARETO:
                if not self.pareto_analyzer:
                    return {
                        "success": False,
                        "error": "Pareto analyzer not available",
                    }

                analysis = self.pareto_analyzer.analyze_file(thread_id, file_id)
                if not analysis.get("eligible"):
                    return {
                        "success": False,
                        "error": f"File not eligible for Pareto promotion: {analysis.get('error')}",
                        "analysis": analysis,
                    }

                chunks_to_promote = analysis["top_chunk_ids"]
            else:
                chunks_to_promote = all_chunk_ids

            temp_tenant = f"temp_{thread_id}"
            promoted_count = self._copy_chunks(
                source_tenant=temp_tenant,
                target_tenant=self.default_tenant,
                chunk_ids=chunks_to_promote,
            )

            file_hash = file_info.get("file_hash")
            if file_hash:
                self.store.mark_promoted(file_hash, mode=mode.value)

            logger.info(
                "Promoted file %s: %d/%d chunks (mode: %s)",
                file_id,
                promoted_count,
                len(all_chunk_ids),
                mode,
            )

            return {
                "success": True,
                "mode": mode.value,
                "chunks_promoted": promoted_count,
                "total_chunks": len(all_chunk_ids),
                "message": f"Successfully promoted {promoted_count} chunks using {mode.value} mode",
            }

        except Exception as e:
            logger.error("Promotion failed for %s: %s", file_id, e, exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }

    def _copy_chunks(
        self,
        source_tenant: str,
        target_tenant: Optional[str],
        chunk_ids: List[str],
    ) -> int:
        """Copy chunks from source tenant to target tenant."""
        if not chunk_ids:
            return 0

        try:
            collection = self.weaviate_client.collections.get(self.collection_name)
            source_collection = collection.with_tenant(source_tenant)
            target_collection = collection.with_tenant(target_tenant) if target_tenant else collection

            copied_count = 0
            for chunk_id in chunk_ids:
                try:
                    response = source_collection.query.fetch_objects(
                        limit=1,
                        filters=Filter.by_id().equal(chunk_id),
                    )
                    objects = getattr(response, "objects", []) or []
                    if not objects:
                        logger.warning("Chunk %s not found in source tenant", chunk_id)
                        continue

                    obj = objects[0]
                    properties = obj.properties
                    target_collection.data.insert(properties=properties)
                    copied_count += 1
                except Exception as e:
                    logger.error("Failed to copy chunk %s: %s", chunk_id, e)
                    continue

            return copied_count

        except Exception as e:
            logger.error("Failed to copy chunks: %s", e)
            return 0


def create_file_promoter(
    weaviate_client: weaviate.WeaviateClient,
    store: Optional[TemporalStore],
    collection_name: str,
    default_tenant: Optional[str] = None,
    pareto_analyzer: Optional[ParetoAnalyzer] = None,
) -> FilePromoter:
    """Factory function to create FilePromoter."""
    return FilePromoter(
        weaviate_client=weaviate_client,
        store=store,
        collection_name=collection_name,
        default_tenant=default_tenant,
        pareto_analyzer=pareto_analyzer,
    )
