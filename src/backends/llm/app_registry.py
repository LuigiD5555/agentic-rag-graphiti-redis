import logging
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import entry_points
from typing import Iterable

from src.core import Result, emit_error
from src.core.errors import ConfigError
from src.workflows.query.apps import AppConfig
from src.backends.llm.builtins import ensure_builtin_providers_loaded

log = logging.getLogger(__name__)

DEFAULT_APP_ENTRYPOINT_GROUP = "rag_agentic_graphiti.apps"


@dataclass(slots=True)
class AppRegistry:
    """
    Django-like app registry with optional Python entry-point discovery.

    - Config.INSTALLED_APPS defines explicit app config class paths.
    - Optionally, entry points in DEFAULT_APP_ENTRYPOINT_GROUP are loaded too.

    This keeps extension logic in the framework while letting users add apps
    declaratively (similar to Django INSTALLED_APPS).
    """

    apps: dict[str, AppConfig]
    populated: bool = False

    def populate(self, config) -> None:
        if self.populated:
            return

        installed = getattr(config, "INSTALLED_APPS", None) or []
        if not isinstance(installed, (list, tuple)):
            raise TypeError("Config.INSTALLED_APPS must be a list/tuple of dotted paths")

        # 1) Explicit apps from settings (stable order).
        for spec in installed:
            if not isinstance(spec, str) or not spec.strip():
                raise TypeError("Each entry in INSTALLED_APPS must be a non-empty string")
            app_config = _load_app_config(spec.strip())
            self._add_app(app_config)

        # 2) Optional autoload from Python entry points (opt-in).
        if bool(getattr(config, "AUTOLOAD_APP_ENTRYPOINTS", False)):
            for spec in _iter_entrypoint_app_specs(group=getattr(
                config, "APP_ENTRYPOINT_GROUP", DEFAULT_APP_ENTRYPOINT_GROUP
                )
            ):
                app_config = _load_app_config(spec)
                self._add_app(app_config)

        # 3) Call ready hooks once all apps are present.
        for app in self.apps.values():
            try:
                app.ready()
            except Exception:
                log.exception("App '%s' ready() raised an exception", app.label)
                raise

        self.populated = True

    def _add_app(self, app: AppConfig) -> None:
        if app.label in self.apps:
            # Deterministic: ignore duplicates.
            return
        self.apps[app.label] = app


_global_registry: AppRegistry | None = None


def get_app_registry() -> AppRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = AppRegistry(apps={})
    return _global_registry


def ensure_apps_loaded(config) -> AppRegistry:
    ensure_builtin_providers_loaded()
    registry = get_app_registry()
    registry.populate(config)
    return registry


def reset_app_registry() -> None:  # pragma: no cover
    global _global_registry
    _global_registry = None


def _load_app_config(dotted_path: str) -> AppConfig:
    """
    Load an AppConfig instance from a dotted class path.

    Example:
        "src.backends.llm.lmstudio.apps.LMStudioProviderAppConfig"
    """

    module_path, _, attr = dotted_path.rpartition(".")
    if not module_path:
        raise ImportError(f"Invalid app spec '{dotted_path}'; expected 'package.module.ClassName'")

    module = import_module(module_path)
    obj = getattr(module, attr, None)
    if obj is None:
        raise ImportError(f"Module '{module_path}' does not define '{attr}'")
    if not isinstance(obj, type) or not issubclass(obj, AppConfig):
        raise TypeError(f"'{dotted_path}' must be a subclass of src.workflows.query.apps.AppConfig")

    instance: AppConfig = obj()  # type: ignore[call-arg]
    return instance


def _iter_entrypoint_app_specs(group: str) -> Iterable[str]:
    try:
        eps = entry_points()
        if hasattr(eps, "select"):
            candidates = list(eps.select(group=group))
        else:
            selected = eps.get(group)  # type: ignore[attr-defined]
            candidates = list(selected or ())
    except Exception:
        log.exception("Failed reading entry points group '%s'", group)
        return ()

    out: list[str] = []
    for ep in candidates:
        # Prefer the explicit module:attr string; works even if loading fails later.
        value = getattr(ep, "value", None)
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
            continue
        # Fallback to requiring the entry point.
        try:
            resolved = ep.load()
        except Exception:
            log.exception("Failed loading entry point '%s' in group '%s'", getattr(ep, "name", "<unknown>"), group)
            continue
        if isinstance(resolved, type) and issubclass(resolved, AppConfig):
            out.append(f"{resolved.__module__}.{resolved.__name__}")
    return out
