"""
SWARM RAG endpoint — /swarm/query

Exposes the SwarmPipeline as a FastAPI route alongside the existing /rag/query.
Uses the same ProviderFactory and WeaviateRetriever as the rest of the app,
but routes through the full SWARM pipeline instead of RAGOrchestrator.

Endpoints:
  POST /swarm/query   — run a query through the SWARM pipeline
  GET  /swarm/health  — verify pipeline is initialized
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src import logger

router = APIRouter(prefix="/swarm", tags=["swarm"])

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class SwarmQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000, description="User query")
    session_id: Optional[str] = Field(None, description="Session ID for continuity")


class SwarmQueryResponse(BaseModel):
    response: str
    session_id: str
    confidence_score: float
    escalated: bool
    intent: str
    domain: str
    complexity: str
    active_branches: list[str]
    latency_ms: dict
    reasoning_summary: str


class SwarmHealthResponse(BaseModel):
    status: str
    pipeline_ready: bool
    provider: str


# ---------------------------------------------------------------------------
# Pipeline singleton (initialized lazily on first request)
# ---------------------------------------------------------------------------

_pipeline = None
_pipeline_error: Optional[str] = None


def _build_pipeline():
    global _pipeline, _pipeline_error
    if _pipeline is not None:
        return _pipeline

    try:
        from src.backends.llm.factory import ProviderFactory
        from src.conf import settings as cfg
        from swarm_rag.core.pipeline import SwarmPipeline

        chat = ProviderFactory(cfg).chat()

        # Try to get WeaviateRetriever from the existing runtime
        weaviate_retriever = None
        neo4j_repo = None
        try:
            from src.backends.storage.vector.weaviate_repository import WeaviateRepository
            from src.workflows.query.retrieval import WeaviateRetriever
            weaviate_host = getattr(cfg, "WEAVIATE_HOST", "localhost")
            weaviate_port = getattr(cfg, "WEAVIATE_PORT", 8080)
            import weaviate as wv
            client = wv.connect_to_local(host=weaviate_host, port=weaviate_port)
            collection = getattr(cfg, "WEAVIATE_CLASS", "Document")
            weaviate_retriever = WeaviateRetriever(client=client, collection_name=collection)
            logger.info("SwarmPipeline: Weaviate connected (%s/%s)", weaviate_host, collection)
        except Exception as exc:
            logger.warning("SwarmPipeline: Weaviate unavailable (%s) — no retrieval", exc)

        try:
            if getattr(cfg, "NEO4J_URI", ""):
                from src.backends.storage.graph.neo4j_repository import Neo4jRepository
                neo4j_repo = Neo4jRepository(cfg)
                logger.info("SwarmPipeline: Neo4j connected")
        except Exception as exc:
            logger.warning("SwarmPipeline: Neo4j unavailable (%s)", exc)

        _pipeline = SwarmPipeline.build(
            chat_interface=chat,
            weaviate_retriever=weaviate_retriever,
            neo4j_repository=neo4j_repo,
        )
        logger.info("SwarmPipeline initialized successfully")
        return _pipeline

    except Exception as exc:
        _pipeline_error = str(exc)
        logger.error("SwarmPipeline initialization failed: %s", exc, exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/query", response_model=SwarmQueryResponse)
async def swarm_query(request: SwarmQueryRequest):
    """Run a query through the SWARM RAG pipeline."""
    try:
        pipeline = _build_pipeline()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SWARM pipeline unavailable: {exc}")

    t0 = time.monotonic()
    try:
        state = await pipeline.run(request.query, session_id=request.session_id)
    except Exception as exc:
        logger.error("SWARM query failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query processing failed: {exc}")

    total_ms = round((time.monotonic() - t0) * 1000, 2)
    state.latency_ms["total_api"] = total_ms

    return SwarmQueryResponse(
        response=state.final_response or "",
        session_id=state.session_id,
        confidence_score=state.reasoning.confidence_score,
        escalated=state.reasoning.escalate_to_llm,
        intent=state.perception.intent,
        domain=state.perception.domain,
        complexity=state.perception.complexity,
        active_branches=state.active_branches,
        latency_ms=state.latency_ms,
        reasoning_summary=state.reasoning.reasoning_summary,
    )


@router.get("/health", response_model=SwarmHealthResponse)
async def swarm_health():
    """Check if the SWARM pipeline is ready."""
    from src.conf import settings as cfg
    provider = getattr(cfg, "PROVIDER", "lmstudio")

    if _pipeline_error:
        return SwarmHealthResponse(
            status="error",
            pipeline_ready=False,
            provider=provider,
        )

    ready = _pipeline is not None
    return SwarmHealthResponse(
        status="ok" if ready else "not_initialized",
        pipeline_ready=ready,
        provider=provider,
    )
