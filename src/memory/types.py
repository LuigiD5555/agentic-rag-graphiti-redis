"""Type definitions for memory system.

This module contains shared type definitions to avoid circular imports.
"""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ChatMemorySnapshot:
    """Snapshot of a conversation for ChatMemory storage."""
    summary_dense: str              # Pareto compressed summary (for embedding)
    key_quotes: List[str]           # Critical quotes
    keywords: List[str]             # Keywords for BM25
    thread_id: str
    user_id: str
    timestamp: str                  # RFC-3339
    ttl_at: str                     # RFC-3339
    pinned: bool
    original_message_count: int
    compression_ratio: float
    tool_executions: Optional[str]  # JSON serialized