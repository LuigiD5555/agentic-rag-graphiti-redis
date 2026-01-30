"""Weaviate-based document retriever for RAG queries."""
import time
from typing import List, Dict, Any, Optional, Tuple
import weaviate
from weaviate.classes.query import MetadataQuery
from src.workflows.query.audit import get_logger
from src.conf import settings

log = get_logger(__name__)


class RetrievalError(Exception):
    """Base exception for retrieval errors."""
    pass


class RetrievalTimeoutError(RetrievalError):
    """Raised when retrieval times out."""
    pass


class RetrievalConnectionError(RetrievalError):
    """Raised when connection to Weaviate fails."""
    pass


class WeaviateRetriever:
    """Retrieves relevant document chunks from Weaviate using vector similarity."""

    def __init__(
        self,
        client: weaviate.WeaviateClient,
        collection_name: str,
        tenant: Optional[str] = None,
        top_k: Optional[int] = None,
        alpha: float = 0.7,
        embedding_service: Optional[Any] = None,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        min_relevance_score: float = 0.5,
    ):
        """Initialize Weaviate retriever.

        Args:
            client: Weaviate client instance.
            collection_name: Name of the Weaviate collection/class.
            tenant: Optional tenant ID for multi-tenancy.
            top_k: Number of top results to return (uses RAG_DEFAULT_TOP_K if None).
            alpha: Hybrid search weight (1.0=vector only, 0.0=keyword only, 0.7=balanced).
            embedding_service: Optional embedding service for query vectorization.
            max_retries: Maximum number of retry attempts for failed requests.
            retry_backoff: Base delay between retries in seconds (exponential backoff).
            min_relevance_score: Minimum score threshold for considering results relevant.
        """
        self.client = client
        self.collection_name = collection_name
        self.tenant = tenant
        self.top_k = top_k if top_k is not None else settings.RAG_DEFAULT_TOP_K
        self.alpha = alpha
        self.embedding_service = embedding_service
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.min_relevance_score = min_relevance_score

        # Get collection reference
        if tenant:
            self.collection = client.collections.get(collection_name).with_tenant(tenant)
        else:
            self.collection = client.collections.get(collection_name)

        log.info(
            "Initialized WeaviateRetriever: collection=%s, tenant=%s, top_k=%d, "
            "has_embedder=%s, max_retries=%d, min_score=%.2f",
            collection_name, tenant, self.top_k, embedding_service is not None,
            max_retries, min_relevance_score
        )

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
        """Retrieve relevant document chunks for a query with observability and retry logic.

        Args:
            query: User's query string.
            top_k: Override default top_k for this query.
            filters: Optional metadata filters (e.g., {"source": "specific_doc.pdf"}).

        Returns:
            Tuple of (results, metadata):
            - results: List of retrieved documents, or None if error occurred
            - metadata: Dict with timing info, error details, and relevance stats
        """
        result_limit = top_k or self.top_k
        total_start = time.time()

        metadata = {
            "query": query[:100],
            "top_k": result_limit,
            "embedding_time_ms": None,
            "search_time_ms": None,
            "total_time_ms": None,
            "retries": 0,
            "error": None,
            "error_type": None,
            "low_relevance": False,
            "avg_score": None,
        }

        # Retry loop
        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    delay = self.retry_backoff * (2 ** (attempt - 1))
                    log.info("Retry attempt %d/%d after %.1fs delay",
                            attempt + 1, self.max_retries, delay)
                    time.sleep(delay)
                    metadata["retries"] = attempt

                active_filters = self._build_filters(filters)

                # Step 1: Generate embedding if needed
                if self.embedding_service:
                    embed_start = time.time()
                    log.debug("Generating query embedding for: %s", query[:50])

                    query_vector = self.embedding_service.generate(query)

                    embed_time = (time.time() - embed_start) * 1000
                    metadata["embedding_time_ms"] = round(embed_time, 2)
                    log.info("Embedding generated in %.2fms (dim=%d)",
                            embed_time, len(query_vector))

                    # Step 2: Vector search
                    search_start = time.time()
                    log.debug("Executing near_vector search: top_k=%d", result_limit)

                    response = self.collection.query.near_vector(
                        near_vector=query_vector,
                        limit=result_limit,
                        filters=active_filters,
                        return_metadata=MetadataQuery(score=True, distance=True),
                    )

                    search_time = (time.time() - search_start) * 1000
                    metadata["search_time_ms"] = round(search_time, 2)
                    log.info("Vector search completed in %.2fms", search_time)
                else:
                    # Fallback to hybrid search
                    log.warning("No embedding service, using hybrid search (may fail)")
                    search_start = time.time()

                    response = self.collection.query.hybrid(
                        query=query,
                        limit=result_limit,
                        alpha=self.alpha,
                        filters=active_filters,
                        return_metadata=MetadataQuery(score=True, distance=True),
                    )

                    search_time = (time.time() - search_start) * 1000
                    metadata["search_time_ms"] = round(search_time, 2)
                    log.info("Hybrid search completed in %.2fms", search_time)

                # Step 3: Process results
                results = []
                scores = []

                for obj in response.objects:
                    # Convert distance to similarity score for cosine distance
                    # distance: 0 = identical, 2 = opposite
                    # similarity: 1 = identical, -1 = opposite
                    distance = obj.metadata.distance if obj.metadata else None
                    if distance is not None:
                        # Convert cosine distance to similarity: similarity = 1 - distance
                        score = 1.0 - distance
                    else:
                        score = 0.0
                    
                    scores.append(score)

                    doc = {
                        "uuid": str(obj.uuid),
                        "text": obj.properties.get("text", ""),
                        "source": obj.properties.get("source", ""),
                        "chunk_index": obj.properties.get("chunk_index", 0),
                        "score": score,
                        "distance": distance,
                    }
                    results.append(doc)

                # Calculate metrics
                total_time = (time.time() - total_start) * 1000
                metadata["total_time_ms"] = round(total_time, 2)

                if scores:
                    # Filter out None values and ensure we have valid scores
                    valid_scores = [s for s in scores if s is not None]
                    if valid_scores:
                        avg_score = sum(valid_scores) / len(valid_scores)
                        metadata["avg_score"] = round(avg_score, 3)
                        metadata["low_relevance"] = avg_score < self.min_relevance_score
                    else:
                        metadata["avg_score"] = 0.0
                        metadata["low_relevance"] = True

                    log.info(
                        "Retrieved %d documents in %.2fms (avg_score=%.3f, low_relevance=%s): %s",
                        len(results), total_time, metadata["avg_score"],
                        metadata["low_relevance"], query[:50]
                    )
                else:
                    log.warning("No documents retrieved for query: %s", query[:50])

                return results, metadata

            except TimeoutError as e:
                metadata["error_type"] = "timeout"
                metadata["error"] = str(e)
                log.error(
                    "Timeout on attempt %d/%d (after %.2fms): %s",
                    attempt + 1, self.max_retries,
                    (time.time() - total_start) * 1000, e
                )
                if attempt == self.max_retries - 1:
                    # Final attempt failed
                    metadata["total_time_ms"] = round((time.time() - total_start) * 1000, 2)
                    return None, metadata

            except (ConnectionError, weaviate.exceptions.WeaviateConnectionError) as e:
                metadata["error_type"] = "connection"
                metadata["error"] = str(e)
                log.error(
                    "Connection error on attempt %d/%d: %s",
                    attempt + 1, self.max_retries, e
                )
                if attempt == self.max_retries - 1:
                    metadata["total_time_ms"] = round((time.time() - total_start) * 1000, 2)
                    return None, metadata

            except Exception as e:
                metadata["error_type"] = "unknown"
                metadata["error"] = str(e)
                log.error(
                    "Unexpected error on attempt %d/%d: %s",
                    attempt + 1, self.max_retries, e, exc_info=True
                )
                if attempt == self.max_retries - 1:
                    metadata["total_time_ms"] = round((time.time() - total_start) * 1000, 2)
                    return None, metadata

        # Should not reach here, but just in case
        metadata["total_time_ms"] = round((time.time() - total_start) * 1000, 2)
        return None, metadata

    def retrieve_by_source(
        self,
        query: str,
        source_filter: str,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve documents filtered by source file.

        Args:
            query: User's query string.
            source_filter: Source file path to filter by.
            top_k: Number of results to return.

        Returns:
            List of retrieved documents from the specified source.
        """
        from weaviate.classes.query import Filter

        result_limit = top_k or self.top_k

        try:
            log.debug("Searching source=%s with query=%s", source_filter, query[:50])

            response = self.collection.query.hybrid(
                query=query,
                limit=result_limit,
                alpha=self.alpha,
                filters=Filter.by_property("source").equal(source_filter),
                return_metadata=MetadataQuery(score=True),
            )

            results = []
            for obj in response.objects:
                doc = {
                    "uuid": str(obj.uuid),
                    "text": obj.properties.get("text", ""),
                    "source": obj.properties.get("source", ""),
                    "chunk_index": obj.properties.get("chunk_index", 0),
                    "score": obj.metadata.score if obj.metadata else 0.0,
                }
                results.append(doc)

            log.info(
                "Retrieved %d documents from source '%s'",
                len(results), source_filter
            )
            return results

        except Exception as e:
            log.error("Source-filtered retrieval failed: %s", e)
            return []

    def get_file_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a representative metadata record for a file_id."""
        from weaviate.classes.query import Filter

        try:
            response = self.collection.query.fetch_objects(
                limit=1,
                filters=Filter.by_property("file_id").equal(file_id),
            )
            objects = getattr(response, "objects", []) or []
            if not objects:
                return None
            obj = objects[0]
            return getattr(obj, "properties", {}) or {}
        except Exception as e:
            log.error("Metadata fetch failed for file_id '%s': %s", file_id, e)
            return None

    def get_file_location(self, file_id: str) -> Optional[str]:
        """Fetch the file_path for a file_id if available."""
        meta = self.get_file_metadata(file_id)
        if not meta:
            return None
        return meta.get("file_path") or meta.get("source")

    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics.

        Returns:
            Dictionary with collection stats (total objects, etc.).
        """
        try:
            # Get aggregate count
            result = self.collection.aggregate.over_all(total_count=True)
            total = result.total_count if result else 0

            return {
                "collection": self.collection_name,
                "tenant": self.tenant,
                "total_documents": total,
                "top_k": self.top_k,
                "alpha": self.alpha,
            }
        except Exception as e:
            log.error("Failed to get collection stats: %s", e)
            return {"error": str(e)}

    def close(self):
        """Close the Weaviate client connection properly."""
        try:
            if self.client is not None:
                self.client.close()
                log.debug("Weaviate client closed successfully")
        except Exception as e:
            log.warning("Failed to close Weaviate client: %s", e)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure client is closed."""
        self.close()
        return False

    @staticmethod
    def _build_filters(filters: Optional[Dict[str, Any]]):
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


__all__ = ["WeaviateRetriever"]
