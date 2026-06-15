"""
Monitoring package for RAG Agentic Graphiti.

This package provides:
1. Bloat analysis (coverage + vulture integration)
2. Real-time code usage monitoring
3. Pipeline-specific code classification
4. Detailed reporting with code snippets
"""

from .bloat_analyzer import BloatAnalyzer, CoverageAnalyzer, VultureAnalyzer, BloatCorrelator
from .realtime_monitor import (
    RealTimeCoverageMonitor,
    CodeSnippetExtractor,
    PipelineClassifier,
    ReportGenerator,
    RealTimeMonitoringCLI
)

__all__ = [
    "BloatAnalyzer",
    "CoverageAnalyzer",
    "VultureAnalyzer",
    "BloatCorrelator",
    "RealTimeCoverageMonitor",
    "CodeSnippetExtractor",
    "PipelineClassifier",
    "ReportGenerator",
    "RealTimeMonitoringCLI"
]

__version__ = "1.0.0"