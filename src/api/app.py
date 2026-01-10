"""FastAPI application for RAG API (supports both OpenAI and Ollama formats)."""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, APIRouter
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import weaviate

from src.api.routers import rag
from src.api.routers.rag import get_rag_orchestrator as rag_get_rag
from src.api.routers.rag import get_ingestion_orchestrator
from src.middleware.thread_manager import ThreadManagerMiddleware
from src.rag.retrieval import WeaviateRetriever
from src.rag.chat import LMStudioChatService
from src.rag.pipeline.rag_orchestrator import RAGOrchestrator
from src.rag.embeddings_factory import get_embedding_service
from src.conf import settings as rag_config
from src.ingestion.orchestrator import IngestionOrchestrator
from src.providers.factory import ProviderFactory
from src.rag.web_search import SearXNGClient


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
_web_search_client = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Lifespan context manager for initializing and cleaning up resources.

    This function initializes:
    - Weaviate client
    - RAG orchestrator
    - Embedding service
    - Chat memory manager
    - Snapshot scheduler (if enabled)
    - Cleanup scheduler (if enabled)
    - Redis client (if enabled)

    Yields:
        None
    """
    global _rag_orchestrator, _embedding_service, _weaviate_client, _ingestion_orchestrator, _chat_memory_manager, _snapshot_scheduler, _cleanup_scheduler, _temporal_cleanup_scheduler, _redis_client, _web_search_client

    logger.info("Initializing RAG API...")

    _web_search_client = None

    try:
        # Load runtime configuration
        config = rag_config
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
        get_vector_store(config)  # This creates the schema if missing
        logger.info("Weaviate schema ready")

        # Ensure ChatMemory collection exists
        from src.memory.storage.chat_memory_schema import create_chat_memory_collection
        logger.info("Ensuring ChatMemory collection exists...")
        chat_memory_created = create_chat_memory_collection(
            _weaviate_client,
            config=config,
            force_recreate=False
        )
        if chat_memory_created:
            logger.info("ChatMemory collection ready")
        else:
            logger.warning("ChatMemory collection creation failed - memory features may not work")

        # Create embedding service FIRST (needed by retriever for query vectorization)
        provider = ProviderFactory(config)
        _embedding_service = get_embedding_service(config, provider)

        # Create retriever with embedding service for query vectorization
        retriever = WeaviateRetriever(
            client=_weaviate_client,
            collection_name=config.WEAVIATE_CLASS,
            tenant=config.WEAVIATE_DEFAULT_TENANT if config.WEAVIATE_MULTI_TENANCY else None,
            top_k=None,  # Use RAG_DEFAULT_TOP_K from settings
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

        # Get keep_alive setting from config
        keep_alive = config.LMSTUDIO_KEEPALIVE_CHAT

        chat_service = LMStudioChatService(
            base_url=base_url,
            api_key="not-needed",  # LM Studio doesn't require API key
            keep_alive=keep_alive,
        )

        # Create RAG orchestrator
        _rag_orchestrator = RAGOrchestrator(
            retriever=retriever,
            chat_service=chat_service,
        )
        logger.info("RAG orchestrator initialized")

        # Create ingestion orchestrator
        _ingestion_orchestrator = IngestionOrchestrator(rag_config)
        logger.info("Ingestion orchestrator initialized")

        # Initialize Chat Memory manager
        try:
            from src.memory.integration import ChatMemoryManager
            _chat_memory_manager = ChatMemoryManager(
                weaviate_client=_weaviate_client,
                embedding_service=_embedding_service,
                snapshot_ttl_days=config.SNAPSHOT_TTL_DAYS,
            )
            logger.info("Chat memory manager initialized")
        except Exception as e:
            logger.error("Failed to initialize chat memory manager: %s", e)
            _chat_memory_manager = None

        # Initialize snapshot scheduler if enabled
        try:
            if config.SNAPSHOT_ENABLED:
                from src.memory.snapshot_scheduler import SnapshotScheduler
                _snapshot_scheduler = SnapshotScheduler(
                    memory_manager=_chat_memory_manager,
                    interval_hours=config.SNAPSHOT_INTERVAL_HOURS,
                )
                _snapshot_scheduler.start()
                logger.info("Snapshot scheduler started")
        except Exception as e:
            logger.error("Failed to initialize snapshot scheduler: %s", e)
            _snapshot_scheduler = None

        # Initialize cleanup scheduler if enabled
        try:
            if config.CLEANUP_ENABLED:
                from src.memory.cleanup_scheduler import CleanupScheduler
                _cleanup_scheduler = CleanupScheduler(
                    memory_manager=_chat_memory_manager,
                    interval_hours=config.CLEANUP_INTERVAL_HOURS,
                )
                _cleanup_scheduler.start()
                logger.info("Cleanup scheduler started")
        except Exception as e:
            logger.error("Failed to initialize cleanup scheduler: %s", e)
            _cleanup_scheduler = None

        # Initialize temporal cleanup scheduler if enabled
        try:
            if config.TEMPORAL_CLEANUP_ENABLED:
                from src.rag.temporal_cleanup_scheduler import TemporalCleanupScheduler
                _temporal_cleanup_scheduler = TemporalCleanupScheduler(
                    interval_hours=config.TEMPORAL_CLEANUP_INTERVAL_HOURS,
                )
                _temporal_cleanup_scheduler.start()
                logger.info("Temporal cleanup scheduler started")
        except Exception as e:
            logger.error("Failed to initialize temporal cleanup scheduler: %s", e)
            _temporal_cleanup_scheduler = None

        # Initialize Redis client if enabled
        try:
            if getattr(config, "REDIS_ENABLED", True):
                import redis

                # Get Redis configuration from settings (centralized like Django)
                _redis_client = redis.Redis(
                    host=config.REDIS_HOST,
                    port=config.REDIS_PORT,
                    db=config.REDIS_DB,
                    password=config.REDIS_PASSWORD if config.REDIS_PASSWORD else None,
                    decode_responses=True,
                )
                # Test connection
                _redis_client.ping()
                logger.info("Redis client initialized at %s:%s (db=%s)",
                           config.REDIS_HOST, config.REDIS_PORT, config.REDIS_DB)
        except Exception as e:
            logger.error("Failed to initialize Redis client: %s", e)
            _redis_client = None

        # Initialize web search client if enabled
        try:
            if getattr(config, "WEB_SEARCH_ENABLED", False):
                _web_search_client = SearXNGClient(
                    base_url=getattr(config, "SEARXNG_URL", "http://localhost:8080"),
                    timeout=getattr(config, "SEARXNG_TIMEOUT", 10),
                )
                logger.info("Web search client initialized")
        except Exception as e:
            logger.error("Failed to initialize web search client: %s", e)
            _web_search_client = None

        logger.info("RAG API initialization complete")

        yield

    except Exception as e:
        logger.error("Failed to initialize RAG API: %s", e, exc_info=True)
        raise
    finally:
        # Cleanup resources
        logger.info("Shutting down RAG API...")

        # Stop schedulers
        for scheduler, name in [
            (_snapshot_scheduler, "snapshot"),
            (_cleanup_scheduler, "cleanup"),
            (_temporal_cleanup_scheduler, "temporal cleanup"),
        ]:
            if scheduler:
                try:
                    scheduler.stop()
                    logger.info("%s scheduler stopped", name)
                except Exception as e:
                    logger.error("Error stopping %s scheduler: %s", name, e)

        # Close Weaviate client
        if _weaviate_client:
            try:
                _weaviate_client.close()
                logger.info("Weaviate client closed")
            except Exception as e:
                logger.error("Error closing Weaviate client: %s", e)


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
