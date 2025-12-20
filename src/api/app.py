"""FastAPI application for OpenAI-compatible RAG API."""
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import weaviate

from src.api.routers import models, chat, responses, embeddings
from src.api.routers.chat import get_rag_orchestrator as chat_get_rag
from src.api.routers.responses import get_rag_orchestrator as responses_get_rag
from src.api.routers.embeddings import get_embedding_service
from src.rag.engine import AppConfig
from src.rag.retrieval import WeaviateRetriever
from src.rag.chat import LMStudioChatService
from src.rag.pipeline.rag_orchestrator import RAGOrchestrator
from src.rag.embeddings_factory import get_embedding_service as create_embedding_service
from src.rag.conf import Config


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for FastAPI app.

    Handles initialization and cleanup of RAG components.
    """
    global _rag_orchestrator, _embedding_service, _weaviate_client

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

        # Create retriever
        retriever = WeaviateRetriever(
            client=_weaviate_client,
            collection_name=config.WEAVIATE_CLASS,
            tenant=config.WEAVIATE_DEFAULT_TENANT if config.WEAVIATE_MULTI_TENANCY else None,
            top_k=5,
        )

        # Create chat service (using LM Studio)
        # Note: The chat service expects OPENAI_API_BASE which should be set to LM Studio
        base_url = config.LM_LLM_URL.rsplit("/v1/completions", 1)[0]
        chat_service = LMStudioChatService(
            base_url=base_url,
            api_key="not-needed",  # LM Studio doesn't require API key
        )

        # Create RAG orchestrator
        _rag_orchestrator = RAGOrchestrator(
            retriever=retriever,
            chat_service=chat_service,
            include_sources=True,
        )

        # Create embedding service
        _embedding_service = create_embedding_service(rag_config)

        logger.info("RAG API initialized successfully")
        logger.info("API is ready to serve requests")

        yield

    except Exception as e:
        logger.error("Failed to initialize RAG API: %s", e, exc_info=True)
        raise

    finally:
        # Cleanup
        logger.info("Shutting down RAG API...")
        if _weaviate_client:
            try:
                _weaviate_client.close()
                logger.info("Weaviate client closed")
            except Exception as e:
                logger.error("Error closing Weaviate client: %s", e)


# Create FastAPI app
app = FastAPI(
    title="RAG API",
    description="OpenAI-compatible API for RAG (Retrieval-Augmented Generation) system",
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


# Override dependencies
app.dependency_overrides[chat_get_rag] = get_rag_instance
app.dependency_overrides[responses_get_rag] = get_rag_instance
app.dependency_overrides[get_embedding_service] = get_embedding_instance


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


# Include routers
app.include_router(models.router)
app.include_router(chat.router)
app.include_router(responses.router)
app.include_router(embeddings.router)


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
    return {
        "message": "RAG API - OpenAI-compatible endpoint",
        "version": "1.0.0",
        "endpoints": {
            "models": "GET /v1/models",
            "chat_completions": "POST /v1/chat/completions",
            "responses": "POST /v1/responses",
            "embeddings": "POST /v1/embeddings",
            "health": "GET /health",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
