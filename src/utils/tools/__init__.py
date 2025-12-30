"""
Tools module for managing external preprocessing services.

This module provides utilities for managing systemd-activated preprocessing
tools (extractor, document-processor, websearch) that run as containers on-demand.
"""

from .systemd_manager import SystemdManager

__all__ = ['SystemdManager']
