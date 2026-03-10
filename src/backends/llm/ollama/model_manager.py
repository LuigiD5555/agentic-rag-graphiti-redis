"""
OllamaModelManager — list installed models and pull missing ones.

Endpoints:
  GET  /api/tags   — list installed models
  POST /api/pull   — download a model (stream=False: blocks until done)
"""
from __future__ import annotations

import logging
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)


class OllamaModelManager:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        require_live: bool = False,
        timeout: int = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._require_live = require_live
        self._timeout = timeout
        self._installed: Optional[List[str]] = None  # lazy-loaded, invalidated after pull

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_models(self) -> List[str]:
        """Return installed model names from GET /api/tags. Cached per instance."""
        if self._installed is not None:
            return self._installed
        try:
            resp = requests.get(f"{self._base_url}/api/tags", timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            self._installed = [m["name"] for m in data.get("models", [])]
            logger.info("Ollama models available: %s", self._installed)
            return self._installed
        except requests.exceptions.RequestException as exc:
            logger.error("Failed to list Ollama models: %s", exc)
            if self._require_live:
                raise RuntimeError(f"Ollama unreachable at {self._base_url}: {exc}") from exc
            self._installed = []
            return []

    def ensure_model(self, name: str) -> bool:
        """Pull `name` if not already installed. Returns True if available."""
        if self._is_installed(name):
            logger.info("Ollama model '%s' already installed.", name)
            return True
        logger.info("Ollama model '%s' not found — pulling...", name)
        return self.pull_model(name)

    def pull_model(self, name: str, pull_timeout: int = 3600) -> bool:
        """POST /api/pull with stream=False (blocks until done). Invalidates cache."""
        logger.info("Pulling Ollama model '%s' (may take several minutes)...", name)
        try:
            resp = requests.post(
                f"{self._base_url}/api/pull",
                json={"name": name, "stream": False},
                timeout=pull_timeout,
            )
            resp.raise_for_status()
            self._installed = None  # invalidate so next list_models() is fresh
            logger.info("Successfully pulled '%s'", name)
            return True
        except requests.exceptions.RequestException as exc:
            logger.error("Failed to pull '%s': %s", name, exc)
            if self._require_live:
                raise RuntimeError(f"Failed to pull model '{name}': {exc}") from exc
            return False

    def get_first_language_model(self) -> Optional[str]:
        """Return first non-embedding installed model, or None."""
        models = [m for m in self.list_models() if "embed" not in m.lower()]
        return models[0] if models else None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_installed(self, name: str) -> bool:
        """Check if name (ignoring :tag suffix) is in the installed list."""
        bare = name.split(":")[0]
        for m in self.list_models():
            if m == name or m.split(":")[0] == bare:
                return True
        return False
