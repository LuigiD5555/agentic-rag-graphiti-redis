"""API router factory registry for OpenAI/Ollama-compatible HTTP adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

from fastapi import APIRouter, FastAPI


DependencyProvider = Callable[[], object]
ApiRouterFactory = Callable[[object], "ApiRouterFamily"]

_registry: dict[str, ApiRouterFactory] = {}


@dataclass(frozen=True)
class DependencyOverrideSpec:
    dependency: Callable[..., object]
    provider_key: str


@dataclass
class ApiRouterFamily:
    name: str
    routers: list[APIRouter]
    overrides: list[DependencyOverrideSpec] = field(default_factory=list)

    def apply(self, app: FastAPI, providers: Mapping[str, DependencyProvider]) -> None:
        """Apply routers and dependency overrides to the FastAPI app."""
        for spec in self.overrides:
            provider = providers.get(spec.provider_key)
            if provider is None:
                raise KeyError(f"Missing dependency provider for '{spec.provider_key}'")
            app.dependency_overrides[spec.dependency] = provider
        for router in self.routers:
            app.include_router(router)


def register_api_router_family(name: str, factory: ApiRouterFactory) -> None:
    normalized = (name or "").strip().lower()
    if not normalized:
        raise ValueError("Router family name must be non-empty")
    if not callable(factory):
        raise TypeError("Router family factory must be callable")
    _registry[normalized] = factory


def get_api_router_family(config: object) -> ApiRouterFamily:
    mode = (getattr(config, "API_MODE", "") or "openai").strip().lower()
    if mode not in _registry:
        available = ", ".join(sorted(_registry.keys())) or "<none>"
        raise KeyError(f"Unknown API_MODE '{mode}'. Available: {available}")
    family = _registry[mode](config)
    return family


def _build_openai_family(config: object) -> ApiRouterFamily:
    _ = config
    from src.api.openai import (
        chat_router,
        models_router,
        responses_router,
        embeddings_router,
    )
    from src.api.openai.chat import get_rag_orchestrator as openai_chat_get_rag
    from src.api.openai.responses import get_rag_orchestrator as openai_responses_get_rag
    from src.api.openai.embeddings import get_embedding_service as openai_get_embedding

    overrides = [
        DependencyOverrideSpec(openai_chat_get_rag, "rag"),
        DependencyOverrideSpec(openai_responses_get_rag, "rag"),
        DependencyOverrideSpec(openai_get_embedding, "embedding"),
    ]
    routers = [models_router, chat_router, responses_router, embeddings_router]
    return ApiRouterFamily(name="openai", routers=routers, overrides=overrides)


def _build_ollama_family(config: object) -> ApiRouterFamily:
    _ = config
    from src.api.ollama import ollama_router
    from src.api.ollama.router import get_rag_orchestrator as ollama_get_rag
    from src.api.ollama.router import get_embedding_service as ollama_get_embedding
    from src.api.ollama.router import get_chat_memory_manager as ollama_get_chat_memory
    from src.api.ollama.router import get_snapshot_scheduler as ollama_get_scheduler

    overrides = [
        DependencyOverrideSpec(ollama_get_rag, "rag"),
        DependencyOverrideSpec(ollama_get_embedding, "embedding"),
        DependencyOverrideSpec(ollama_get_chat_memory, "chat_memory"),
        DependencyOverrideSpec(ollama_get_scheduler, "snapshot_scheduler"),
    ]

    compat_router = APIRouter(prefix="/ollama")
    compat_router.include_router(ollama_router)

    routers = [ollama_router, compat_router]
    return ApiRouterFamily(name="ollama", routers=routers, overrides=overrides)


register_api_router_family("openai", _build_openai_family)
register_api_router_family("ollama", _build_ollama_family)


__all__ = [
    "ApiRouterFamily",
    "DependencyOverrideSpec",
    "get_api_router_family",
    "register_api_router_family",
]
