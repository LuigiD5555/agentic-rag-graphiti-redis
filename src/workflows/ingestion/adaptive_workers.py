"""Adaptive worker count controller for ingestion pipeline.

Dynamically adjusts thread pool size based on RAM and CPU load,
using hysteresis to avoid thrashing when resources are near thresholds.
"""

import os
import time
from typing import Optional

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

from src import logger


class AdaptiveWorkerController:
    """Adjusts worker count between min and max based on system resources.

    Uses hysteresis: requires N consecutive measurements in the same
    direction before changing the worker count, preventing oscillation
    near threshold boundaries.

    Configuration via environment variables:
        RAG_ADAPTIVE_WORKERS     - enable/disable (default: true)
        RAG_ADAPTIVE_RAM_HIGH    - RAM% threshold to decrease workers (default: 75)
        RAG_ADAPTIVE_RAM_LOW     - RAM% threshold to allow increasing workers (default: 60)
        RAG_ADAPTIVE_CPU_HIGH    - 1-min load avg threshold to decrease (default: 2.5)
        RAG_ADAPTIVE_CPU_LOW     - 1-min load avg threshold to allow increase (default: 1.5)
        RAG_ADAPTIVE_BATCH_SIZE  - files per sub-batch (default: 10)
    """

    CYCLES_TO_INCREASE = 3
    CYCLES_TO_DECREASE = 2

    def __init__(
        self,
        min_workers: int = 2,
        max_workers: int = 4,
        ram_high: float = 75.0,
        ram_low: float = 60.0,
        cpu_high: float = 2.5,
        cpu_low: float = 1.5,
    ):
        self.min_workers = max(1, min_workers)
        self.max_workers = max(self.min_workers, max_workers)
        self.ram_high = float(os.getenv("RAG_ADAPTIVE_RAM_HIGH", str(ram_high)))
        self.ram_low = float(os.getenv("RAG_ADAPTIVE_RAM_LOW", str(ram_low)))
        self.cpu_high = float(os.getenv("RAG_ADAPTIVE_CPU_HIGH", str(cpu_high)))
        self.cpu_low = float(os.getenv("RAG_ADAPTIVE_CPU_LOW", str(cpu_low)))

        self._current = max_workers
        self._up_streak = 0    # consecutive "conditions are good" readings
        self._down_streak = 0  # consecutive "conditions are bad" readings

    def get_workers(self) -> int:
        """Return the recommended worker count for the next sub-batch.

        Reads current system RAM and CPU load, applies hysteresis logic,
        and returns a value in [min_workers, max_workers].

        If psutil is unavailable, returns max_workers unchanged.
        """
        if not _PSUTIL_AVAILABLE:
            return self._current

        ram_pct = psutil.virtual_memory().percent
        # load average: 1-min value normalised per CPU count
        cpu_count = psutil.cpu_count(logical=True) or 1
        load_avg = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
        load_per_cpu = load_avg / cpu_count

        pressure = ram_pct > self.ram_high or load_per_cpu > self.cpu_high
        relaxed = ram_pct < self.ram_low and load_per_cpu < self.cpu_low

        if pressure:
            self._down_streak += 1
            self._up_streak = 0
            if self._down_streak >= self.CYCLES_TO_DECREASE:
                new = max(self.min_workers, self._current - 1)
                if new != self._current:
                    logger.info(
                        "AdaptiveWorkers: reducing workers %d→%d "
                        "(RAM=%.1f%%, load/cpu=%.2f)",
                        self._current, new, ram_pct, load_per_cpu,
                    )
                    self._current = new
                self._down_streak = 0
        elif relaxed:
            self._up_streak += 1
            self._down_streak = 0
            if self._up_streak >= self.CYCLES_TO_INCREASE:
                new = min(self.max_workers, self._current + 1)
                if new != self._current:
                    logger.info(
                        "AdaptiveWorkers: increasing workers %d→%d "
                        "(RAM=%.1f%%, load/cpu=%.2f)",
                        self._current, new, ram_pct, load_per_cpu,
                    )
                    self._current = new
                self._up_streak = 0
        else:
            # Neutral: decay streaks without resetting fully
            self._down_streak = max(0, self._down_streak - 1)
            self._up_streak = max(0, self._up_streak - 1)

        return self._current

    @property
    def current_workers(self) -> int:
        return self._current


def is_adaptive_enabled() -> bool:
    """Return True if adaptive worker mode is enabled via config."""
    return os.getenv("RAG_ADAPTIVE_WORKERS", "true").lower() not in ("false", "0", "no")


def get_adaptive_batch_size() -> int:
    """Return the sub-batch size for adaptive processing."""
    return max(1, int(os.getenv("RAG_ADAPTIVE_BATCH_SIZE", "10")))
