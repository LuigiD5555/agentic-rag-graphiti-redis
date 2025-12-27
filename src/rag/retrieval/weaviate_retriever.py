"""Weaviate-based document retriever for RAG queries."""
from typing import List, Dict, Any, Optional
import weaviate
from weaviate.classes.query import MetadataQuery
from src.rag.audit import get_logger

log = get_logger(__name__)


class WeaviateRetriever:
    """Retrieves relevant document chunks from Weaviate using vector similarity."""

    def __init__(
        self,
        client: weaviate.WeaviateClient,
        collection_name: str,
        tenant: Optional[str] = None,
        top_k: int = 5,
        alpha: float = 0.7,
        embedding_service: Optional[Any] = None,
    ):
        """Initialize Weaviate retriever.

        Args:
            client: Weaviate client instance.
            collection_name: Name of the Weaviate collection/class.
            tenant: Optional tenant ID for multi-tenancy.
            top_k: Number of top results to return (default: 5).
            alpha: Hybrid search weight (1.0=vector only, 0.0=keyword only, 0.7=balanced).
            embedding_service: Optional embedding service for query vectorization.
        """
        self.client = client
        self.collection_name = collection_name
        self.tenant = tenant
        self.top_k = top_k
        self.alpha = alpha
        self.embedding_service = embedding_service

        # Get collection reference
        if tenant:
            self.collection = client.collections.get(collection_name).with_tenant(tenant)
        else:
            self.collection = client.collections.get(collection_name)

        log.info(
            "Initialized WeaviateRetriever: collection=%s, tenant=%s, top_k=%d, has_embedder=%s",
            collection_name, tenant, top_k, embedding_service is not None
        )

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant document chunks for a query.

        Args:
            query: User's query string.
            top_k: Override default top_k for this query.
            filters: Optional metadata filters (e.g., {"source": "specific_doc.pdf"}).

        Returns:
            List of retrieved documents with metadata and scores.
        """
        k = top_k or self.top_k

        try:
            active_filters = self._build_filters(filters)

            # If we have an embedding service, vectorize the query and use near_vector search
            if self.embedding_service:
                log.debug("Generating query embedding for: %s", query[:50])
                query_vector = self.embedding_service.generate(query)
                log.debug("Executing near_vector search with embedding (dim=%d), top_k=%d", len(query_vector), k)

                # Use near_vector search with the generated embedding
                response = self.collection.query.near_vector(
                    near_vector=query_vector,
                    limit=k,
                    filters=active_filters,
                    return_metadata=MetadataQuery(score=True, distance=True),
                )
            else:
                # Fallback to hybrid search if no embedding service
                # Note: This will fail if Weaviate doesn't have a vectorizer configured
                log.warning("No embedding service configured, falling back to hybrid search (may fail)")
                log.debug("Executing hybrid search: query=%s, top_k=%d", query[:50], k)

                response = self.collection.query.hybrid(
                    query=query,
                    limit=k,
                    alpha=self.alpha,
                    filters=active_filters,
                    return_metadata=MetadataQuery(score=True, distance=True),
                )

            results = []
            for obj in response.objects:
                doc = {
                    "uuid": str(obj.uuid),
                    "text": obj.properties.get("text", ""),
                    "source": obj.properties.get("source", ""),
                    "chunk_index": obj.properties.get("chunk_index", 0),
                    "score": obj.metadata.score if obj.metadata else 0.0,
                    "distance": obj.metadata.distance if obj.metadata else None,
                }
                results.append(doc)

            log.info("Retrieved %d documents for query: %s", len(results), query[:50])
            return results

        except Exception as e:
            log.error("Retrieval failed for query '%s': %s", query[:50], e)
            return []

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

        k = top_k or self.top_k

        try:
            log.debug("Searching source=%s with query=%s", source_filter, query[:50])

            response = self.collection.query.hybrid(
                query=query,
                limit=k,
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
