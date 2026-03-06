# src/workflows/ingestion/wave_planner.py
"""
Wave planning and execution utilities for ingestion workflows.

This module provides:
- A WavePlan data structure.
- A WavePlanner for splitting candidates into waves based on size/count heuristics.
- A CallbackWaveOrchestrator that executes waves delegating work to a callback.

Note (2026-03-06): WaveOrchestratorStrategy (Protocol) and WaveOrchestrator were
removed. They defined a 3-phase contract (preprocess/embedding/upsert per wave)
that was never implemented. The orchestrator already owns phase logic and only
needs the partitioning utility, which CallbackWaveOrchestrator provides.
The original design intent — running all 3 phases inside each wave to bound
peak RAM — was evaluated and deemed unnecessary: AdaptiveWorkerController and
IngestQueue already mitigate the same problem via different paths. If future
datasets cause measurable RAM saturation that those mechanisms cannot handle,
revisit implementing a phase-internal wave strategy at that point.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class WavePlan:
    """
    Represents a single wave execution plan.

    Attributes:
        wave_id: A stable identifier for the wave, e.g. "wave_001".
        candidates: The items to be processed in this wave.
        metadata: Optional metadata about the wave (counts, size estimates, etc.).
    """

    wave_id: str
    candidates: List[Any]
    metadata: Dict[str, Any]


class WavePlanner:
    """
    Plans waves for ingestion based on simple heuristics.

    The current planner groups candidates into waves using target thresholds.
    """

    def __init__(
        self,
        target_files_per_wave: int = 100,
        max_waves: Optional[int] = None,
    ) -> None:
        """
        Initialize the WavePlanner.

        Args:
            target_files_per_wave: Desired number of candidates per wave.
            max_waves: Optional cap on number of waves.
        """
        if target_files_per_wave <= 0:
            raise ValueError("target_files_per_wave must be > 0")

        self._target_files_per_wave = target_files_per_wave
        self._max_waves = max_waves

    def plan(self, candidates: List[Any]) -> List[WavePlan]:
        """
        Split candidates into WavePlan objects.

        Args:
            candidates: Candidate items to process.

        Returns:
            A list of WavePlan objects.
        """
        if not candidates:
            return []

        waves: List[WavePlan] = []
        current: List[Any] = []

        for candidate in candidates:
            current.append(candidate)
            if len(current) >= self._target_files_per_wave:
                waves.append(self._build_wave_plan(waves_count=len(waves), candidates=current))
                current = []

                if self._max_waves is not None and len(waves) >= self._max_waves:
                    break

        if current and (self._max_waves is None or len(waves) < self._max_waves):
            waves.append(self._build_wave_plan(waves_count=len(waves), candidates=current))

        return waves

    def _build_wave_plan(self, waves_count: int, candidates: List[Any]) -> WavePlan:
        """
        Build a WavePlan for the given candidates.

        Args:
            waves_count: Number of waves already built.
            candidates: Candidates for this wave.

        Returns:
            A WavePlan instance.
        """
        wave_id = f"wave_{waves_count + 1:03d}"
        metadata: Dict[str, Any] = {
            "files_count": len(candidates),
        }
        return WavePlan(wave_id=wave_id, candidates=list(candidates), metadata=metadata)


class CallbackWaveOrchestrator:
    """Execute ingestion work in waves using a callback.

    This orchestrator exists to support the ingestion workflow in
    `src/workflows/ingestion/orchestrator.py`, which already owns the phase
    logic and only needs a utility to split candidates into stable waves.

    Returns:
        Dict with successful_waves, failed_waves, total_waves, wave_summaries.
    """

    def __init__(
        self,
        planner: Optional[WavePlanner] = None,
    ) -> None:
        """Initialize the callback-based orchestrator.

        Args:
            planner: Optional planner. If omitted, a default WavePlanner is used.
        """
        self._planner = planner or WavePlanner()

    def execute_waves(
        self,
        candidates: List[Any],
        process_callback: Callable[[List[Any]], Any],
    ) -> Dict[str, Any]:
        """Plan and execute waves for the given candidates.

        Args:
            candidates: The items to be processed.
            process_callback: A callable that processes a single wave.

        Returns:
            A dictionary containing per-wave summaries and success/failure counts.
        """
        wave_plans = self._planner.plan(list(candidates))
        wave_summaries: List[Dict[str, Any]] = []

        successful_waves = 0
        failed_waves = 0

        for wave_index, wave_plan in enumerate(wave_plans, start=1):
            try:
                result = process_callback(list(wave_plan.candidates))
                wave_summaries.append(
                    {
                        "wave_id": wave_plan.wave_id,
                        "index": wave_index,
                        "count": len(wave_plan.candidates),
                        "metadata": dict(wave_plan.metadata),
                        "result": result,
                        "error": None,
                    }
                )
                successful_waves += 1
            except Exception as exc:  # noqa: BLE001
                wave_summaries.append(
                    {
                        "wave_id": wave_plan.wave_id,
                        "index": wave_index,
                        "count": len(wave_plan.candidates),
                        "metadata": dict(wave_plan.metadata),
                        "result": None,
                        "error": f"{exc.__class__.__name__}: {exc}",
                    }
                )
                failed_waves += 1

        return {
            "successful_waves": successful_waves,
            "failed_waves": failed_waves,
            "total_waves": len(wave_plans),
            "wave_summaries": wave_summaries,
        }


def create_default_wave_orchestrator() -> CallbackWaveOrchestrator:
    """Create a default callback-based wave orchestrator."""
    return CallbackWaveOrchestrator()
