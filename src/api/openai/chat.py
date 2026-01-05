"""Router for /v1/chat/completions endpoint (OpenAI-compatible)."""
import uuid
import json
import logging
import time
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
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


async def _stream_chat_completion(
    request: ChatCompletionRequest,
    rag: RAGOrchestrator,
    thread_id: str,
    user_id: str,
    answer: str,
    result: Dict[str, Any],
    selected_model: str,
):
    """Generate streaming response in OpenAI SSE format."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    # Use selected_model or fallback to avoid null/rag-local in stream
    model_name = selected_model or "gpt-3.5-turbo"

    # Send the answer content in chunks (simulate word-by-word streaming)
    created_timestamp = int(time.time())
    role_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created_timestamp,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant"},
                "finish_reason": None,
            }
        ],
    }
    yield f"data: {json.dumps(role_chunk)}\n\n"

    words = answer.split()
    for i, word in enumerate(words):
        chunk_content = word + (" " if i < len(words) - 1 else "")
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_timestamp,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": chunk_content},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n"

    # Send final chunk with finish_reason
    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created_timestamp,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    request: ChatCompletionRequest,
    http_request: Request,
    rag: RAGOrchestrator = Depends(get_rag_orchestrator),
    thread_id: str = Depends(get_thread_id),
    user_id: str = Depends(get_user_id),
):
    """Create a chat completion using the RAG system.

    This endpoint is compatible with OpenAI's chat completions API.
    It extracts the user's question from the messages, performs RAG retrieval,
    and generates a response. Supports both streaming and non-streaming modes.

    Args:
        request: Chat completion request with messages and parameters.
        rag: RAG orchestrator instance (injected).
        thread_id: Thread identifier (injected by middleware).
        user_id: User identifier (injected by middleware).

    Returns:
        Chat completion response with answer and usage information.
        If stream=true, returns a StreamingResponse with SSE format.
    """
    # Respect client streaming preference to avoid JSON parsing errors.
    state = load_or_create_state(user_id, thread_id)

    question = _extract_question_from_messages(request.messages)

    selected_model = request.model
    if not selected_model or selected_model == "rag-local":
        selected_model = None

    # Debug: Log conversation history length
    history_len = len(state.get("messages", []))
    logger.debug(f"Thread {thread_id[:8]}... has {history_len} messages in history")

    try:
        result = rag.query(
            question=question,
            top_k=request.top_k,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            thread_id=thread_id,
            model=selected_model,
            conversation_history=state["messages"],
        )
    except Exception as e:
        logger.error(f"RAG query failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"RAG query failed: {str(e)}")

    answer = result["answer"]

    if result.get("sources"):
        # Filter out sources with very low relevance (< 5%)
        import os
        relevant_sources = [src for src in result["sources"] if src['relevance_score'] >= 0.05]

        if relevant_sources:
            sources_text = "\n\n---\n**Fuentes consultadas:**\n"
            for idx, src in enumerate(relevant_sources, 1):
                path = src['path']
                score = src['relevance_score']

                # Extract filename and directory
                filename = os.path.basename(path)
                directory = os.path.dirname(path)

                # Convert score to percentage
                relevance_pct = score * 100

                # Format source with better readability (no emojis)
                sources_text += f"\n{idx}. {filename}\n"
                sources_text += f"   Ubicacion: {directory}/\n"
                sources_text += f"   Relevancia: {relevance_pct:.1f}%\n"

            answer += sources_text

    state["messages"].append({"role": "user", "content": question})
    state["messages"].append({"role": "assistant", "content": answer})

    if should_compress_state(state):
        logger.info(f"Compressing state for thread {thread_id[:8]}...")
        state = compress_and_update_state(state)

    save_state(state, thread_id)

    # Handle streaming response only when the client explicitly accepts SSE.
    accept_header = (http_request.headers.get("accept") or "").lower()
    stream_allowed = "text/event-stream" in accept_header
    if request.stream and not stream_allowed:
        logger.warning(
            "Streaming requested but client does not accept SSE; returning JSON response. "
            "accept=%s",
            accept_header,
        )

    if request.stream and stream_allowed:
        return StreamingResponse(
            _stream_chat_completion(request, rag, thread_id, user_id, answer, result, selected_model),
            media_type="text/event-stream",
        )

    # Handle non-streaming response
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

    logger.info(f"Sending response: {response.model_dump_json()[:500]}...")
    return response
