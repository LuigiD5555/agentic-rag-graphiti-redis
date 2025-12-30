"""
Tools module for managing external preprocessing services.

This module provides utilities for managing systemd-activated preprocessing
tools (extractor, document-processor, websearch) that run as containers on-demand.
"""

from importlib import import_module

__all__ = ['SystemdManager']


def __getattr__(name: str):
    if name == "SystemdManager":
        return import_module(".systemd_manager", __name__).SystemdManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
