"""File discovery module for RAG ingestion.

This module provides functionality to discover and filter files in the filesystem
for ingestion into the RAG system. It includes caching, pattern matching, path tree
optimization, and various filtering strategies.
"""

from .cache import DirectoryScanCache, DiscoveryCacheManager
from .filters import (
    FilterStrategy,
    IgnoreDirsStrategy,
    ExtFilterStrategy,
    GlobExclusionStrategy,
    build_filters
)
from .pattern_matching import PatternMatcher
from .path_tree import PathTree, PathNode
from .scanner import DirectoryScanner
from .adaptive_scanner import AdaptiveHybridScanner, SchedulerPolicy, ScanMetrics, DirectoryState
from .service import FileDiscoveryService

__all__ = [
    # Main service
    "FileDiscoveryService",

    # Cache
    "DirectoryScanCache",
    "DiscoveryCacheManager",

    # Filters
    "FilterStrategy",
    "IgnoreDirsStrategy",
    "ExtFilterStrategy",
    "GlobExclusionStrategy",
    "build_filters",

    # Pattern matching
    "PatternMatcher",

    # Path tree optimization
    "PathTree",
    "PathNode",

    # Scanner
    "DirectoryScanner",

    # Adaptive scanner
    "AdaptiveHybridScanner",
    "SchedulerPolicy",
    "ScanMetrics",
    "DirectoryState",
]
