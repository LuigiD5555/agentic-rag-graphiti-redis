"""
BaseSpecialist — abstract base for all seq2seq and encoder specialists.

Differences from BasePlugin (which wraps retrieval/knowledge tools):
- Specialists transform information (rewrite, extract, rank) using ML models
- Models are loaded ONCE at class level (not per instance) via _load_model()
- Each subclass declares its HF model_id and implements _run_model()
- Graceful degradation: if model unavailable, _fallback() is called instead
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)


class BaseSpecialist(ABC):
    """Abstract base for SWARM RAG specialist transformers."""

    model_id: ClassVar[str] = ""          # HuggingFace model ID
    name: ClassVar[str] = ""              # unique specialist name
    _model: ClassVar[Optional[Any]] = None  # shared across instances
    _model_loaded: ClassVar[bool] = False

    @classmethod
    def load(cls) -> None:
        """Load the HF model once. Call at startup, not per query."""
        if cls._model_loaded:
            return
        try:
            cls._model = cls._load_model()
            cls._model_loaded = True
            logger.info("Specialist '%s' loaded model '%s'", cls.name, cls.model_id)
        except Exception as exc:
            logger.warning(
                "Specialist '%s' could not load model '%s': %s — will use fallback",
                cls.name, cls.model_id, exc,
            )
            cls._model_loaded = True  # prevent retry on every call

    @classmethod
    @abstractmethod
    def _load_model(cls) -> Any:
        """Load and return the HF model/pipeline. Called once."""
        ...

    @abstractmethod
    async def run(self, state: BlackboardState) -> BlackboardState:
        """Execute specialist logic and return updated state."""
        ...

    @abstractmethod
    def _fallback(self, state: BlackboardState) -> BlackboardState:
        """Return state unchanged when model is unavailable."""
        ...

    async def _run_in_executor(self, fn, *args) -> Any:
        """Run a synchronous HF call in a thread pool to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    def _record(self, state: BlackboardState, elapsed_ms: float) -> None:
        state.latency_ms[self.name] = elapsed_ms
        state.execution_trace.append({"specialist": self.name, "latency_ms": elapsed_ms})
