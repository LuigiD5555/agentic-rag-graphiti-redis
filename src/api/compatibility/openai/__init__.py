"""OpenAI-compatible API routers."""
from .chat import router as chat_router
from .models import router as models_router
from .responses import router as responses_router
from .embeddings import router as embeddings_router

__all__ = [
    "chat_router",
    "models_router",
    "responses_router",
    "embeddings_router",
]
