from __future__ import annotations

from typing import Callable, Dict, Optional

from src.backends.storage.cache.ingestion import IngestionCacheManager
from src.workflows.ingestion.strategies.base import IngestionStrategy
from src.workflows.ingestion.strategies.high_memory import HighMemoryStrategy
from src.workflows.ingestion.strategies.low_memory import LowMemoryStrategy

STRATEGY_REGISTRY: Dict[str, Callable[..., IngestionStrategy]] = {
    "high_memory": HighMemoryStrategy,
    "low_memory": LowMemoryStrategy,
}


def select_strategy(
    config: object,
    cache_manager: IngestionCacheManager | None,
    strategy_override: Optional[str] = None,
    max_ram_override: Optional[int] = None,
) -> IngestionStrategy:
    """Return the best strategy for the current configuration."""
    requested = (strategy_override or getattr(config, "INGESTION_STRATEGY", "auto") or "auto").lower()

    if requested == "auto":
        requested = _auto_detect(config, max_ram_override)

    strategy_cls = STRATEGY_REGISTRY.get(requested, HighMemoryStrategy)
    return strategy_cls(config, cache_manager)


def _auto_detect(config: object, max_ram_override: Optional[int] = None) -> str:
    profile = getattr(config, "RAG_PERFORMANCE_PROFILE", None) or getattr(config, "RESOURCE_MODE", None)
    if isinstance(profile, str):
        normalized = profile.lower()
        if normalized in {"performance", "high", "balanced"}:
            return "high_memory"
        if normalized in {"optimized", "low_memory", "low"}:
            return "low_memory"

    threshold = max_ram_override if max_ram_override is not None else getattr(config, "MAX_RAM_USAGE_PERCENT", 80)
    if _has_enough_ram(threshold):
        return "high_memory"

    return "low_memory"


def _has_enough_ram(max_usage_percent: int) -> bool:
    try:
        import psutil  # type: ignore[import]
    except ImportError:
        return True

    try:
        memory = psutil.virtual_memory()
        return memory.percent <= max_usage_percent
    except Exception:
        return True
