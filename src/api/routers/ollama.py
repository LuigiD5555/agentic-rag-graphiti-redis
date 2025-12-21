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
from src.rag.models import list_models
from src.rag.pipeline.rag_orchestrator import RAGOrchestrator

router = APIRouter(prefix="/api", tags=["ollama"])


async def get_rag_orchestrator() -> RAGOrchestrator:
    """Dependency injection for RAG orchestrator."""
    raise HTTPException(status_code=500, detail="RAG orchestrator not initialized")


async def get_embedding_service():
    """Dependency injection for embedding service."""
    raise HTTPException(status_code=500, detail="Embedding service not initialized")


def _resolve_generation_params(options) -> Dict[str, Any]:
    if options is None:
        return {"temperature": 0.7, "top_k": None, "max_tokens": 1024}

    max_tokens = options.max_tokens or options.num_predict or 1024
    return {
        "temperature": options.temperature if options.temperature is not None else 0.7,
        "top_k": options.top_k,
        "max_tokens": max_tokens,
    }


@router.post("/generate", response_model=OllamaGenerateResponse)
async def generate(
    request: OllamaGenerateRequest,
    rag: RAGOrchestrator = Depends(get_rag_orchestrator),
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
    )
    return OllamaGenerateResponse(model=request.model, response=response_text, sources=None)


@router.post("/chat", response_model=OllamaChatResponse)
async def chat(
    request: OllamaChatRequest,
    rag: RAGOrchestrator = Depends(get_rag_orchestrator),
) -> OllamaChatResponse:
    if request.stream:
        raise HTTPException(status_code=501, detail="Streaming is not supported.")
    rag_options = request.rag
    options = _resolve_generation_params(request.options)
    use_rag = True if rag_options is None or rag_options.enabled is None else rag_options.enabled
    include_sources = True if rag_options is None or rag_options.include_sources is None else rag_options.include_sources
    filters = None if rag_options is None else rag_options.filters

    if use_rag:
        question = _extract_question_from_messages(request.messages)
        result = rag.query(
            question=question,
            top_k=options["top_k"],
            filters=filters,
            temperature=options["temperature"],
            max_tokens=options["max_tokens"],
        )
        sources = result.get("sources", []) if include_sources else None
        return OllamaChatResponse(
            model=request.model,
            message=OllamaMessage(role="assistant", content=result["answer"]),
            sources=sources,
        )

    response_text = rag.chat_service.chat(
        messages=[m.dict() for m in request.messages],
        temperature=options["temperature"],
        max_tokens=options["max_tokens"],
    )
    return OllamaChatResponse(
        model=request.model,
        message=OllamaMessage(role="assistant", content=response_text),
        sources=None,
    )


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
    base_url = os.getenv("OPENAI_API_BASE", "http://127.0.0.1:1234/v1")
    models = list_models(base_url)
    items: List[OllamaTagModel] = []
    for m in models:
        model_id = m.get("id") or m.get("name")
        if not model_id:
            continue
        items.append(OllamaTagModel(name=model_id, details={"family": "lmstudio"}))

    if not items:
        items.append(OllamaTagModel(name="rag-default", details={"family": "rag"}))

    return OllamaTagsResponse(models=items)


def _extract_question_from_messages(messages: List[OllamaMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return "\n".join(msg.content for msg in messages)
