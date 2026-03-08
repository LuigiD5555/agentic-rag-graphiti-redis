"""
Router — decides which plugins to activate for a given query.

Strategy (F1): keyword-based activation loaded from config/router_keywords.yaml.
The baseline set (retrieval, context_compressor, evidence_merger) is always on.
Specialist plugins activate when any of their keywords appear in the query.

The KEYWORD_MAP is reloaded automatically if the YAML file changes (via mtime).
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "router_keywords.yaml"

# Hardcoded fallback (used when YAML is unavailable)
_DEFAULT_ALWAYS_ON: list[str] = ["retrieval", "context_compressor", "evidence_merger"]
_DEFAULT_KEYWORD_MAP: dict[str, list[str]] = {
    "math_understanding": ["calcula", "porcentaje", "%", "suma", "divide"],
    "math_tool": ["calcula", "porcentaje", "%", "suma", "divide", "formula"],
    "code_understanding": ["python", "funcion", "metodo", "bug", "codigo", "clase"],
    "code_agent": ["archivo", "diff", "tests", "repo", "commit"],
    "graph_retrieval": ["relacion", "conecta", "depende", "vinculo", "grafo"],
    "version_monitor": ["version", "anterior", "actual", "cambio", "vigente"],
    "mcp_tool_agent": ["digit", "git", "commit", "repo", "mcp"],
    "memory_retrieval": ["antes", "recuerdas", "solucionamos", "anteriormente"],
    "privacy_scrubber": ["confidencial", "privado", "secreto", "pii", "gdpr"],
}


class _RouterConfig:
    """Lazy-loading YAML config with mtime-based cache invalidation."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._mtime: Optional[float] = None
        self._always_on: list[str] = list(_DEFAULT_ALWAYS_ON)
        self._keyword_map: dict[str, list[str]] = dict(_DEFAULT_KEYWORD_MAP)
        self._load()

    def _load(self) -> None:
        if not _YAML_AVAILABLE:
            logger.warning("PyYAML not available — using hardcoded keyword map")
            return
        if not self._path.exists():
            logger.warning("Router keywords config not found at %s — using defaults", self._path)
            return
        try:
            mtime = self._path.stat().st_mtime
            if mtime == self._mtime:
                return  # unchanged
            data = yaml.safe_load(self._path.read_text())
            self._always_on = data.get("always_on", _DEFAULT_ALWAYS_ON)
            kmap = data.get("keyword_map", {})
            self._keyword_map = {
                plugin: cfg.get("keywords", [])
                for plugin, cfg in kmap.items()
            }
            self._mtime = mtime
            logger.info("Loaded router keywords from %s", self._path)
        except Exception as exc:
            logger.error("Failed to load router keywords: %s — using defaults", exc)

    @property
    def always_on(self) -> list[str]:
        self._load()  # re-check mtime on each access
        return self._always_on

    @property
    def keyword_map(self) -> dict[str, list[str]]:
        self._load()
        return self._keyword_map


class Router:
    """
    Classifies the query and decides which plugins to activate.

    Returns a list of plugin names that should run for the given BlackboardState.
    The list always includes the baseline (always_on) plugins.
    """

    def __init__(self, config_path: Path = _CONFIG_PATH) -> None:
        self._config = _RouterConfig(config_path)

    async def route(self, state: BlackboardState) -> list[str]:
        """Return ordered list of plugin names to activate."""
        q = state.user_query.lower()
        active: list[str] = list(self._config.always_on)

        for plugin, keywords in self._config.keyword_map.items():
            if plugin in active:
                continue
            if any(kw in q for kw in keywords):
                active.append(plugin)
                logger.debug("Router activated '%s' for query: %.60s…", plugin, q)

        state.active_plugins = active
        state.intents = self._extract_intents(active)
        logger.info("Router activated %d plugins: %s", len(active), active)
        return active

    def _extract_intents(self, active_plugins: list[str]) -> list[str]:
        """Derive high-level intents from the active plugin set."""
        intents = []
        if "math_understanding" in active_plugins:
            intents.append("math")
        if "code_understanding" in active_plugins:
            intents.append("code")
        if "graph_retrieval" in active_plugins:
            intents.append("graph")
        if "version_monitor" in active_plugins:
            intents.append("version")
        if "memory_retrieval" in active_plugins:
            intents.append("memory")
        if not intents:
            intents.append("retrieval")
        return intents
