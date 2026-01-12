"""File promotion system for temporal RAG.

Handles promotion of temporal files to permanent KB (full or Pareto-based).
"""
import logging
from typing import List, Dict, Any, Optional
from enum import Enum

import redis
import weaviate
from weaviate.classes.query import Filter

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
        redis_client: redis.Redis,
        collection_name: str,
        default_tenant: Optional[str] = None,
        pareto_analyzer: Optional[ParetoAnalyzer] = None,
    ):
        """Initialize file promoter.

        Args:
            weaviate_client: Weaviate client instance
            redis_client: Redis client instance
            collection_name: Weaviate collection name
            default_tenant: Default (permanent) tenant name
            pareto_analyzer: ParetoAnalyzer instance (optional)
        """
        self.weaviate_client = weaviate_client
        self.redis = redis_client
        self.collection_name = collection_name
        self.default_tenant = default_tenant
        self.pareto_analyzer = pareto_analyzer

        logger.info(
            f"FilePromoter initialized: collection={collection_name}, "
            f"default_tenant={default_tenant}"
        )

    def promote_file(
        self,
        thread_id: str,
        file_id: str,
        mode: PromotionMode = PromotionMode.FULL,
    ) -> Dict[str, Any]:
        """Promote a file from temporal to permanent storage.

        Args:
            thread_id: Thread identifier
            file_id: File identifier
            mode: Promotion mode (full or pareto)

        Returns:
            Dictionary with promotion results:
            - success: bool
            - mode: str
            - chunks_promoted: int
            - total_chunks: int
            - message: str
        """
        try:
            # Get file info from Redis
            file_key = f"temp_file:{thread_id}:{file_id}"
            file_info = self.redis.hgetall(file_key)

            if not file_info:
                return {
                    "success": False,
                    "error": "File not found in Redis",
                }

            # Decode Redis bytes
            file_info = {k.decode(): v.decode() for k, v in file_info.items()}

            # Get chunk IDs
            chunk_ids_str = file_info.get("chunk_ids", "")
            all_chunk_ids = chunk_ids_str.split(",") if chunk_ids_str else []

            if not all_chunk_ids:
                return {
                    "success": False,
                    "error": "No chunks found for file",
                }

            # Determine which chunks to promote
            if mode == PromotionMode.PARETO:
                # Use Pareto analysis to select top chunks
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
                # Full promotion - all chunks
                chunks_to_promote = all_chunk_ids

            # Copy chunks from temporal tenant to default tenant
            temp_tenant = f"temp_{thread_id}"
            promoted_count = self._copy_chunks(
                source_tenant=temp_tenant,
                target_tenant=self.default_tenant,
                chunk_ids=chunks_to_promote,
            )

            # Update Redis tracking
            file_hash = file_info.get("file_hash")
            if file_hash:
                if mode == PromotionMode.PARETO:
                    self.redis.hset(f"file_uploads:{file_hash}", "pareto_promoted", "1")
                else:
                    self.redis.hset(f"file_uploads:{file_hash}", "promoted", "1")

            logger.info(
                f"Promoted file {file_id}: {promoted_count}/{len(all_chunk_ids)} chunks "
                f"(mode: {mode})"
            )

            return {
                "success": True,
                "mode": mode.value,
                "chunks_promoted": promoted_count,
                "total_chunks": len(all_chunk_ids),
                "message": f"Successfully promoted {promoted_count} chunks using {mode.value} mode",
            }

        except Exception as e:
            logger.error(f"Promotion failed for {file_id}: {e}", exc_info=True)
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
        """Copy chunks from source tenant to target tenant.

        Args:
            source_tenant: Source tenant name
            target_tenant: Target tenant name (None for default)
            chunk_ids: List of chunk UUIDs to copy

        Returns:
            Number of chunks successfully copied
        """
        if not chunk_ids:
            return 0

        try:
            collection = self.weaviate_client.collections.get(self.collection_name)

            # Get source collection with tenant
            source_collection = collection.with_tenant(source_tenant)

            # Get target collection
            if target_tenant:
                target_collection = collection.with_tenant(target_tenant)
            else:
                target_collection = collection

            copied_count = 0

            for chunk_id in chunk_ids:
                try:
                    # Fetch chunk from source tenant
                    # Note: This is a simplified version
                    # In production, you'd use batch operations for efficiency
                    response = source_collection.query.fetch_objects(
                        limit=1,
                        filters=Filter.by_id().equal(chunk_id),
                    )

                    objects = getattr(response, "objects", []) or []
                    if not objects:
                        logger.warning(f"Chunk {chunk_id} not found in source tenant")
                        continue

                    # Get chunk data
                    obj = objects[0]
                    properties = obj.properties

                    # Insert into target tenant
                    # Note: In production, you'd preserve the vector as well
                    target_collection.data.insert(properties=properties)

                    copied_count += 1

                except Exception as e:
                    logger.error(f"Failed to copy chunk {chunk_id}: {e}")
                    continue

            return copied_count

        except Exception as e:
            logger.error(f"Failed to copy chunks: {e}", exc_info=True)
            return 0

    def auto_promote_on_threshold(
        self,
        file_hash: str,
        thread_id: str,
        file_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Auto-promote file if upload count threshold is met.

        Args:
            file_hash: File hash
            thread_id: Thread identifier
            file_id: File identifier

        Returns:
            Promotion result if promoted, None otherwise
        """
        # This is called by the upload endpoint when threshold is reached
        # Perform full promotion
        return self.promote_file(
            thread_id=thread_id,
            file_id=file_id,
            mode=PromotionMode.FULL,
        )


def create_file_promoter(
    weaviate_client: weaviate.WeaviateClient,
    redis_client: redis.Redis,
    collection_name: str,
    default_tenant: Optional[str] = None,
    pareto_analyzer: Optional[ParetoAnalyzer] = None,
) -> FilePromoter:
    """Factory function to create FilePromoter.

    Args:
        weaviate_client: Weaviate client
        redis_client: Redis client
        collection_name: Weaviate collection name
        default_tenant: Default tenant name
        pareto_analyzer: ParetoAnalyzer instance

    Returns:
        FilePromoter instance
    """
    return FilePromoter(
        weaviate_client=weaviate_client,
        redis_client=redis_client,
        collection_name=collection_name,
        default_tenant=default_tenant,
        pareto_analyzer=pareto_analyzer,
    )
