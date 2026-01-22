# src/workflows/ingestion/wave_planner.py
"""
Wave planning and execution utilities for ingestion workflows.

This module provides:
- A WavePlan data structure.
- A WavePlanner for splitting candidates into waves based on size/count heuristics.
- A WaveOrchestrator that executes waves using a pluggable strategy.

The code is defensive about the strategy return types:
some phases may naturally return a list (e.g., list of processed records),
while other phases return dictionaries with structured metadata. The orchestrator
normalizes these results so downstream code can safely summarize progress.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence


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


class WaveOrchestratorStrategy(Protocol):
    """
    Strategy contract for executing ingestion phases.

    Implementations may return either:
    - dict: structured phase result
    - list/tuple/sequence: natural payload (e.g., processed items)
    """

    def preprocess_phase(self, candidates: List[Any], wave_id: str) -> Any:
        """Run wave-level preprocessing and return phase results."""
        raise NotImplementedError

    def embedding_phase(self, preprocessed: Any, wave_id: str) -> Any:
        """Run wave-level embedding and return phase results."""
        raise NotImplementedError

    def upsert_phase(self, embedded: Any, wave_id: str) -> Any:
        """Run wave-level upsert and return phase results."""
        raise NotImplementedError


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


class WaveOrchestrator:
    """
    Executes waves using a given strategy and returns a structured summary.
    """

    def __init__(self, strategy: WaveOrchestratorStrategy) -> None:
        """
        Initialize the orchestrator.

        Args:
            strategy: The wave execution strategy.
        """
        self._strategy = strategy

    def execute_waves(self, wave_plans: List[WavePlan]) -> Dict[str, Any]:
        """
        Execute all waves and return a summary.

        This method is intentionally defensive about strategy return types.

        Args:
            wave_plans: Planned waves.

        Returns:
            A dictionary summary containing per-wave results and aggregates.
        """
        wave_results: List[Dict[str, Any]] = []
        for wave_index, wave_plan in enumerate(wave_plans, start=1):
            try:
                preprocess_result = self._strategy.preprocess_phase(
                    candidates=wave_plan.candidates,
                    wave_id=wave_plan.wave_id,
                )
                normalized_preprocess = self._normalize_phase_result(preprocess_result)

                embedding_result = self._strategy.embedding_phase(
                    preprocessed=normalized_preprocess,
                    wave_id=wave_plan.wave_id,
                )
                normalized_embedding = self._normalize_phase_result(embedding_result)

                upsert_result = self._strategy.upsert_phase(
                    embedded=normalized_embedding,
                    wave_id=wave_plan.wave_id,
                )
                normalized_upsert = self._normalize_phase_result(upsert_result)

                wave_results.append(
                    {
                        "wave_id": wave_plan.wave_id,
                        "index": wave_index,
                        "metadata": wave_plan.metadata,
                        "preprocess": normalized_preprocess,
                        "embedding": normalized_embedding,
                        "upsert": normalized_upsert,
                        "error": None,
                    }
                )
            except ValueError as exc:
                wave_results.append(
                    {
                        "wave_id": wave_plan.wave_id,
                        "index": wave_index,
                        "metadata": wave_plan.metadata,
                        "preprocess": {},
                        "embedding": {},
                        "upsert": {},
                        "error": f"ValueError: {exc}",
                    }
                )
            except RuntimeError as exc:
                wave_results.append(
                    {
                        "wave_id": wave_plan.wave_id,
                        "index": wave_index,
                        "metadata": wave_plan.metadata,
                        "preprocess": {},
                        "embedding": {},
                        "upsert": {},
                        "error": f"RuntimeError: {exc}",
                    }
                )

        total_files_processed = self._count_total_files_processed(wave_results)

        successful_waves = sum(1 for w in wave_results if w.get("error") is None)
        failed_waves = sum(1 for w in wave_results if w.get("error") is not None)

        return {
            "waves": wave_results,
            "total_waves": len(wave_results),
            "successful_waves": successful_waves,
            "failed_waves": failed_waves,
            "total_files_processed": total_files_processed,
        }

    def _normalize_phase_result(self, result: Any) -> Dict[str, Any]:
        """
        Normalize a phase result into a dictionary.

        Strategy phases are allowed to return lists/tuples/sequences naturally.
        We wrap those into {"payload": ...} so downstream summarization is safe.

        Args:
            result: Any phase result returned by the strategy.

        Returns:
            A dict representation of the phase result.
        """
        if result is None:
            return {}

        if isinstance(result, dict):
            return result

        # Natural list/tuple payload.
        if isinstance(result, (list, tuple)):
            return {"payload": list(result)}

        # Generic sequence (but not string/bytes).
        if isinstance(result, Sequence) and not isinstance(result, (str, bytes)):
            return {"payload": list(result)}

        return {"payload": result}

    def _count_total_files_processed(self, wave_results: List[Dict[str, Any]]) -> int:
        """
        Count the total files processed across waves.

        We try in this order:
        - explicit "files" list in preprocess/embedding/upsert dict
        - explicit "files_count" in wave metadata
        - length of "payload" if it's a list

        Args:
            wave_results: Per-wave results.

        Returns:
            Total processed files count estimate.
        """
        total = 0
        for wave in wave_results:
            if wave.get("error") is not None:
                continue

            # Prefer the most concrete signal available.
            phase_dicts = [
                wave.get("preprocess", {}),
                wave.get("embedding", {}),
                wave.get("upsert", {}),
            ]

            counted = False
            for phase_data in phase_dicts:
                phase_count = self._count_files_in_phase(phase_data)
                if phase_count is not None:
                    total += phase_count
                    counted = True
                    break

            if counted:
                continue

            metadata = wave.get("metadata", {})
            if isinstance(metadata, dict) and isinstance(metadata.get("files_count"), int):
                total += int(metadata["files_count"])

        return total

    def _count_files_in_phase(self, phase_data: Any) -> Optional[int]:
        """
        Try to infer a file count from a phase dictionary.

        Args:
            phase_data: Phase data.

        Returns:
            An integer count if it can be inferred, otherwise None.
        """
        if not isinstance(phase_data, dict):
            return None

        files_value = phase_data.get("files")
        if isinstance(files_value, list):
            return len(files_value)

        payload_value = phase_data.get("payload")
        if isinstance(payload_value, list):
            return len(payload_value)

        files_count_value = phase_data.get("files_count")
        if isinstance(files_count_value, int):
            return int(files_count_value)

        return None


def create_default_wave_orchestrator(strategy: WaveOrchestratorStrategy) -> WaveOrchestrator:
    """
    Factory function for creating a default WaveOrchestrator.

    Args:
        strategy: The wave execution strategy.

    Returns:
        A WaveOrchestrator instance.
    """
    return WaveOrchestrator(strategy=strategy)
