"""
Planner — builds an execution DAG from the active plugin list.

The DAG is represented as a list of phases, where each phase is a group
of plugin names that can run in parallel. Phases respect dependency order:
a plugin only appears in a phase after all its dependencies have been
scheduled in earlier phases.

Dependency information is read from PluginManager manifests.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Optional

from swarm_rag.core.plugin_manager import PluginManager

logger = logging.getLogger(__name__)

# Plugins that are always appended as terminal nodes regardless of dependencies
_TERMINAL_PLUGINS = {"slm_verbalizer"}


class CyclicDependencyError(Exception):
    pass


class Planner:
    def __init__(self, plugin_manager: PluginManager) -> None:
        self._pm = plugin_manager

    def build_dag(self, active_plugins: list[str]) -> list[list[str]]:
        """
        Build an ordered list of phases from the active plugin set.

        Returns: list[list[str]]
            Each inner list is a group of plugins safe to run in parallel.
            Example: [["math_understanding", "retrieval"], ["evidence_merger"], ["slm_verbalizer"]]
        """
        # Filter out terminal plugins — they are scheduled separately at the end
        working = [p for p in active_plugins if p not in _TERMINAL_PLUGINS]

        # Build in-degree map and adjacency list restricted to active plugins
        active_set = set(working)
        in_degree: dict[str, int] = {p: 0 for p in working}
        dependents: dict[str, list[str]] = defaultdict(list)

        for plugin in working:
            deps = self._pm.dependencies_of(plugin)
            for dep in deps:
                if dep not in active_set:
                    # Dependency not active — ignore (treat as satisfied)
                    continue
                in_degree[plugin] += 1
                dependents[dep].append(plugin)

        # Kahn's algorithm — topological sort with parallel grouping
        phases: list[list[str]] = []
        queue: deque[str] = deque(p for p, d in in_degree.items() if d == 0)
        remaining = len(working)

        while queue:
            phase = list(queue)
            queue.clear()
            phases.append(sorted(phase))  # sorted for determinism
            remaining -= len(phase)
            for plugin in phase:
                for dependent in dependents[plugin]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

        if remaining > 0:
            cycle_nodes = [p for p, d in in_degree.items() if d > 0]
            raise CyclicDependencyError(
                f"Cyclic dependency detected among plugins: {cycle_nodes}"
            )

        # Append terminal plugins as final phase
        terminal_active = [p for p in active_plugins if p in _TERMINAL_PLUGINS]
        if terminal_active:
            phases.append(sorted(terminal_active))

        logger.info("Planner built %d phases: %s", len(phases), phases)
        return phases
