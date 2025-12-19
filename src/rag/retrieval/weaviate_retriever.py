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
    ):
        """Initialize Weaviate retriever.

        Args:
            client: Weaviate client instance.
            collection_name: Name of the Weaviate collection/class.
            tenant: Optional tenant ID for multi-tenancy.
            top_k: Number of top results to return (default: 5).
            alpha: Hybrid search weight (1.0=vector only, 0.0=keyword only, 0.7=balanced).
        """
        self.client = client
        self.collection_name = collection_name
        self.tenant = tenant
        self.top_k = top_k
        self.alpha = alpha

        # Get collection reference
        if tenant:
            self.collection = client.collections.get(collection_name).with_tenant(tenant)
        else:
            self.collection = client.collections.get(collection_name)

        log.info(
            "Initialized WeaviateRetriever: collection=%s, tenant=%s, top_k=%d",
            collection_name, tenant, top_k
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
            log.debug("Executing hybrid search: query=%s, top_k=%d", query[:50], k)

            # Hybrid search (combines vector + keyword search)
            response = self.collection.query.hybrid(
                query=query,
                limit=k,
                alpha=self.alpha,
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


__all__ = ["WeaviateRetriever"]
