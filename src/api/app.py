"""FastAPI application for RAG API (supports both OpenAI and Ollama formats)."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, APIRouter
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import weaviate

from src.api.routers import rag
from src.api.routers.rag import get_rag_orchestrator as rag_get_rag
from src.api.routers.rag import get_ingestion_orchestrator
from src.api.middleware.thread_manager import ThreadManagerMiddleware
from src.rag.engine import AppConfig
from src.rag.retrieval import WeaviateRetriever
from src.rag.chat import LMStudioChatService
from src.rag.pipeline.rag_orchestrator import RAGOrchestrator
from src.rag.embeddings_factory import get_embedding_service as create_embedding_service
from src.rag.conf import Config
from src.ingestion.orchestrator import IngestionOrchestrator


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Global instances (initialized in lifespan)
_rag_orchestrator: RAGOrchestrator | None = None
_embedding_service = None
_weaviate_client = None
_ingestion_orchestrator: IngestionOrchestrator | None = None
_chat_memory_manager = None
_snapshot_scheduler = None
_cleanup_scheduler = None
_temporal_cleanup_scheduler = None
_redis_client = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for FastAPI app.

    Handles initialization and cleanup of RAG components.
    """
    global _rag_orchestrator, _embedding_service, _weaviate_client, _ingestion_orchestrator, _chat_memory_manager, _snapshot_scheduler, _cleanup_scheduler, _temporal_cleanup_scheduler, _redis_client

    logger.info("Initializing RAG API...")

    try:
        # Load configuration
        config = AppConfig()
        rag_config = Config()
        logger.info("Configuration loaded")

        # Initialize Weaviate client
        logger.info("Connecting to Weaviate at %s", config.WEAVIATE_URL)
        _weaviate_client = weaviate.connect_to_local(
            host=config.WEAVIATE_URL.replace("http://", "").replace("https://", "").split(":")[0],
            port=int(config.WEAVIATE_URL.split(":")[-1]) if ":" in config.WEAVIATE_URL else 8080,
            grpc_port=config.WEAVIATE_GRPC_PORT,
        )

        # Ensure Weaviate schema exists BEFORE any operations
        from src.storage.vector import get_vector_store
        logger.info("Ensuring Weaviate schema exists...")
        get_vector_store(rag_config)  # This creates the schema if missing
        logger.info("Weaviate schema ready")

        # Create embedding service FIRST (needed by retriever for query vectorization)
        _embedding_service = create_embedding_service(rag_config)

        # Create retriever with embedding service for query vectorization
        retriever = WeaviateRetriever(
            client=_weaviate_client,
            collection_name=config.WEAVIATE_CLASS,
            tenant=config.WEAVIATE_DEFAULT_TENANT if config.WEAVIATE_MULTI_TENANCY else None,
            top_k=5,
            embedding_service=_embedding_service,
        )

        # Create chat service (using LM Studio)
        # Note: The chat service expects OPENAI_API_BASE which should end in /v1
        # config.LM_LLM_URL is typically "http://127.0.0.1:1234/v1" or "http://127.0.0.1:1234/v1/completions"
        base_url = config.LM_LLM_URL
        if base_url.endswith("/completions"):
            base_url = base_url.rsplit("/completions", 1)[0]
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"

        chat_service = LMStudioChatService(
            base_url=base_url,
            api_key="not-needed",  # LM Studio doesn't require API key
        )

        # Create ChatMemory manager BEFORE RAG orchestrator
        from src.memory.integration import create_chat_memory_manager
        _chat_memory_manager = create_chat_memory_manager(
            weaviate_client=_weaviate_client,
            embedding_service=_embedding_service,
            snapshot_ttl_days=30,
            enable_cross_chat=True,
            enable_rrf=True,
            enable_mmr=True,
            mmr_lambda=0.5,
        )
        logger.info("ChatMemory manager initialized")

        # Create snapshot scheduler for automatic 24h snapshots
        from src.memory.snapshot_scheduler import create_snapshot_scheduler
        _snapshot_scheduler = create_snapshot_scheduler(
            snapshot_interval=86400  # 24 hours in seconds
        )
        logger.info("Snapshot scheduler initialized (24h interval)")

        # Create cleanup scheduler for expired snapshots (runs every hour)
        from src.memory.cleanup_scheduler import create_cleanup_scheduler
        _cleanup_scheduler = create_cleanup_scheduler(
            chat_memory_manager=_chat_memory_manager,
            snapshot_scheduler=_snapshot_scheduler,
            cleanup_interval=3600,  # 1 hour in seconds
        )
        # Start background cleanup loop
        await _cleanup_scheduler.start()
        logger.info("Cleanup scheduler started (1h interval)")

        # Initialize Redis client (shared across features)
        from src.storage.cache.redis_connection import create_redis_client_with_retry
        redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_password = (os.getenv("REDIS_PASSWORD") or "").strip() or None
        _redis_client = create_redis_client_with_retry(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=False,  # We handle encoding/decoding ourselves
        )
        logger.info(f"Redis client initialized: {redis_host}:{redis_port}")

        # Migrate old Redis conversations to ChatMemory on startup
        from src.memory.core.checkpointer import create_checkpointer
        from src.memory.startup_migrator import migrate_redis_conversations_on_startup
        try:
            # Create checkpointer to access Redis conversations
            checkpointer = create_checkpointer(
                redis_host=redis_host,
                redis_port=redis_port,
                redis_password=redis_password,
                ttl_seconds=172800,  # 48 hours
            )

            # Run migration (synchronous operation)
            migration_stats = await asyncio.to_thread(
                migrate_redis_conversations_on_startup,
                checkpointer=checkpointer,
                chat_memory_manager=_chat_memory_manager,
                snapshot_scheduler=_snapshot_scheduler,
                age_threshold=86400,  # 24 hours
            )

            logger.info(
                "Startup migration completed: scanned=%d, migrated=%d, skipped=%d, errors=%d",
                migration_stats["scanned"],
                migration_stats["migrated"],
                migration_stats["skipped"],
                migration_stats["errors"]
            )
        except Exception as e:
            # Don't fail startup if migration fails
            logger.warning("Startup migration failed (continuing anyway): %s", e)

        # Create ingestion orchestrator
        _ingestion_orchestrator = IngestionOrchestrator(rag_config)

        # Initialize files router for temporal RAG
        from src.api.files.router import initialize_files_router
        from src.api.files.tracking import create_file_tracker
        from src.rag.temporal.retriever import create_multi_tenant_retriever
        from src.rag.temporal.tenant_manager import create_temporal_tenant_manager
        from src.rag.temporal.cleanup_scheduler import create_temporal_cleanup_scheduler

        # Create file tracker
        file_tracker = create_file_tracker(
            redis_client=_redis_client,
            promotion_threshold=int(os.getenv("TEMPORAL_PROMOTION_THRESHOLD", "3")),
            pareto_min_queries=int(os.getenv("TEMPORAL_PARETO_MIN_QUERIES", "5")),
        )

        # Create multi-tenant retriever for temporal files
        multi_tenant_retriever = create_multi_tenant_retriever(
            weaviate_client=_weaviate_client,
            collection_name=config.WEAVIATE_CLASS,
            default_tenant=config.WEAVIATE_DEFAULT_TENANT if config.WEAVIATE_MULTI_TENANCY else None,
            top_k_per_tenant=5,
            embedding_service=_embedding_service,
        )
        logger.info("Multi-tenant retriever created for temporal RAG")

        # Create temporal tenant manager for cleanup
        tenant_manager = create_temporal_tenant_manager(
            weaviate_client=_weaviate_client,
            collection_name=config.WEAVIATE_CLASS,
            ttl_seconds=int(os.getenv("TEMPORAL_TENANT_TTL", "86400")),
        )

        # Create and start background cleanup scheduler
        _temporal_cleanup_scheduler = create_temporal_cleanup_scheduler(
            tenant_manager=tenant_manager,
            redis_client=_redis_client,
            cleanup_interval=int(os.getenv("TEMPORAL_CLEANUP_INTERVAL", "3600")),
        )
        _temporal_cleanup_scheduler.start()
        logger.info("Temporal cleanup scheduler started")

        # Create RAG orchestrator with ChatMemory + Temporal RAG
        _rag_orchestrator = RAGOrchestrator(
            retriever=retriever,
            chat_service=chat_service,
            include_sources=True,
            chat_memory_manager=_chat_memory_manager,
            multi_tenant_retriever=multi_tenant_retriever,
            file_tracker=file_tracker,
        )

        # Initialize files router
        initialize_files_router(
            weaviate_client=_weaviate_client,
            redis_client=_redis_client,
            ingestion_orchestrator=_ingestion_orchestrator,
            collection_name=config.WEAVIATE_CLASS,
            default_tenant=config.WEAVIATE_DEFAULT_TENANT if config.WEAVIATE_MULTI_TENANCY else None,
        )
        logger.info("Temporal RAG files router initialized (with Pareto and promotion)")

        logger.info("RAG API initialized successfully")
        logger.info("API is ready to serve requests")

        yield

    except Exception as e:
        logger.error("Failed to initialize RAG API: %s", e, exc_info=True)
        raise

    finally:
        # Cleanup
        logger.info("Shutting down RAG API...")

        # Stop cleanup scheduler (memory)
        if _cleanup_scheduler:
            try:
                await _cleanup_scheduler.stop()
                logger.info("Memory cleanup scheduler stopped")
            except Exception as e:
                logger.error("Error stopping memory cleanup scheduler: %s", e)

        # Stop temporal cleanup scheduler
        if _temporal_cleanup_scheduler:
            try:
                _temporal_cleanup_scheduler.stop()
                logger.info("Temporal cleanup scheduler stopped")
            except Exception as e:
                logger.error("Error stopping temporal cleanup scheduler: %s", e)

        if _weaviate_client:
            try:
                _weaviate_client.close()
                logger.info("Weaviate client closed")
            except Exception as e:
                logger.error("Error closing Weaviate client: %s", e)


