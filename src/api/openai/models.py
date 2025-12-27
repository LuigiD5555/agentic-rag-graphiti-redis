"""Router for /v1/models endpoint."""
from fastapi import APIRouter
from src.api.models import ModelsResponse, Model

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """List available models.

    Returns a list of virtual models representing the RAG system
    and the underlying LM Studio model.
    """
    models = [
        Model(
            id="rag-local",
            owned_by="rag-local",
        ),
        Model(
            id="lmstudio-liquidai",
            owned_by="lmstudio",
        ),
        Model(
            id="text-embedding-ada-002",
            owned_by="lmstudio",
        ),
    ]

    return ModelsResponse(data=models)