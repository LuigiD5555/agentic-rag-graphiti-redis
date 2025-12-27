"""Persistence layer for ChatMemory snapshots in Weaviate.

Handles:
- Saving snapshots with embeddings
- Retrieving snapshots by user_id
- TTL-based filtering
- Cross-chat recall queries
"""
import logging
from typing import List, Dict, Any, Optional
import weaviate
from weaviate.classes.query import Filter, MetadataQuery

from src.memory.types import ChatMemorySnapshot
from src.memory.storage.chat_memory_schema import (
    CHAT_MEMORY_COLLECTION,
    get_chat_memory_collection,
    is_expired,
)

logger = logging.getLogger(__name__)


class ChatMemoryPersistence:
    """Manages ChatMemory snapshot persistence in Weaviate."""

    def __init__(
        self,
        client: weaviate.WeaviateClient,
        embedding_service: Optional[Any] = None,
    ):
        """Initialize persistence layer.

        Args:
            client: Weaviate client instance
            embedding_service: Service to generate embeddings for summary_dense
        """
        self.client = client
        self.embedding_service = embedding_service
        self.collection = get_chat_memory_collection(client, auto_create=True)

        if not self.collection:
            logger.error("Failed to initialize ChatMemory collection")

    def save_snapshot(self, snapshot: ChatMemorySnapshot) -> bool:
        """Save snapshot to Weaviate with embedding.

        Args:
            snapshot: ChatMemorySnapshot to persist

        Returns:
            True if saved successfully
        """
        if not self.collection:
            logger.error("ChatMemory collection not available")
            return False

        try:
            # Generate embedding for summary_dense
            vector = None
            if self.embedding_service and snapshot.summary_dense:
                try:
                    vector = self.embedding_service.generate(snapshot.summary_dense)
                    logger.debug(
                        f"Generated embedding for snapshot (dim={len(vector)})"
                    )
                except Exception as e:
                    logger.warning(f"Could not generate embedding: {e}")

            # Prepare properties
            properties = {
                "summary_dense": snapshot.summary_dense,
                "key_quotes": snapshot.key_quotes,
                "keywords": snapshot.keywords,
                "thread_id": snapshot.thread_id,
                "user_id": snapshot.user_id,
                "timestamp": snapshot.timestamp,
                "ttl_at": snapshot.ttl_at,
                "pinned": snapshot.pinned,
                "original_message_count": snapshot.original_message_count,
                "compression_ratio": snapshot.compression_ratio,
                "tool_executions": snapshot.tool_executions,
            }

            # Insert with or without vector
            if vector:
                uuid = self.collection.data.insert(
                    properties=properties,
                    vector=vector,
                )
            else:
                uuid = self.collection.data.insert(properties=properties)

            logger.info(
                f"Saved snapshot for thread {snapshot.thread_id[:8]}... "
                f"(uuid={str(uuid)[:8]}..., {snapshot.original_message_count} msgs)"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}", exc_info=True)
            return False

    def get_user_snapshots(
        self,
        user_id: str,
        include_expired: bool = False,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve all snapshots for a user.

        Args:
            user_id: User identifier
            include_expired: Include expired snapshots (default: False)
            limit: Maximum snapshots to return

        Returns:
            List of snapshot dictionaries
        """
        if not self.collection:
            logger.error("ChatMemory collection not available")
            return []

        try:
            # Build filter: user_id AND (pinned OR not expired)
            filters = Filter.by_property("user_id").equal(user_id)

            if not include_expired:
                # Only include: pinned=true OR ttl_at > now
                # Note: Weaviate date comparison requires RFC-3339 format
                from datetime import datetime
                now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

                pinned_filter = Filter.by_property("pinned").equal(True)
                ttl_filter = Filter.by_property("ttl_at").greater_than(now)

                # (pinned=true OR ttl_at > now)
                filters = filters & (pinned_filter | ttl_filter)

            response = self.collection.query.fetch_objects(
                filters=filters,
                limit=limit,
                return_metadata=MetadataQuery(creation_time=True),
            )

            snapshots = []
            for obj in response.objects:
                snapshot = {
                    "uuid": str(obj.uuid),
                    **obj.properties,
                }
                snapshots.append(snapshot)

            logger.info(
                f"Retrieved {len(snapshots)} snapshots for user {user_id[:8]}..."
            )
            return snapshots

        except Exception as e:
            logger.error(f"Failed to retrieve user snapshots: {e}", exc_info=True)
            return []

    def search_snapshots(
        self,
        query: str,
        user_id: Optional[str] = None,
        top_k: int = 5,
        alpha: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Search snapshots using hybrid search (vector + BM25).

        Args:
            query: Search query
            user_id: Optional user filter
            top_k: Number of results
            alpha: Hybrid search weight (1.0=vector, 0.0=BM25, 0.7=balanced)

        Returns:
            List of matching snapshots with scores
        """
        if not self.collection:
            logger.error("ChatMemory collection not available")
            return []

        try:
            # Generate query embedding if available
            query_vector = None
            if self.embedding_service:
                try:
                    query_vector = self.embedding_service.generate(query)
                except Exception as e:
                    logger.warning(f"Could not generate query embedding: {e}")

            # Build filters
            filters = None
            if user_id:
                from datetime import datetime
                now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

                # user_id AND (pinned OR ttl_at > now)
                user_filter = Filter.by_property("user_id").equal(user_id)
                pinned_filter = Filter.by_property("pinned").equal(True)
                ttl_filter = Filter.by_property("ttl_at").greater_than(now)

                filters = user_filter & (pinned_filter | ttl_filter)

            # Execute search
            if query_vector:
                # Use near_vector for better semantic search
                response = self.collection.query.near_vector(
                    near_vector=query_vector,
                    limit=top_k,
                    filters=filters,
                    return_metadata=MetadataQuery(score=True, distance=True),
                )
            else:
                # Fallback to hybrid search
                response = self.collection.query.hybrid(
                    query=query,
                    limit=top_k,
                    alpha=alpha,
                    filters=filters,
                    return_metadata=MetadataQuery(score=True),
                )

            results = []
            for obj in response.objects:
                result = {
                    "uuid": str(obj.uuid),
                    "score": obj.metadata.score if obj.metadata else 0.0,
                    "distance": getattr(obj.metadata, "distance", None) if obj.metadata else None,
                    **obj.properties,
                }
                results.append(result)

            logger.info(
                f"Found {len(results)} snapshots for query: {query[:50]}"
            )
            return results

        except Exception as e:
            logger.error(f"Snapshot search failed: {e}", exc_info=True)
            return []

    def cleanup_expired_snapshots(self, user_id: Optional[str] = None) -> int:
        """Delete expired non-pinned snapshots.

        Args:
            user_id: Optional user filter (if None, cleanup all users)

        Returns:
            Number of snapshots deleted
        """
        if not self.collection:
            logger.error("ChatMemory collection not available")
            return 0

        try:
            from datetime import datetime
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            # Filter: pinned=false AND ttl_at <= now
            filters = (
                Filter.by_property("pinned").equal(False)
                & Filter.by_property("ttl_at").less_or_equal(now)
            )

            if user_id:
                filters = filters & Filter.by_property("user_id").equal(user_id)

            # Delete matching objects
            result = self.collection.data.delete_many(where=filters)

            deleted_count = result.successful if hasattr(result, 'successful') else 0

            logger.info(
                f"Cleanup: deleted {deleted_count} expired snapshots"
                + (f" for user {user_id[:8]}..." if user_id else "")
            )
            return deleted_count

        except Exception as e:
            logger.error(f"Cleanup failed: {e}", exc_info=True)
            return 0

    def pin_snapshot(self, snapshot_uuid: str, pinned: bool = True) -> bool:
        """Pin/unpin a snapshot to exempt from TTL cleanup.

        Args:
            snapshot_uuid: Snapshot UUID
            pinned: Pin (True) or unpin (False)

        Returns:
            True if updated successfully
        """
        if not self.collection:
            return False

        try:
            self.collection.data.update(
                uuid=snapshot_uuid,
                properties={"pinned": pinned},
            )
            logger.info(
                f"Snapshot {snapshot_uuid[:8]}... "
                f"{'pinned' if pinned else 'unpinned'}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to pin snapshot: {e}")
            return False


def create_persistence(
    client: weaviate.WeaviateClient,
    embedding_service: Optional[Any] = None,
) -> ChatMemoryPersistence:
    """Factory function to create persistence layer.

    Args:
        client: Weaviate client
        embedding_service: Optional embedding service

    Returns:
        ChatMemoryPersistence instance
    """
    return ChatMemoryPersistence(client, embedding_service)