# Determine API mode from environment variable
API_MODE = os.getenv("API_MODE", "ollama").lower()  # "openai" or "ollama"
logger.info(f"API mode: {API_MODE}")


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


# Dependency overrides
def get_rag_instance() -> RAGOrchestrator:
    """Get RAG orchestrator instance."""
    if _rag_orchestrator is None:
        raise RuntimeError("RAG orchestrator not initialized")
    return _rag_orchestrator


def get_embedding_instance():
    """Get embedding service instance."""
    if _embedding_service is None:
        raise RuntimeError("Embedding service not initialized")
    return _embedding_service


def get_ingestion_instance() -> IngestionOrchestrator:
    """Get ingestion orchestrator instance."""
    if _ingestion_orchestrator is None:
        raise RuntimeError("Ingestion orchestrator not initialized")
    return _ingestion_orchestrator


def get_chat_memory_instance():
    """Get ChatMemory manager instance."""
    if _chat_memory_manager is None:
        raise RuntimeError("ChatMemory manager not initialized")
    return _chat_memory_manager


def get_snapshot_scheduler_instance():
    """Get snapshot scheduler instance."""
    if _snapshot_scheduler is None:
        raise RuntimeError("Snapshot scheduler not initialized")
    return _snapshot_scheduler


# Include routers based on API mode
if API_MODE == "openai":
    # OpenAI-compatible routers
    from src.api.openai import (
        chat_router,
        models_router,
        responses_router,
        embeddings_router,
    )
    from src.api.openai.chat import get_rag_orchestrator as openai_chat_get_rag
    from src.api.openai.responses import get_rag_orchestrator as openai_responses_get_rag
    from src.api.openai.embeddings import get_embedding_service as openai_get_embedding

    app.dependency_overrides[openai_chat_get_rag] = get_rag_instance
    app.dependency_overrides[openai_responses_get_rag] = get_rag_instance
    app.dependency_overrides[openai_get_embedding] = get_embedding_instance

    app.include_router(models_router)
    app.include_router(chat_router)
    app.include_router(responses_router)
    app.include_router(embeddings_router)

    logger.info("Loaded OpenAI-compatible routers")
