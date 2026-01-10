"""Router for RAG statistics and monitoring endpoints."""
import logging
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from src.rag.conf import Config

_config = Config()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stats", tags=["stats"])


# Response models
class GraphStats(BaseModel):
    """Graph database statistics."""
    nodes: int
    relations: int
    node_types: Dict[str, int]
    relation_types: Dict[str, int]


class VectorStats(BaseModel):
    """Vector store statistics."""
    total_documents: int
    total_chunks: int
    tenants: List[str]
    collection_name: str


class RAGStats(BaseModel):
    """Overall RAG system statistics."""
    documents_indexed: int
    chunks_indexed: int
    active_tenants: int
    graph_nodes: int
    graph_relations: int
    redis_memory_mb: float
    weaviate_objects: int


class QueryMetrics(BaseModel):
    """Recent query metrics."""
    total_queries: int
    avg_latency_ms: float
    avg_relevance_score: float
    last_query: str


# Dependency injection placeholders
async def get_weaviate_client():
    """Get Weaviate client instance."""
    from src.api.app import _weaviate_client
    if _weaviate_client is None:
        raise HTTPException(status_code=500, detail="Weaviate client not initialized")
    return _weaviate_client


async def get_redis_client():
    """Get Redis client instance."""
    from src.api.app import _redis_client
    if _redis_client is None:
        raise HTTPException(status_code=500, detail="Redis client not initialized")
    return _redis_client


@router.get("/rag", response_model=RAGStats)
async def get_rag_stats(
    weaviate_client = Depends(get_weaviate_client),
    redis_client = Depends(get_redis_client),
) -> RAGStats:
    """Get overall RAG system statistics."""
    try:
        import os
        from src.rag.engine import AppConfig

        config = AppConfig()
        collection_name = config.WEAVIATE_CLASS

        # Get Weaviate stats
        collection = weaviate_client.collections.get(collection_name)

        # Count total objects across all tenants
        total_objects = 0
        tenants = []

        try:
            # Get all tenants if multi-tenancy is enabled
            if config.WEAVIATE_MULTI_TENANCY:
                tenant_list = collection.tenants.get()
                tenants = [t.name for t in tenant_list]

                # Count objects per tenant
                for tenant in tenants:
                    try:
                        response = collection.with_tenant(tenant).aggregate.over_all(
                            total_count=True
                        )
                        total_objects += response.total_count or 0
                    except Exception as e:
                        logger.warning(f"Could not get stats for tenant {tenant}: {e}")
            else:
                # Single tenant mode
                response = collection.aggregate.over_all(total_count=True)
                total_objects = response.total_count or 0
                tenants = [config.WEAVIATE_DEFAULT_TENANT]
        except Exception as e:
            logger.error(f"Error getting Weaviate stats: {e}")
            total_objects = 0
            tenants = []

        # Get Redis memory usage
        redis_memory_mb = 0.0
        try:
            info = redis_client.info("memory")
            redis_memory_bytes = info.get("used_memory", 0)
            redis_memory_mb = redis_memory_bytes / (1024 * 1024)
        except Exception as e:
            logger.warning(f"Could not get Redis memory stats: {e}")

        # TODO: Get Neo4j graph stats (placeholder for now)
        graph_nodes = 0
        graph_relations = 0

        return RAGStats(
            documents_indexed=total_objects,  # Approximation
            chunks_indexed=total_objects,
            active_tenants=len(tenants),
            graph_nodes=graph_nodes,
            graph_relations=graph_relations,
            redis_memory_mb=round(redis_memory_mb, 2),
            weaviate_objects=total_objects,
        )
    except Exception as e:
        logger.error(f"Error getting RAG stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph", response_model=GraphStats)
async def get_graph_stats() -> GraphStats:
    """Get graph database statistics from Neo4j."""
    try:
        import os
        from neo4j import GraphDatabase

        # Get Neo4j connection details
        uri = _config.NEO4J_URI
        user = _config.NEO4J_USER
        password = _config.NEO4J_PASSWORD

        driver = GraphDatabase.driver(uri, auth=(user, password))

        with driver.session() as session:
            # Count nodes
            node_result = session.run("MATCH (n) RETURN count(n) as count")
            total_nodes = node_result.single()["count"]

            # Count relationships
            rel_result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
            total_relations = rel_result.single()["count"]

            # Count nodes by type
            node_types_result = session.run(
                "MATCH (n) RETURN labels(n) as labels, count(*) as count"
            )
            node_types = {}
            for record in node_types_result:
                labels = record["labels"]
                if labels:
                    label = labels[0] if labels else "Unknown"
                    node_types[label] = record["count"]

            # Count relationships by type
            rel_types_result = session.run(
                "MATCH ()-[r]->() RETURN type(r) as type, count(*) as count"
            )
            relation_types = {record["type"]: record["count"] for record in rel_types_result}

        driver.close()

        return GraphStats(
            nodes=total_nodes,
            relations=total_relations,
            node_types=node_types,
            relation_types=relation_types,
        )
    except Exception as e:
        logger.error(f"Error getting graph stats: {e}", exc_info=True)
        # Return empty stats if Neo4j is not available
        return GraphStats(
            nodes=0,
            relations=0,
            node_types={},
            relation_types={},
        )


@router.get("/vector", response_model=VectorStats)
async def get_vector_stats(
    weaviate_client = Depends(get_weaviate_client),
) -> VectorStats:
    """Get vector store statistics."""
    try:
        from src.rag.engine import AppConfig

        config = AppConfig()
        collection_name = config.WEAVIATE_CLASS

        collection = weaviate_client.collections.get(collection_name)

        # Get all tenants
        tenants = []
        total_chunks = 0

        if config.WEAVIATE_MULTI_TENANCY:
            tenant_list = collection.tenants.get()
            tenants = [t.name for t in tenant_list]

            # Count objects per tenant
            for tenant in tenants:
                try:
                    response = collection.with_tenant(tenant).aggregate.over_all(
                        total_count=True
                    )
                    total_chunks += response.total_count or 0
                except Exception as e:
                    logger.warning(f"Could not get stats for tenant {tenant}: {e}")
        else:
            tenants = [config.WEAVIATE_DEFAULT_TENANT]
            response = collection.aggregate.over_all(total_count=True)
            total_chunks = response.total_count or 0

        return VectorStats(
            total_documents=total_chunks,  # Approximation
            total_chunks=total_chunks,
            tenants=tenants,
            collection_name=collection_name,
        )
    except Exception as e:
        logger.error(f"Error getting vector stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics", response_model=QueryMetrics)
async def get_query_metrics(
    redis_client = Depends(get_redis_client),
) -> QueryMetrics:
    """Get recent query metrics from Redis."""
    try:
        # This is a placeholder - you would implement actual metrics tracking
        # For now, return dummy data
        return QueryMetrics(
            total_queries=0,
            avg_latency_ms=0.0,
            avg_relevance_score=0.0,
            last_query="",
        )
    except Exception as e:
        logger.error(f"Error getting query metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
