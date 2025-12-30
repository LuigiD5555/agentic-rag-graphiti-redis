"""Router for /v1/embeddings endpoint."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from src.api.models import EmbeddingRequest, EmbeddingResponse, Embedding, Usage
from src.rag.interfaces.embedding_interface import EmbeddingInterface

router = APIRouter(prefix="/v1", tags=["embeddings"])


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (1 token ~= 4 chars)."""
    return len(text) // 4


async def get_embedding_service() -> EmbeddingInterface:
    """Dependency injection for embedding service."""
    raise HTTPException(status_code=500, detail="Embedding service not initialized")


@router.post("/embeddings", response_model=EmbeddingResponse)
async def create_embeddings(
    request: EmbeddingRequest,
    embedding_service: EmbeddingInterface = Depends(get_embedding_service),
) -> EmbeddingResponse:
    """Create embeddings for the given input text(s).

    This endpoint is compatible with OpenAI's embeddings API.
    It converts text into vector representations for semantic search,
    clustering, or other downstream tasks.

    Args:
        request: Embedding request with input text(s).
        embedding_service: Embedding service instance (injected).

    Returns:
        Embedding response with vectors and usage information.
    """
    if isinstance(request.input, str):
        texts = [request.input]
    else:
        texts = request.input

    try:
        embeddings: List[List[float]] = []
        for text in texts:
            vector = embedding_service.generate(text)
            embeddings.append(vector)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding generation failed: {str(e)}")

    total_tokens = sum(_estimate_tokens(text) for text in texts)

    data = [
        Embedding(
            embedding=emb,
            index=idx,
        )
        for idx, emb in enumerate(embeddings)
    ]

    response = EmbeddingResponse(
        data=data,
        model=request.model,
        usage=Usage(
            prompt_tokens=total_tokens,
            completion_tokens=0,
            total_tokens=total_tokens,
        ),
    )

    return response
