"""FastAPI application for RAG API (supports both OpenAI and Ollama formats)."""
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import rag
from src.api.routers.rag import get_rag_orchestrator as rag_get_rag
from src.api.routers.rag import get_ingestion_orchestrator
from src.api.runtime import RuntimeFactory, RuntimeResources
from src.middleware.thread_manager import ThreadManagerMiddleware
from src.rag.pipeline.rag_orchestrator import RAGOrchestrator
from src.conf import settings as rag_config
from src.ingestion.orchestrator import IngestionOrchestrator
from src.providers.api_factory import get_api_router_family


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

runtime_factory = RuntimeFactory(rag_config)
runtime_resources: Optional[RuntimeResources] = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for initializing the RAG runtime."""
    global runtime_resources

    logger.info("Initializing RAG API...")
    resources: Optional[RuntimeResources] = None

    try:
        resources = runtime_factory.create()
        runtime_resources = resources
        yield
    except Exception as exc:
        logger.error("Failed to initialize RAG API: %s", exc, exc_info=True)
        raise
    finally:
        logger.info("Shutting down RAG API...")
        runtime_factory.shutdown(resources)
        runtime_resources = None


# Determine API mode from runtime configuration
API_MODE = rag_config.API_MODE
logger.info("API mode: %s", API_MODE)


# Create FastAPI app
if API_MODE == "openai":
    app = FastAPI(
        title="RAG API",
        description="OpenAI-compatible API for RAG (Retrieval-Augmented Generation) system",
        version="1.0.0",
        lifespan=lifespan,
    )
else:
    app = FastAPI(
        title="RAG API",
        description="Ollama-compatible API for RAG (Retrieval-Augmented Generation) system",
        version="1.0.0",
        lifespan=lifespan,
    )


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this based on your needs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Thread Manager middleware (for memory system)
app.add_middleware(ThreadManagerMiddleware)


def _require_runtime_resources() -> RuntimeResources:
    if runtime_resources is None:
        raise RuntimeError("Runtime resources not initialized")
    return runtime_resources


# Dependency overrides
def get_rag_instance() -> RAGOrchestrator:
    """Get RAG orchestrator instance."""
    return _require_runtime_resources().rag_orchestrator


def get_embedding_instance():
    """Get embedding service instance."""
    return _require_runtime_resources().embedding_service


def get_ingestion_instance() -> IngestionOrchestrator:
    """Get ingestion orchestrator instance."""
    return _require_runtime_resources().ingestion_orchestrator


def get_chat_memory_instance():
    """Get ChatMemory manager instance."""
    manager = _require_runtime_resources().chat_memory_manager
    if manager is None:
        raise RuntimeError("ChatMemory manager not initialized")
    return manager


def get_snapshot_scheduler_instance():
    """Get snapshot scheduler instance."""
    scheduler = _require_runtime_resources().snapshot_scheduler
    if scheduler is None:
        raise RuntimeError("Snapshot scheduler not initialized")
    return scheduler


# Include routers based on API mode (via factory to hide HTTP specifics)
api_family = get_api_router_family(rag_config)
api_family.apply(
    app,
    providers={
        "rag": get_rag_instance,
        "embedding": get_embedding_instance,
        "chat_memory": get_chat_memory_instance,
        "snapshot_scheduler": get_snapshot_scheduler_instance,
    },
)
logger.info("Loaded API router family: %s", api_family.name)


# Always include RAG router (for ingestion)
app.dependency_overrides[rag_get_rag] = get_rag_instance
app.dependency_overrides[get_ingestion_orchestrator] = get_ingestion_instance
app.include_router(rag.router)

# Include files router for temporal RAG (OpenAI-compatible)
from src.api.files.router import router as files_router
app.include_router(files_router)
logger.info("Files router (/v1/files) included")

# Include volumes router for external volume management
from src.api.routers.volumes import router as volumes_router
from src.api.routers.exclusions import router as exclusions_router
app.include_router(volumes_router)
logger.info("Volumes router (/volumes) included")
app.include_router(exclusions_router)
logger.info("Exclusions router (/exclusions) included")

# Include stats router for monitoring and dashboards
from src.api.routers.stats import router as stats_router
app.include_router(stats_router)
logger.info("Stats router (/api/stats) included")


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": str(exc),
                "type": "internal_server_error",
                "code": "internal_error",
            }
        },
    )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "rag_initialized": runtime_resources is not None,
        "embedding_initialized": bool(runtime_resources and runtime_resources.embedding_service),
    }


@app.get("/")
async def root():
    """Root endpoint."""
    if API_MODE == "openai":
        return {
            "message": "RAG API - OpenAI-compatible endpoint",
            "version": "1.0.0",
            "api_mode": "openai",
            "endpoints": {
                "models": "GET /v1/models",
                "chat_completions": "POST /v1/chat/completions",
                "responses": "POST /v1/responses",
                "embeddings": "POST /v1/embeddings",
                "rag_ingest": "POST /rag/ingest",
                "rag_query": "POST /rag/query",
                "health": "GET /health",
            },
        }
    else:
        return {
            "message": "RAG API - Ollama-compatible endpoint",
            "version": "1.0.0",
            "api_mode": "ollama",
            "endpoints": {
                "generate": "POST /api/generate",
                "chat": "POST /api/chat",
                "embeddings": "POST /api/embeddings",
                "pull": "POST /api/pull",
                "tags": "GET /api/tags",
                "version": "GET /api/version",
                "rag_ingest": "POST /rag/ingest",
                "rag_query": "POST /rag/query",
                "health": "GET /health",
            },
        }
