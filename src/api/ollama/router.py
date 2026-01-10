"""Router for Ollama-like core endpoints."""
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from src.api.models_ollama import (
    OllamaGenerateRequest,
    OllamaGenerateResponse,
    OllamaChatRequest,
    OllamaChatResponse,
    OllamaEmbeddingsRequest,
    OllamaEmbeddingsResponse,
    OllamaPullRequest,
    OllamaTagsResponse,
    OllamaTagModel,
    OllamaMessage,
)
import src.settings as settings
from src.api.middleware.thread_manager import get_thread_id, get_user_id
from src.rag.models import list_models
from src.rag.pipeline.rag_orchestrator import RAGOrchestrator

router = APIRouter(prefix="/api", tags=["ollama"])


async def get_rag_orchestrator() -> RAGOrchestrator:
    """Dependency injection for RAG orchestrator."""
    raise HTTPException(status_code=500, detail="RAG orchestrator not initialized")


async def get_embedding_service():
    """Dependency injection for embedding service."""
    raise HTTPException(status_code=500, detail="Embedding service not initialized")


async def get_chat_memory_manager():
    """Dependency injection for ChatMemory manager."""
    raise HTTPException(status_code=500, detail="ChatMemory manager not initialized")


async def get_snapshot_scheduler():
    """Dependency injection for snapshot scheduler."""
    raise HTTPException(status_code=500, detail="Snapshot scheduler not initialized")


def _resolve_generation_params(options) -> Dict[str, Any]:
    if options is None:
        return {
            "temperature": settings.RAG_DEFAULT_TEMPERATURE,
            "top_k": None,
            "max_tokens": settings.RAG_DEFAULT_MAX_TOKENS
        }

    max_tokens = options.max_tokens or options.num_predict or settings.RAG_DEFAULT_MAX_TOKENS
    return {
        "temperature": options.temperature if options.temperature is not None else settings.RAG_DEFAULT_TEMPERATURE,
        "top_k": options.top_k,
        "max_tokens": max_tokens,
    }


@router.post("/generate", response_model=OllamaGenerateResponse)
async def generate(
    request: OllamaGenerateRequest,
    rag: RAGOrchestrator = Depends(get_rag_orchestrator),
    thread_id: str = Depends(get_thread_id),
) -> OllamaGenerateResponse:
    if request.stream:
        raise HTTPException(status_code=501, detail="Streaming is not supported.")
    rag_options = request.rag
    options = _resolve_generation_params(request.options)
    use_rag = True if rag_options is None or rag_options.enabled is None else rag_options.enabled
    include_sources = True if rag_options is None or rag_options.include_sources is None else rag_options.include_sources
    filters = None if rag_options is None else rag_options.filters

    if use_rag:
        result = rag.query(
            question=request.prompt,
            top_k=options["top_k"],
            filters=filters,
            temperature=options["temperature"],
            max_tokens=options["max_tokens"],
            system_prompt=request.system,
            model=request.model,
            thread_id=thread_id,
        )
        sources = result.get("sources", []) if include_sources else None
        return OllamaGenerateResponse(
            model=request.model,
            response=result["answer"],
            sources=sources,
        )

    messages = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    messages.append({"role": "user", "content": request.prompt})
    response_text = rag.chat_service.chat(
        messages=messages,
        temperature=options["temperature"],
        max_tokens=options["max_tokens"],
        model=request.model,
    )
    return OllamaGenerateResponse(model=request.model, response=response_text, sources=None)


