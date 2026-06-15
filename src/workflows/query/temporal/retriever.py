"""Multi-tenant retriever for temporal RAG.

Retrieves from multiple tenants (default KB + temporal files) and combines results.
"""
import logging
from typing import List, Dict, Any, Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor
import weaviate
from weaviate.classes.query import MetadataQuery

logger = logging.getLogger(__name__)


class MultiTenantRetriever:
    """Retrieves from multiple tenants and combines results."""

    def __init__(
        self,
        client: weaviate.WeaviateClient,
        collection_name: str,
        default_tenant: Optional[str] = None,
        top_k_per_tenant: int = 5,
        embedding_service: Optional[Any] = None,
        alpha: float = 0.7,
    ):
        """Initialize multi-tenant retriever.

        Args:
            client: Weaviate client instance
            collection_name: Collection name
            default_tenant: Default tenant (permanent KB)
            top_k_per_tenant: Number of results per tenant
            embedding_service: Embedding service for query vectorization
            alpha: Hybrid search alpha parameter
        """
        self.client = client
        self.collection_name = collection_name
        self.default_tenant = default_tenant
        self.top_k_per_tenant = top_k_per_tenant
        self.embedding_service = embedding_service
        self.alpha = alpha

        logger.info(
            f"MultiTenantRetriever initialized: collection={collection_name}, "
            f"default_tenant={default_tenant}, top_k={top_k_per_tenant}"
        )

    def retrieve_from_tenants(
        self,
        query: str,
        tenants: List[str],
        top_k_per_tenant: Optional[int] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Retrieve from multiple tenants in parallel.

        Args:
            query: User query
            tenants: List of tenant names to search
            top_k_per_tenant: Override default top_k

        Returns:
            Dictionary mapping tenant name to list of results
        """
        per_tenant_limit = top_k_per_tenant or self.top_k_per_tenant

        # Generate query embedding once (reuse across tenants)
        query_vector = None
        if self.embedding_service:
            try:
                query_vector = self.embedding_service.generate(query)
                logger.debug(f"Generated query embedding (dim={len(query_vector)})")
            except Exception as e:
                logger.warning(f"Failed to generate query embedding: {e}")

        # Retrieve from each tenant in parallel
        with ThreadPoolExecutor(max_workers=len(tenants)) as executor:
            futures = {
                executor.submit(
                    self._retrieve_from_single_tenant,
                    query,
                    tenant,
                    per_tenant_limit,
                    query_vector,
                ): tenant
                for tenant in tenants
            }

            results = {}
            for future in futures:
                tenant = futures[future]
                try:
                    tenant_results = future.result(timeout=10)
                    results[tenant] = tenant_results
                    logger.debug(
                        f"Retrieved {len(tenant_results)} results from tenant {tenant}"
                    )
                except Exception as e:
                    logger.error(f"Failed to retrieve from tenant {tenant}: {e}")
                    results[tenant] = []

        return results

    def _retrieve_from_single_tenant(
        self,
        query: str,
        tenant: str,
        per_tenant_limit: int,
        query_vector: Optional[List[float]] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve from a single tenant.

        Args:
            query: User query
            tenant: Tenant name
            per_tenant_limit: Number of results per tenant
            query_vector: Pre-computed query embedding (optional)

        Returns:
            List of retrieved documents
        """
        try:
            # Get collection with tenant
            collection = self.client.collections.get(self.collection_name)

            # Use with_tenant to query specific tenant
            tenant_collection = collection.with_tenant(tenant) if tenant else collection

            # Use near_vector if we have embedding
            if query_vector is not None:
                response = tenant_collection.query.near_vector(
                    near_vector=query_vector,
                    limit=per_tenant_limit,
                    return_metadata=MetadataQuery(score=True, distance=True),
                )
            else:
                # Fallback to hybrid search
                response = tenant_collection.query.hybrid(
                    query=query,
                    limit=per_tenant_limit,
                    alpha=self.alpha,
                    return_metadata=MetadataQuery(score=True, distance=True),
                )

            # Parse results
            results = []
            for obj in response.objects:
                doc = {
                    "uuid": str(obj.uuid),
                    "text": obj.properties.get("text", ""),
                    "source": obj.properties.get("source", ""),
                    "chunk_index": obj.properties.get("chunk_index", 0),
                    "score": obj.metadata.score if obj.metadata else 0.0,
                    "distance": obj.metadata.distance if obj.metadata else None,
                    "tenant": tenant,  # Tag with source tenant
                    "is_temporal": tenant.startswith("temp_") if tenant else False,
                }
                results.append(doc)

            return results

        except Exception as e:
            logger.error(f"Failed to retrieve from tenant {tenant}: {e}", exc_info=True)
            return []

    def retrieve_with_temporal(
        self,
        query: str,
        thread_id: Optional[str] = None,
        top_k_total: int = 10,
    ) -> Dict[str, Any]:
        """Retrieve from default KB + temporal tenant (if exists).

        Args:
            query: User query
            thread_id: Thread ID (for temporal tenant)
            top_k_total: Total number of results to return after fusion

        Returns:
            Dictionary with results from each tenant and combined results
        """
        tenants = []

        # Always search default KB
        if self.default_tenant:
            tenants.append(self.default_tenant)

        # Add temporal tenant if thread_id provided
        if thread_id:
            temp_tenant = f"temp_{thread_id}"

            # Check if temporal tenant exists
            try:
                collection = self.client.collections.get(self.collection_name)
                existing_tenants = collection.tenants.get()
                tenant_names = [t.name for t in existing_tenants]

                if temp_tenant in tenant_names:
                    tenants.append(temp_tenant)
                    logger.debug(f"Including temporal tenant: {temp_tenant}")
                else:
                    logger.debug(f"Temporal tenant {temp_tenant} does not exist")
            except Exception as e:
                logger.warning(f"Failed to check if temporal tenant exists: {e}")

        # Retrieve from all tenants
        per_tenant_results = self.retrieve_from_tenants(
            query=query,
            tenants=tenants,
            top_k_per_tenant=self.top_k_per_tenant,
        )

        # Separate KB and temporal results
        kb_results = per_tenant_results.get(self.default_tenant, [])
        temporal_results = []
        if thread_id:
            temp_tenant = f"temp_{thread_id}"
            temporal_results = per_tenant_results.get(temp_tenant, [])

        # Combine results (simple concatenation for now, RRF in next step)
        all_results = kb_results + temporal_results

        # Sort by score and limit
        all_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        combined_results = all_results[:top_k_total]

        return {
            "kb_results": kb_results,
            "temporal_results": temporal_results,
            "combined_results": combined_results,
            "kb_count": len(kb_results),
            "temporal_count": len(temporal_results),
            "total_count": len(combined_results),
        }


def apply_rrf_fusion(
    kb_results: List[Dict[str, Any]],
    temporal_results: List[Dict[str, Any]],
    rrf_k: int = 60,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """Apply Reciprocal Rank Fusion (RRF) to combine results from KB and temporal.

    Args:
        kb_results: Results from permanent KB
        temporal_results: Results from temporal files
        rrf_k: RRF constant (default: 60)
        top_k: Number of final results

    Returns:
        List of fused and re-ranked results
    """
    # Build mapping of UUID to document
    doc_map = {}
    rrf_scores = {}

    # Process KB results
    for rank, doc in enumerate(kb_results, start=1):
        uuid = doc["uuid"]
        doc_map[uuid] = doc
        rrf_scores[uuid] = rrf_scores.get(uuid, 0.0) + 1.0 / (rrf_k + rank)

    # Process temporal results
    for rank, doc in enumerate(temporal_results, start=1):
        uuid = doc["uuid"]
        if uuid not in doc_map:
            doc_map[uuid] = doc
        rrf_scores[uuid] = rrf_scores.get(uuid, 0.0) + 1.0 / (rrf_k + rank)

    # Sort by RRF score
    sorted_uuids = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

    # Build final results
    fused_results = []
    for uuid, rrf_score in sorted_uuids[:top_k]:
        doc = doc_map[uuid].copy()
        doc["rrf_score"] = rrf_score
        fused_results.append(doc)

    logger.debug(
        f"RRF fusion: {len(kb_results)} KB + {len(temporal_results)} temporal "
        f"→ {len(fused_results)} fused results"
    )

    return fused_results


def create_multi_tenant_retriever(
    weaviate_client: weaviate.WeaviateClient,
    collection_name: str,
    default_tenant: Optional[str] = None,
    top_k_per_tenant: int = 5,
    embedding_service: Optional[Any] = None,
) -> MultiTenantRetriever:
    """Factory function to create MultiTenantRetriever.

    Args:
        weaviate_client: Weaviate client instance
        collection_name: Collection name
        default_tenant: Default tenant name
        top_k_per_tenant: Results per tenant
        embedding_service: Embedding service

    Returns:
        MultiTenantRetriever instance
    """
    return MultiTenantRetriever(
        client=weaviate_client,
        collection_name=collection_name,
        default_tenant=default_tenant,
        top_k_per_tenant=top_k_per_tenant,
        embedding_service=embedding_service,
    )
