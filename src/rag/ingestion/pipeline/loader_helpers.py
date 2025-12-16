import os
from typing import Any

from src.rag.ingestion.loaders.errors import LoaderError
from src.rag.audit import get_logger

from .failures import record_failure

log = get_logger(__name__)


def call_loader(pipeline: Any, loader: object, method_name: str):
    load_fn = getattr(loader, method_name, None)
    if load_fn is None:
        log.error("Loader %s does not implement %s; skipping.", loader.__class__.__name__, method_name)
        return None

    try:
        return load_fn()
    except LoaderError as exc:
        source = resolve_loader_source(loader)
        log.warning("Skipping %s: %s", source, exc)
        record_failure(pipeline, source, str(exc), reason="loader_skip")
    except Exception as exc:  # pragma: no cover - defensive logging
        source = resolve_loader_source(loader)
        log.exception("Loader %s failed for %s: %s", loader.__class__.__name__, source, exc)
        record_failure(pipeline, source, str(exc), reason="loader_error")
    return None


def resolve_loader_source(loader: object) -> str:
    for attr in ("path", "_path", "file_path", "source"):
        value = getattr(loader, attr, None)
        if value:
            return str(value)
    return loader.__class__.__name__


def should_skip_path(path: str) -> bool:
    if os.path.islink(path) and not os.path.exists(path):
        try:
            target = os.readlink(path)
            log.warning("Skipping broken symlink: %s -> %s", path, target)
        except OSError:
            log.warning("Skipping broken symlink: %s", path)
        return True

    basename = os.path.basename(path)
    if basename.strip().startswith("~$"):
        log.info("Skipping temporary Office lock file: %s", path)
        return True

    if not os.path.exists(path):
        log.error("Path does not exist: %s", path)
        return True

    return False


__all__ = ["call_loader", "resolve_loader_source", "should_skip_path"]
