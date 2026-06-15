"""Router for RAG statistics and monitoring endpoints."""
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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
    weaviate_objects: int


class QueryMetrics(BaseModel):
    """Recent query metrics."""
    total_queries: int
    avg_latency_ms: float
    avg_relevance_score: float
    last_query: str


# Dependency injection
async def get_weaviate_client():
    """Get Weaviate client instance."""
    from src.api.app import runtime_resources
    if runtime_resources is None or runtime_resources.weaviate_client is None:
        raise HTTPException(status_code=500, detail="Weaviate client not initialized")
    return runtime_resources.weaviate_client


async def get_neo4j_repository() -> Optional[Any]:
    """Get Neo4j repository instance (None if not enabled)."""
    from src.api.app import runtime_resources
    if runtime_resources is None:
        return None
    return runtime_resources.neo4j_repository


@router.get("/rag", response_model=RAGStats)
async def get_rag_stats(
    weaviate_client = Depends(get_weaviate_client),
    neo4j_repo = Depends(get_neo4j_repository),
) -> RAGStats:
    """Get overall RAG system statistics."""
    try:
        from src.workflows.query.engine import AppConfig

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

        # Get Neo4j graph stats if repository is available
        graph_nodes = 0
        graph_relations = 0
        if neo4j_repo is not None:
            try:
                with neo4j_repo.driver.session() as session:
                    graph_nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
                    graph_relations = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            except Exception as exc:
                logger.warning("Could not fetch Neo4j stats for /rag: %s", exc)

        return RAGStats(
            documents_indexed=total_objects,  # Approximation
            chunks_indexed=total_objects,
            active_tenants=len(tenants),
            graph_nodes=graph_nodes,
            graph_relations=graph_relations,
            weaviate_objects=total_objects,
        )
    except Exception as e:
        logger.error(f"Error getting RAG stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/graph", response_model=GraphStats)
async def get_graph_stats(
    neo4j_repo = Depends(get_neo4j_repository),
) -> GraphStats:
    """Get graph database statistics from Neo4j."""
    if neo4j_repo is None:
        return GraphStats(nodes=0, relations=0, node_types={}, relation_types={})

    try:
        with neo4j_repo.driver.session() as session:
            total_nodes = session.run("MATCH (n) RETURN count(n) as count").single()["count"]
            total_relations = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()["count"]

            node_types = {}
            for record in session.run("MATCH (n) RETURN labels(n) as labels, count(*) as count"):
                labels = record["labels"]
                if labels:
                    node_types[labels[0]] = record["count"]

            relation_types = {
                record["type"]: record["count"]
                for record in session.run("MATCH ()-[r]->() RETURN type(r) as type, count(*) as count")
            }

        return GraphStats(
            nodes=total_nodes,
            relations=total_relations,
            node_types=node_types,
            relation_types=relation_types,
        )
    except Exception as e:
        logger.error("Error getting graph stats: %s", e, exc_info=True)
        return GraphStats(nodes=0, relations=0, node_types={}, relation_types={})


@router.get("/vector", response_model=VectorStats)
async def get_vector_stats(
    weaviate_client = Depends(get_weaviate_client),
) -> VectorStats:
    """Get vector store statistics."""
    try:
        from src.workflows.query.engine import AppConfig

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
async def get_query_metrics() -> QueryMetrics:
    """Get recent query metrics (placeholder)."""
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
