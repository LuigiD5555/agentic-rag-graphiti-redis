"""
Base plugin interface for SWARM RAG.

Every specialist and core plugin must subclass BasePlugin and implement `run`.
The plugin declares its contract (name, capabilities, inputs, outputs,
dependencies) so the Planner can build a correct execution DAG without
having to inspect each plugin's source code.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState


class BasePlugin(ABC):
    """Abstract base for all SWARM RAG plugins."""

    # --- Contract (must be overridden as class attributes) ---
    name: str
    capabilities: list[str] = []
    inputs: list[str] = []
    outputs: list[str] = []
    dependencies: list[str] = []

    @abstractmethod
    async def run(self, state: BlackboardState) -> BlackboardState:
        """Execute plugin logic and return updated state."""
        ...

    def is_applicable(self, state: BlackboardState) -> bool:
        """
        Return True if this plugin should run for the given state.
        Override in plugins that have their own activation logic.
        By default every plugin is applicable.
        """
        return True

    async def _timed_run(self, state: BlackboardState) -> BlackboardState:
        """Wrapper that records plugin latency in state.latency_ms."""
        t0 = time.monotonic()
        state = await self.run(state)
        elapsed = round((time.monotonic() - t0) * 1000, 2)
        state.latency_ms[self.name] = elapsed
        state.execution_trace.append({"plugin": self.name, "latency_ms": elapsed})
        return state
