"""
Scheduler — executes the DAG produced by the Planner.

Each phase runs its plugins concurrently with asyncio.gather().
Phases execute sequentially so that later phases can consume outputs
written by earlier ones. The shared BlackboardState is merged after
each phase.

State merging strategy: last-writer-wins for scalar fields,
list fields are extended (deduplicated for primitive lists),
dict fields are shallowly merged.
"""
from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from typing import Optional

from experiments.swarm_rag.plugins.base_plugin import BasePlugin
from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)


class Scheduler:
    """
    Executes a DAG (list of phases) against a shared BlackboardState.

    Plugin errors in a phase are caught and logged; they do NOT abort
    subsequent phases — the system degrades gracefully.
    """

    def __init__(self, timeout_per_plugin: float = 30.0) -> None:
        """
        Args:
            timeout_per_plugin: Max seconds to wait for a single plugin run.
                                 Timed-out plugins are skipped with a warning.
        """
        self._timeout = timeout_per_plugin

    async def execute(
        self,
        phases: list[list[str]],
        plugin_map: dict[str, BasePlugin],
        state: BlackboardState,
    ) -> BlackboardState:
        """
        Run all phases sequentially, each phase's plugins in parallel.

        Args:
            phases:     Output of Planner.build_dag()
            plugin_map: name → BasePlugin instance
            state:      Initial BlackboardState

        Returns:
            Updated BlackboardState after all phases complete.
        """
        for phase_idx, phase in enumerate(phases):
            plugins_in_phase = [
                plugin_map[name] for name in phase if name in plugin_map
            ]
            skipped = [name for name in phase if name not in plugin_map]
            if skipped:
                logger.warning("Phase %d: plugins not registered — skipping: %s", phase_idx, skipped)

            if not plugins_in_phase:
                continue

            logger.info("Scheduler executing phase %d: %s", phase_idx, [p.name for p in plugins_in_phase])
            partial_states = await self._run_phase(plugins_in_phase, state)

            for partial in partial_states:
                if partial is not None:
                    state = self._merge_state(state, partial)

        return state

    async def _run_phase(
        self,
        plugins: list[BasePlugin],
        state: BlackboardState,
    ) -> list[Optional[BlackboardState]]:
        """Run all plugins in a phase concurrently."""
        tasks = [self._run_with_timeout(plugin, deepcopy(state)) for plugin in plugins]
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def _run_with_timeout(
        self,
        plugin: BasePlugin,
        state: BlackboardState,
    ) -> Optional[BlackboardState]:
        try:
            return await asyncio.wait_for(
                plugin._timed_run(state),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            logger.error("Plugin '%s' timed out after %.1fs", plugin.name, self._timeout)
            return None
        except Exception as exc:
            logger.error("Plugin '%s' raised an exception: %s", plugin.name, exc, exc_info=True)
            return None

    @staticmethod
    def _merge_state(base: BlackboardState, partial: BlackboardState) -> BlackboardState:
        """
        Merge partial state produced by one plugin into the accumulated base.

        Rules:
        - Scalar fields: partial wins if not None/empty
        - list fields: extend + deduplicate (for str lists); for list[dict] extend only
        - dict fields: shallow merge (partial keys overwrite base keys)
        - Nested Pydantic models: recursively apply same rules
        """
        base_data = base.model_dump()
        partial_data = partial.model_dump()

        merged = _deep_merge(base_data, partial_data)
        return BlackboardState(**merged)


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, override_val in override.items():
        base_val = base.get(key)

        if override_val is None:
            continue  # keep base value

        if isinstance(base_val, dict) and isinstance(override_val, dict):
            result[key] = _deep_merge(base_val, override_val)
        elif isinstance(base_val, list) and isinstance(override_val, list):
            # Extend: for primitive lists deduplicate; for dict lists just extend
            if base_val and isinstance(base_val[0], dict):
                # list[dict] — extend (dict items aren't hashable)
                seen_ids = {id(item) for item in base_val}
                result[key] = base_val + [i for i in override_val if i not in base_val]
            else:
                # list of primitives — union preserving order
                result[key] = list(dict.fromkeys(base_val + override_val))
        else:
            # Scalar: partial wins if it's a non-empty / non-default value
            if override_val not in (None, "", [], {}):
                result[key] = override_val
    return result
