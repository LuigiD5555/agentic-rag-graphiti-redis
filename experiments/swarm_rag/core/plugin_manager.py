"""
PluginManager — registry, manifest loading, and plugin lifecycle.

Responsibilities:
- Register plugin instances by name
- Load and validate manifest.json from each plugin's directory
- Expose get_plugin() and list_active() for the Router and Planner
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from experiments.swarm_rag.plugins.base_plugin import BasePlugin
from experiments.swarm_rag.schemas.plugin_manifest import PluginManifest

logger = logging.getLogger(__name__)

_PLUGINS_DIR = Path(__file__).parent.parent / "plugins"


class PluginManager:
    def __init__(self) -> None:
        self._registry: dict[str, BasePlugin] = {}
        self._manifests: dict[str, PluginManifest] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, plugin: BasePlugin) -> None:
        """Register a plugin instance. Loads its manifest if not yet loaded."""
        self._registry[plugin.name] = plugin
        if plugin.name not in self._manifests:
            self._load_manifest(plugin.name)
        logger.debug("Registered plugin: %s", plugin.name)

    def _load_manifest(self, name: str) -> None:
        manifest_path = _PLUGINS_DIR / name / "manifest.json"
        if not manifest_path.exists():
            logger.warning("No manifest.json for plugin '%s' at %s", name, manifest_path)
            return
        try:
            data = json.loads(manifest_path.read_text())
            self._manifests[name] = PluginManifest(**data)
        except Exception as exc:
            logger.error("Failed to load manifest for '%s': %s", name, exc)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        return self._registry.get(name)

    def get_manifest(self, name: str) -> Optional[PluginManifest]:
        return self._manifests.get(name)

    def list_active(self) -> list[str]:
        """Return names of all registered, enabled plugins."""
        active = []
        for name, plugin in self._registry.items():
            manifest = self._manifests.get(name)
            if manifest is None or manifest.enabled:
                active.append(name)
        return active

    def list_all(self) -> dict[str, PluginManifest]:
        return dict(self._manifests)

    def dependencies_of(self, name: str) -> list[str]:
        manifest = self._manifests.get(name)
        return manifest.dependencies if manifest else []

    # ------------------------------------------------------------------
    # Bulk auto-discovery (optional convenience)
    # ------------------------------------------------------------------

    def autodiscover(self) -> None:
        """
        Scan plugins/ directory for manifest.json files and load them.
        Does NOT instantiate plugins — callers must still register instances.
        Useful for inspecting capabilities before runtime registration.
        """
        for manifest_path in sorted(_PLUGINS_DIR.glob("*/manifest.json")):
            plugin_name = manifest_path.parent.name
            if plugin_name not in self._manifests:
                self._load_manifest(plugin_name)
        logger.info("Autodiscovered %d plugin manifests", len(self._manifests))