else:
    # Ollama-compatible routers
    from src.api.ollama import ollama_router
    from src.api.ollama.router import get_rag_orchestrator as ollama_get_rag
    from src.api.ollama.router import get_embedding_service as ollama_get_embedding
    from src.api.ollama.router import get_chat_memory_manager as ollama_get_chat_memory
    from src.api.ollama.router import get_snapshot_scheduler as ollama_get_scheduler

    app.dependency_overrides[ollama_get_rag] = get_rag_instance
    app.dependency_overrides[ollama_get_embedding] = get_embedding_instance
    app.dependency_overrides[ollama_get_chat_memory] = get_chat_memory_instance
    app.dependency_overrides[ollama_get_scheduler] = get_snapshot_scheduler_instance

    app.include_router(ollama_router)

    # Also include Ollama router with /ollama prefix for Open WebUI compatibility
    ollama_compat_router = APIRouter(prefix="/ollama")
    ollama_compat_router.include_router(ollama_router)
    app.include_router(ollama_compat_router)

    logger.info("Loaded Ollama-compatible routers")

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
        "rag_initialized": _rag_orchestrator is not None,
        "embedding_initialized": _embedding_service is not None,
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.app:app",
        host="127.0.0.1",  # SECURITY: Localhost only
        port=8000,
        reload=True,
        log_level="info",
    )