@router.post("/chat", response_model=OllamaChatResponse)
async def chat(
    request: OllamaChatRequest,
    rag: RAGOrchestrator = Depends(get_rag_orchestrator),
    user_id: str = Depends(get_user_id),
    thread_id: str = Depends(get_thread_id),
    chat_memory=Depends(get_chat_memory_manager),
    scheduler=Depends(get_snapshot_scheduler),
) -> OllamaChatResponse:
    """Chat endpoint with automatic snapshot creation every 24h.

    Automatically creates ChatMemory snapshots every 24 hours to enable
    cross-chat retrieval from past conversations.
    """
    rag_options = request.rag
    options = _resolve_generation_params(request.options)
    use_rag = True if rag_options is None or rag_options.enabled is None else rag_options.enabled
    include_sources = True if rag_options is None or rag_options.include_sources is None else rag_options.include_sources
    filters = None if rag_options is None else rag_options.filters

    if use_rag:
        question = _extract_question_from_messages(request.messages)
        conversation_history = [m.dict() for m in request.messages]
        result = rag.query(
            question=question,
            top_k=options["top_k"],
            filters=filters,
            temperature=options["temperature"],
            max_tokens=options["max_tokens"],
            model=request.model,
            user_id=user_id,
            conversation_history=conversation_history,
            thread_id=thread_id,
        )
        sources = result.get("sources", []) if include_sources else None
        response = OllamaChatResponse(
            model=request.model,
            message=OllamaMessage(role="assistant", content=result["answer"]),
            sources=sources,
        )
    else:
        response_text = rag.chat_service.chat(
            messages=[m.dict() for m in request.messages],
            temperature=options["temperature"],
            max_tokens=options["max_tokens"],
            model=request.model,
        )
        response = OllamaChatResponse(
            model=request.model,
            message=OllamaMessage(role="assistant", content=response_text),
            sources=None,
        )

    try:
        if scheduler.should_create_snapshot(thread_id):
            from src.memory.core.state import create_initial_state
            from src.memory.snapshot import create_snapshot

            state = create_initial_state(user_id, thread_id)
            state["messages"] = [m.dict() for m in request.messages]
            state["messages"].append({
                "role": "assistant",
                "content": response.message.content
            })

            snapshot = create_snapshot(
                state=state,
                user_id=user_id,
                thread_id=thread_id,
                ttl_days=30,
            )
            success = chat_memory.persistence.save_snapshot(snapshot)

            if success:
                scheduler.mark_snapshot_created(thread_id)
                from src.rag.audit import get_logger
                log = get_logger(__name__)
                log.info(
                    "Auto-created snapshot for thread %s (%d messages, %d keywords)",
                    thread_id[:16],
                    len(state["messages"]),
                    len(snapshot.keywords)
                )
    except Exception as e:
        from src.rag.audit import get_logger
        log = get_logger(__name__)
        log.warning("Failed to auto-create snapshot for thread %s: %s", thread_id[:16], e)

    return response


@router.post("/embeddings", response_model=OllamaEmbeddingsResponse)
async def embeddings(
    request: OllamaEmbeddingsRequest,
    embed_service=Depends(get_embedding_service),
) -> OllamaEmbeddingsResponse:
    inputs = request.input if isinstance(request.input, list) else [request.input]
    if len(inputs) == 1:
        vectors = [embed_service.generate(inputs[0])]
    else:
        vectors = embed_service.generate_batch(inputs)
    return OllamaEmbeddingsResponse(model=request.model, embeddings=vectors)


@router.post("/pull")
async def pull(_: OllamaPullRequest):
    raise HTTPException(status_code=501, detail="Pull is not supported by this backend.")


@router.get("/tags", response_model=OllamaTagsResponse)
async def tags() -> OllamaTagsResponse:
    base_url = settings.OPENAI_API_BASE if hasattr(settings, "OPENAI_API_BASE") else "http://127.0.0.1:1234/v1"
    models = list_models(base_url)
    items: List[OllamaTagModel] = []
    for m in models:
        model_id = m.get("id") or m.get("name")
        if not model_id:
            continue

        items.append(
            OllamaTagModel(
                name=model_id,
                model=model_id,
                size=0,
                digest=f"sha256:{model_id[:16]}",
                details={
                    "family": "lmstudio",
                    "format": "gguf",
                    "parameter_size": "unknown",
                },
            )
        )

        if ':' not in model_id:
            items.append(
                OllamaTagModel(
                    name=f"{model_id}:latest",
                    model=f"{model_id}:latest",
                    size=0,
                    digest=f"sha256:{model_id[:16]}",
                    details={
                        "family": "lmstudio",
                        "format": "gguf",
                        "parameter_size": "unknown",
                    },
                )
            )

    if not items:
        items.append(
            OllamaTagModel(
                name="rag-default",
                model="rag-default",
                size=0,
                digest="sha256:ragdefault0000",
                details={"family": "rag", "format": "gguf", "parameter_size": "unknown"},
            )
        )

    return OllamaTagsResponse(models=items)


