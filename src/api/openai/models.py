"""Router for /v1/models endpoint."""
import logging
import time
import httpx
from typing import Optional
from fastapi import APIRouter
from src.api.models import ModelsResponse, Model

router = APIRouter(prefix="/v1", tags=["models"])
logger = logging.getLogger(__name__)

# Cache for LM Studio models (TTL: 60 seconds)
_models_cache: Optional[ModelsResponse] = None
_cache_timestamp: float = 0
_CACHE_TTL_SECONDS = 60


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """List available models.

    Returns a list of virtual models representing the RAG system
    plus any models exposed by LM Studio.

    Uses a 60-second cache to avoid querying LM Studio on every request.
    """
    global _models_cache, _cache_timestamp

    # Check cache validity
    now = time.time()
    if _models_cache and (now - _cache_timestamp) < _CACHE_TTL_SECONDS:
        logger.debug("Returning cached models (age: %.1fs)", now - _cache_timestamp)
        return _models_cache

    # Cache expired or doesn't exist, fetch fresh data
    items = []
    seen = set()

    # Always expose the virtual RAG model for clients.
    items.append(Model(id="rag-local", owned_by="rag-local"))
    seen.add("rag-local")

    # Try to fetch models from LM Studio
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get("http://127.0.0.1:1234/v1/models")
            if response.status_code == 200:
                lm_data = response.json()
                for model_obj in lm_data.get("data", []):
                    model_id = model_obj.get("id")
                    if model_id and model_id not in seen:
                        items.append(Model(
                            id=model_id,
                            owned_by=model_obj.get("owned_by", "lmstudio")
                        ))
                        seen.add(model_id)
                logger.info("Fetched %d models from LM Studio", len(lm_data.get("data", [])))
            else:
                logger.warning("LM Studio returned status %d", response.status_code)
    except Exception as e:
        logger.debug("Could not fetch models from LM Studio: %s", e)

    # Update cache
    response_obj = ModelsResponse(data=items)
    _models_cache = response_obj
    _cache_timestamp = now

    return response_obj
