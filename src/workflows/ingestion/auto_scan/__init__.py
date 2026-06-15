"""Auto-scan scheduler tool - periodically scans for file changes and triggers ingestion."""

__all__ = ["AutoScanScheduler", "main"]


def __getattr__(name: str):
    """Lazily import exports to avoid runpy warnings about premature submodule loading."""
    if name == "AutoScanScheduler":
        from .scheduler import AutoScanScheduler

        return AutoScanScheduler
    if name == "main":
        from .scheduler import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
