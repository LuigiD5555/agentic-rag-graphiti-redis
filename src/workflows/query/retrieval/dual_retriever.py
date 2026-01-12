"""Dual-collection retriever that searches across both small and large embedding collections."""

import time
from typing import List, Dict, Any, Optional, Tuple
import weaviate
from weaviate.classes.query import MetadataQuery
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class DualCollectionRetriever:
    """Retriever that searches both small (384) and large (768) embedding collections."""

    def __init__(
        self,
        client: weaviate.WeaviateClient,
        small_collection_name: str,
        large_collection_name: str,
        tenant: Optional[str] = None,
        top_k: int = 3,
        alpha: float = 0.7,
        small_embedding_service: Optional[Any] = None,
        large_embedding_service: Optional[Any] = None,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        min_relevance_score: float = 0.5,
        small_collection_weight: float = 0.4,  # Weight for small collection results
    ):
        """Initialize dual-collection retriever.

        Args:
            client: Weaviate client instance
            small_collection_name: Name of small embedding collection (384 dims)
            large_collection_name: Name of large embedding collection (768 dims)
            tenant: Optional tenant ID for multi-tenancy
            top_k: Total number of results to return across both collections
            alpha: Hybrid search weight (1.0=vector only, 0.0=keyword only)
            small_embedding_service: Embedding service for 384-dim vectors
            large_embedding_service: Embedding service for 768-dim vectors
            max_retries: Maximum number of retry attempts
            retry_backoff: Base delay between retries in seconds
            min_relevance_score: Minimum score threshold
            small_collection_weight: Weight for small collection results in fusion (0.0-1.0)
        """
        self.client = client
        self.small_collection_name = small_collection_name
        self.large_collection_name = large_collection_name
        self.tenant = tenant
        self.top_k = top_k
        self.alpha = alpha
        self.small_embedding_service = small_embedding_service
        self.large_embedding_service = large_embedding_service
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.min_relevance_score = min_relevance_score
        self.small_collection_weight = small_collection_weight

        # Get collection references
        if tenant:
            self.small_collection = client.collections.get(
                small_collection_name
            ).with_tenant(tenant)
            self.large_collection = client.collections.get(
                large_collection_name
            ).with_tenant(tenant)
        else:
            self.small_collection = client.collections.get(small_collection_name)
            self.large_collection = client.collections.get(large_collection_name)

        log.info(
            "DualCollectionRetriever initialized: small=%s, large=%s, tenant=%s, "
            "top_k=%d, weight=%.2f",
            small_collection_name, large_collection_name, tenant,
            top_k, small_collection_weight
        )

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
        """Retrieve relevant chunks from both collections and fuse results.

        Args:
            query: User's query string
            top_k: Override default top_k for this query
            filters: Optional metadata filters

        Returns:
            Tuple of (results, metadata):
            - results: Fused list of retrieved documents from both collections
            - metadata: Dict with timing info, collection stats, and error details
        """
        k = top_k or self.top_k
        total_start = time.time()

        metadata = {
            "query": query[:100],
            "top_k": k,
            "small_collection_results": 0,
            "large_collection_results": 0,
            "total_results": 0,
            "embedding_time_ms": None,
            "search_time_ms": None,
            "fusion_time_ms": None,
            "total_time_ms": None,
            "retries": 0,
            "error": None,
            "error_type": None,
            "low_relevance": False,
            "avg_score": None,
        }

        # Build filters once for both collections
        active_filters = self._build_filters(filters)

        # Determine how many results to fetch from each collection
        # Fetch more than needed, then trim after fusion
        small_k = max(k // 2, 1)  # At least 1 from small collection
        large_k = k  # Full k from large collection (more important)

        # Retrieve from small collection with retry logic
        small_results = []
        small_results = self._retrieve_from_collection(
            collection=self.small_collection,
            collection_name=self.small_collection_name,
            embedding_service=self.small_embedding_service,
            query=query,
            limit=small_k,
            filters=active_filters,
            metadata=metadata,
            collection_key="small"
        )

        # Retrieve from large collection with retry logic
        large_results = []
        large_results = self._retrieve_from_collection(
            collection=self.large_collection,
            collection_name=self.large_collection_name,
            embedding_service=self.large_embedding_service,
            query=query,
            limit=large_k,
            filters=active_filters,
            metadata=metadata,
            collection_key="large"
        )

        # Fuse results from both collections
        fusion_start = time.time()
        fused_results = self._fuse_results(
            small_results,
            large_results,
            k,
            self.small_collection_weight
        )
        fusion_time = (time.time() - fusion_start) * 1000
        metadata["fusion_time_ms"] = round(fusion_time, 2)

        # Calculate metrics
        metadata["small_collection_results"] = len(small_results)
        metadata["large_collection_results"] = len(large_results)
        metadata["total_results"] = len(fused_results)

        total_time = (time.time() - total_start) * 1000
        metadata["total_time_ms"] = round(total_time, 2)

        if fused_results:
            scores = [r["score"] for r in fused_results]
            avg_score = sum(scores) / len(scores)
            metadata["avg_score"] = round(avg_score, 3)
            metadata["low_relevance"] = avg_score < self.min_relevance_score

            log.info(
                "Dual retrieval: %d results (small=%d, large=%d) in %.2fms (avg_score=%.3f)",
                len(fused_results), len(small_results), len(large_results),
                total_time, avg_score
            )
        else:
            log.warning("No results from either collection for query: %s", query[:50])

        return fused_results, metadata

    def _fuse_results(
        self,
        small_results: List[Dict[str, Any]],
        large_results: List[Dict[str, Any]],
        top_k: int,
        small_weight: float,
    ) -> List[Dict[str, Any]]:
        """Fuse results from both collections using weighted scoring.

        Args:
            small_results: Results from small embedding collection
            large_results: Results from large embedding collection
            top_k: Number of results to return
            small_weight: Weight for small collection (large gets 1-small_weight)

        Returns:
            Fused and sorted list of results
        """
        large_weight = 1.0 - small_weight

        # Apply weights to scores
        for result in small_results:
            result["weighted_score"] = result["score"] * small_weight

        for result in large_results:
            result["weighted_score"] = result["score"] * large_weight

        # Combine and deduplicate by source+chunk_index
        seen = set()
        combined = []

        # Prioritize large collection results (higher quality)
        for result in large_results:
            key = (result["source"], result["chunk_index"])
            if key not in seen:
                seen.add(key)
                combined.append(result)

        # Add unique results from small collection
        for result in small_results:
            key = (result["source"], result["chunk_index"])
            if key not in seen:
                seen.add(key)
                combined.append(result)

        # Sort by weighted score and trim to top_k
        combined.sort(key=lambda x: x["weighted_score"], reverse=True)
        return combined[:top_k]

    def _retrieve_from_collection(
        self,
        collection,
        collection_name: str,
        embedding_service,
        query: str,
        limit: int,
        filters,
        metadata: Dict[str, Any],
        collection_key: str,  # "small" or "large"
    ) -> List[Dict[str, Any]]:
        """Retrieve from a single collection with retry logic.

        Args:
            collection: Weaviate collection instance
            collection_name: Name of collection (for logging)
            embedding_service: Embedding service for this collection
            query: Search query
            limit: Number of results to fetch
            filters: Weaviate filters to apply
            metadata: Metadata dict to update with stats
            collection_key: "small" or "large" for metadata keys

        Returns:
            List of results
        """
        results = []

        # Retry loop
        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    delay = self.retry_backoff * (2 ** (attempt - 1))
                    log.info(
                        "Retry attempt %d/%d for %s collection after %.1fs delay",
                        attempt + 1, self.max_retries, collection_name, delay
                    )
                    time.sleep(delay)
                    metadata["retries"] = metadata.get("retries", 0) + 1

                if embedding_service:
                    # Vector search with embedding
                    embed_start = time.time()
                    vector = embedding_service.generate(query)
                    embed_time = (time.time() - embed_start) * 1000

                    search_start = time.time()
                    response = collection.query.near_vector(
                        near_vector=vector,
                        limit=limit,
                        filters=filters,
                        return_metadata=MetadataQuery(score=True, distance=True),
                    )
                    search_time = (time.time() - search_start) * 1000

                    log.debug(
                        "%s collection: vector search in %.2fms (embed: %.2fms, search: %.2fms)",
                        collection_name, embed_time + search_time, embed_time, search_time
                    )
                else:
                    # Fallback to hybrid search if no embedding service
                    log.warning(
                        "No embedding service for %s, using hybrid search",
                        collection_name
                    )
                    search_start = time.time()
                    response = collection.query.hybrid(
                        query=query,
                        limit=limit,
                        alpha=self.alpha,
                        filters=filters,
                        return_metadata=MetadataQuery(score=True, distance=True),
                    )
                    search_time = (time.time() - search_start) * 1000

                # Process results
                for obj in response.objects:
                    results.append({
                        "uuid": str(obj.uuid),
                        "text": obj.properties.get("text", ""),
                        "source": obj.properties.get("source", ""),
                        "chunk_index": obj.properties.get("chunk_index", 0),
                        "score": obj.metadata.score if obj.metadata else 0.0,
                        "distance": obj.metadata.distance if obj.metadata else None,
                        "collection": collection_name,
                    })

                log.debug("%s collection returned %d results", collection_name, len(results))
                break  # Success, exit retry loop

            except Exception as e:
                log.error(
                    "%s collection search failed (attempt %d/%d): %s",
                    collection_name, attempt + 1, self.max_retries, e
                )
                metadata[f"{collection_key}_collection_error"] = str(e)

                # If last attempt, give up
                if attempt == self.max_retries - 1:
                    log.error(
                        "All retry attempts exhausted for %s collection",
                        collection_name
                    )
                    return []

        return results

    @staticmethod
    def _build_filters(filters: Optional[Dict[str, Any]]):
        """Build Weaviate filters from dict.

        Args:
            filters: Dict of property filters

        Returns:
            Weaviate Filter object or None
        """
        if not filters:
            return None

        from weaviate.classes.query import Filter

        clauses = []
        for key, value in filters.items():
            if value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                clauses.append(Filter.by_property(key).contains_any(list(value)))
            else:
                clauses.append(Filter.by_property(key).equal(value))

        if not clauses:
            return None

        combined = clauses[0]
        for clause in clauses[1:]:
            combined = combined & clause
        return combined

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for both collections.

        Returns:
            Dictionary with collection stats
        """
        stats = {}

        for collection_name, collection in [
            (self.small_collection_name, self.small_collection),
            (self.large_collection_name, self.large_collection),
        ]:
            try:
                result = collection.aggregate.over_all(total_count=True)
                total = result.total_count if result else 0
                stats[collection_name] = {"total_documents": total}
            except Exception as e:
                log.error(f"Failed to get stats for {collection_name}: {e}")
                stats[collection_name] = {"error": str(e)}

        return stats


__all__ = ["DualCollectionRetriever"]
