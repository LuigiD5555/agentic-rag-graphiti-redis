"""Lightweight API proxy for RAG system.

This API acts as a thin HTTP translation layer that converts OpenAI/Ollama format
requests into the internal RAG format and proxies them to the core service.

Architecture:
    Client → API (this) → Core Service (app container) → RAG Stack

This keeps the API container minimal (~150-200 MB) while the core container
handles all the heavy lifting (Weaviate, embeddings, LLM, etc).
"""
import logging
import os
from typing import Any, Dict

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Core service URL (the actual RAG stack running in 'app' container)
CORE_SERVICE_URL = os.getenv("CORE_SERVICE_URL", "http://127.0.0.1:8001")
CORE_TIMEOUT = int(os.getenv("CORE_TIMEOUT", "120"))

# API mode (openai or ollama)
API_MODE = os.getenv("API_MODE", "ollama").lower()

# Create FastAPI app
app = FastAPI(
    title="RAG API Proxy",
    description=f"Lightweight proxy for RAG system ({'OpenAI' if API_MODE == 'openai' else 'Ollama'} mode)",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    api_mode: str
    core_service: str
    core_healthy: bool


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    # Check if core service is healthy
    core_healthy = False
    try:
        response = requests.get(
            f"{CORE_SERVICE_URL}/health",
            timeout=5,
        )
        core_healthy = response.status_code == 200
    except Exception as e:
        logger.warning(f"Core service health check failed: {e}")

    return HealthResponse(
        status="healthy" if core_healthy else "degraded",
        api_mode=API_MODE,
        core_service=CORE_SERVICE_URL,
        core_healthy=core_healthy,
    )


@app.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint."""
    if API_MODE == "openai":
        return {
            "message": "RAG API Proxy - OpenAI-compatible endpoint",
            "version": "1.0.0",
            "api_mode": "openai",
            "core_service": CORE_SERVICE_URL,
            "endpoints": {
                "models": "GET /v1/models",
                "chat_completions": "POST /v1/chat/completions",
                "responses": "POST /v1/responses",
                "embeddings": "POST /v1/embeddings",
                "files": "POST /v1/files",
                "health": "GET /health",
            },
        }
    else:
        return {
            "message": "RAG API Proxy - Ollama-compatible endpoint",
            "version": "1.0.0",
            "api_mode": "ollama",
            "core_service": CORE_SERVICE_URL,
            "endpoints": {
                "generate": "POST /api/generate",
                "chat": "POST /api/chat",
                "embeddings": "POST /api/embeddings",
                "tags": "GET /api/tags",
                "version": "GET /api/version",
                "health": "GET /health",
            },
        }


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_all(path: str, request: Request) -> JSONResponse:
    """Proxy all requests to core service.

    This catch-all route forwards all requests to the core service,
    preserving headers, query params, and body.
    """
    # Build target URL
    target_url = f"{CORE_SERVICE_URL}/{path}"

    # Get query parameters
    query_params = dict(request.query_params)

    # Get headers (exclude host and content-length which will be auto-generated)
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in ("host", "content-length")
    }

    # Get body
    try:
        body = await request.body()
    except Exception:
        body = None

    # Forward request to core service
    try:
        response = requests.request(
            method=request.method,
            url=target_url,
            params=query_params,
            headers=headers,
            data=body,
            timeout=CORE_TIMEOUT,
            stream=False,  # We don't support streaming yet
        )

        # Return response
        return JSONResponse(
            content=response.json() if response.content else {},
            status_code=response.status_code,
            headers={
                key: value
                for key, value in response.headers.items()
                if key.lower() not in ("content-encoding", "content-length", "transfer-encoding")
            },
        )

    except requests.exceptions.Timeout:
        logger.error(f"Core service timeout for {request.method} {path}")
        raise HTTPException(
            status_code=504,
            detail={
                "error": {
                    "message": "Core service timeout",
                    "type": "gateway_timeout",
                    "code": "timeout",
                }
            },
        )
    except requests.exceptions.ConnectionError:
        logger.error(f"Core service connection error for {request.method} {path}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "message": "Core service unavailable",
                    "type": "service_unavailable",
                    "code": "connection_error",
                }
            },
        )
    except Exception as e:
        logger.error(f"Proxy error for {request.method} {path}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": str(e),
                    "type": "internal_server_error",
                    "code": "proxy_error",
                }
            },
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.app_proxy:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