@router.get("/version")
async def version() -> Dict[str, str]:
    """Return Ollama API version information."""
    return {"version": "0.1.0"}


@router.get("/ps")
async def list_running_models() -> Dict[str, List]:
    """List currently running models (Ollama compatibility).

    Returns empty list since we don't track running models like Ollama does.
    """
    return {"models": []}


@router.post("/show")
async def show_model(request: Dict[str, Any]) -> Dict[str, Any]:
    """Show model information (Ollama compatibility).

    OpenWebUI calls this to verify model existence and get details.
    """
    model_name = request.get("name", "")

    return {
        "modelfile": f"# Modelfile for {model_name}\nFROM {model_name}",
        "parameters": "",
        "template": "{{ .Prompt }}",
        "details": {
            "parent_model": "",
            "format": "gguf",
            "family": "llama",
            "families": ["llama"],
            "parameter_size": "unknown",
            "quantization_level": "Q4_0"
        },
        "model_info": {
            "general.architecture": "llama",
            "general.file_type": 2,
            "general.parameter_count": 0,
            "general.quantization_version": 2
        }
    }


def _extract_question_from_messages(messages: List[OllamaMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return "\n".join(msg.content for msg in messages)

@router.post("/chat/memory", response_model=OllamaChatResponse)
async def chat_with_memory(
    request: OllamaChatRequest,
    thread_id: str = Depends(get_thread_id),
    user_id: str = Depends(get_user_id),
    rag: RAGOrchestrator = Depends(get_rag_orchestrator),
) -> OllamaChatResponse:
    """Chat endpoint with conversation memory (experimental).

    Uses thread_id from X-Thread-ID header to maintain conversation state.
    State includes message history, tool memory, and compressed summaries.
    """
    from src.memory.helpers import (
        load_or_create_state,
        save_state,
        should_compress_state,
        compress_and_update_state,
        build_llm_context,
    )
    
    if request.stream:
        raise HTTPException(status_code=501, detail="Streaming not supported with memory")
    
    state = load_or_create_state(user_id, thread_id)
    
    question = _extract_question_from_messages(request.messages)
    
    rag_options = request.rag
    options = _resolve_generation_params(request.options)
    use_rag = True if rag_options is None or rag_options.enabled is None else rag_options.enabled
    filters = None if rag_options is None else rag_options.filters
    
    rag_results = None
    if use_rag:
        result = rag.query(
            question=question,
            top_k=options["top_k"],
            filters=filters,
            temperature=options["temperature"],
            max_tokens=options["max_tokens"],
            model=request.model,
            thread_id=thread_id,
        )
        answer = result["answer"]
        rag_results = result.get("sources", [])
    else:
        context = build_llm_context(state, question, rag_results)

        answer = rag.chat_service.chat(
            messages=[{"role": "user", "content": context}],
            temperature=options["temperature"],
            max_tokens=options["max_tokens"],
            model=request.model,
        )
    
    state["messages"].append({"role": "user", "content": question})
    state["messages"].append({"role": "assistant", "content": answer})
    
    if should_compress_state(state):
        state = compress_and_update_state(state)
    
    save_state(state, thread_id)
    
    return OllamaChatResponse(
        model=request.model,
        message=OllamaMessage(role="assistant", content=answer),
        sources=rag_results if use_rag else None,
    )
