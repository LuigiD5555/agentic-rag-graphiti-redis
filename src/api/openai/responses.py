"""Router for /v1/responses endpoint (modern OpenAI API)."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from src.api.models import (
    ResponseRequest,
    ResponseObject,
    ResponseOutput,
    ResponseMetadata,
    Usage,
    Source,
)
from src.rag.pipeline.rag_orchestrator import RAGOrchestrator
from src.api.middleware.thread_manager import get_thread_id

router = APIRouter(prefix="/v1", tags=["responses"])


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (1 token ~= 4 chars)."""
    return len(text) // 4


def _extract_text_from_input(input_data) -> str:
    """Extract text from input (can be string or list of ResponseInput)."""
    if isinstance(input_data, str):
        return input_data

    # List of ResponseInput objects
    texts = []
    for item in input_data:
        if isinstance(item, dict) and "text" in item:
            texts.append(item["text"])
        elif hasattr(item, "text"):
            texts.append(item.text)

    return "\n".join(texts)


async def get_rag_orchestrator() -> RAGOrchestrator:
    """Dependency injection for RAG orchestrator."""
    raise HTTPException(status_code=500, detail="RAG orchestrator not initialized")


@router.post("/responses", response_model=ResponseObject)
async def create_response(
    request: ResponseRequest,
    rag: RAGOrchestrator = Depends(get_rag_orchestrator),
    thread_id: str = Depends(get_thread_id),
) -> ResponseObject:
    """Create a response using the RAG system (modern endpoint).

    This is the modern OpenAI API endpoint for generating responses.
    It supports advanced features like metadata and structured outputs.

    Args:
        request: Response request with input and parameters.
        rag: RAG orchestrator instance (injected).

    Returns:
        Response object with answer, sources, and metadata.
    """
    # Extract text from input
    question = _extract_text_from_input(request.input)

    # Execute RAG query
    try:
        result = rag.query(
            question=question,
            top_k=request.top_k,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            thread_id=thread_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG query failed: {str(e)}")

    answer = result["answer"]

    # Estimate token usage
    prompt_tokens = _estimate_tokens(question)
    completion_tokens = _estimate_tokens(answer)

    # Build metadata with sources
    sources = [
        Source(path=src["path"], relevance_score=src["relevance_score"])
        for src in result.get("sources", [])
    ]

    metadata = ResponseMetadata(
        retrieved_count=result["metadata"]["retrieved_count"],
        sources=sources,
        query=question,
        temperature=request.temperature or 0.7,
        max_tokens=request.max_tokens or 1024,
    )

    # Build response
    response = ResponseObject(
        id=f"resp-{uuid.uuid4().hex[:24]}",
        model=request.model,
        output=[
            ResponseOutput(
                type="text",
                text=answer,
            )
        ],
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        metadata=metadata,
    )

    return response


@router.get("/responses/{response_id}", response_model=ResponseObject)
async def get_response(response_id: str) -> ResponseObject:
    """Get a previously created response by ID.

    This endpoint allows retrieving cached responses.
    Currently not implemented (returns 501 Not Implemented).
    """
    raise HTTPException(
        status_code=501,
        detail="Response retrieval not yet implemented. Consider using a cache service.",
    )


@router.delete("/responses/{response_id}")
async def delete_response(response_id: str) -> dict:
    """Delete a response by ID.

    Currently not implemented (returns 501 Not Implemented).
    """
    raise HTTPException(
        status_code=501,
        detail="Response deletion not yet implemented.",
    )