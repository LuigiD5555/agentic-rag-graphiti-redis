"""Router for /v1/chat/completions endpoint (OpenAI-compatible)."""
import uuid
import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from src.api.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    ChatMessage,
    Usage,
)
from src.rag.pipeline.rag_orchestrator import RAGOrchestrator
from src.memory.helpers import (
    load_or_create_state,
    save_state,
    should_compress_state,
    compress_and_update_state,
)
from src.api.middleware.thread_manager import get_user_id, get_thread_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["chat"])


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (1 token ~= 4 chars)."""
    return len(text) // 4


def _extract_question_from_messages(messages: list) -> str:
    """Extract the user's question from chat messages.

    Takes the last user message as the question.
    """
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return "\n".join(msg.content for msg in messages)


async def get_rag_orchestrator() -> RAGOrchestrator:
    """Dependency injection for RAG orchestrator.

    This will be overridden in the main app to inject the actual instance.
    """
    raise HTTPException(status_code=500, detail="RAG orchestrator not initialized")


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    request: ChatCompletionRequest,
    rag: RAGOrchestrator = Depends(get_rag_orchestrator),
    thread_id: str = Depends(get_thread_id),
    user_id: str = Depends(get_user_id),
) -> ChatCompletionResponse:
    """Create a chat completion using the RAG system.

    This endpoint is compatible with OpenAI's chat completions API.
    It extracts the user's question from the messages, performs RAG retrieval,
    and generates a response.

    Args:
        request: Chat completion request with messages and parameters.
        rag: RAG orchestrator instance (injected).
        thread_id: Thread identifier (injected by middleware).
        user_id: User identifier (injected by middleware).

    Returns:
        Chat completion response with answer and usage information.
    """
    state = load_or_create_state(user_id, thread_id)

    question = _extract_question_from_messages(request.messages)

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

    if result.get("sources"):
        sources_text = "\n\nSources:\n" + "\n".join(
            f"- {src['path']} (score: {src['relevance_score']:.3f})"
            for src in result["sources"]
        )
        answer += sources_text

    state["messages"].append({"role": "user", "content": question})
    state["messages"].append({"role": "assistant", "content": answer})

    if should_compress_state(state):
        logger.info(f"Compressing state for thread {thread_id[:8]}...")
        state = compress_and_update_state(state)

    save_state(state, thread_id)

    prompt_text = "\n".join(msg.content for msg in request.messages)
    prompt_tokens = _estimate_tokens(prompt_text)
    completion_tokens = _estimate_tokens(answer)

    response = ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
        model=request.model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatMessage(
                    role="assistant",
                    content=answer,
                ),
                finish_reason="stop",
            )
        ],
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )

    return response
