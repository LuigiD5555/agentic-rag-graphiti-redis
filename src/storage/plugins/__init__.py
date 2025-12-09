from __future__ import annotations

from importlib import import_module
from typing import Any, Dict


def _import_string(dotted_path: str) -> Any:
    """
    Import a class or object from a dotted path.

    Example: "src.storage.vector.weaviate_repository.plugin.WeaviateVectorPlugin"
    """
    module_path, _, attr = dotted_path.rpartition(".")
    if not module_path:
        msg = f"Invalid dotted path '{dotted_path}'; expected 'package.module.ClassName'"
        raise ImportError(msg)
    module = import_module(module_path)
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise ImportError(f"Module '{module_path}' does not define a '{attr}' attribute") from exc


def load_storage_backend(engine_path: str) -> Any:
    """
    Load a storage backend class from an ENGINE string.

    The returned object is the class; callers are responsible for instantiation.
    """
    backend_cls = _import_string(engine_path)
    return backend_cls


def create_storage_instance(config: Dict[str, Any]) -> Any:
    """
    Instantiate a storage backend from a config dict that contains at least:
        - ENGINE: dotted path to the backend class.

    Additional keys are passed as '**options' to the backend constructor.
    """
    engine = config.get("ENGINE")
    if not engine:
        raise ValueError("Storage config must define an 'ENGINE' key")

    backend_cls = load_storage_backend(engine)

    # Pass all config entries except ENGINE to the backend
    options = {k: v for k, v in config.items() if k != "ENGINE"}
    return backend_cls(**options)
