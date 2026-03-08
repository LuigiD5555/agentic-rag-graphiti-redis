"""
Blackboard shared state schema.

The blackboard is the central contract of the SWARM RAG system.
All plugins read from and write to this state. It is created per-query
and cleaned up after the response is delivered.
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class MathContext(BaseModel):
    detected: bool = False
    problem_type: Optional[str] = None
    variables: list[dict] = Field(default_factory=list)
    required_operation: Optional[str] = None
    missing_inputs: list[str] = Field(default_factory=list)
    tool_hint: Optional[str] = None
    result: Optional[Any] = None


class CodeContext(BaseModel):
    detected: bool = False
    language: Optional[str] = None
    task_type: Optional[str] = None
    symbols: list[str] = Field(default_factory=list)
    likely_files: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    tool_hint: Optional[str] = None
    result: Optional[Any] = None


class RetrievalResults(BaseModel):
    weaviate_hits: list[dict] = Field(default_factory=list)
    neo4j_hits: list[dict] = Field(default_factory=list)
    memory_hits: list[dict] = Field(default_factory=list)


class BlackboardState(BaseModel):
    # --- Input ---
    user_query: str
    session_id: str
    timestamp: str

    # --- Intent & routing ---
    intents: list[str] = Field(default_factory=list)
    active_plugins: list[str] = Field(default_factory=list)

    # --- Specialist contexts ---
    math_context: MathContext = Field(default_factory=MathContext)
    code_context: CodeContext = Field(default_factory=CodeContext)

    # --- Retrieval ---
    retrieval: RetrievalResults = Field(default_factory=RetrievalResults)

    # --- Tool execution ---
    tool_plan: list[dict] = Field(default_factory=list)
    tool_results: list[dict] = Field(default_factory=list)

    # --- Version / conflict detection ---
    version_conflicts: list[dict] = Field(default_factory=list)
    active_versions: list[dict] = Field(default_factory=list)

    # --- Privacy ---
    anonymized: bool = False
    entity_map: dict = Field(default_factory=dict)  # PII -> anonymous token

    # --- Final output ---
    evidence_summary: Optional[str] = None
    final_response: Optional[str] = None

    # --- Observability ---
    execution_trace: list[dict] = Field(default_factory=list)
    latency_ms: dict = Field(default_factory=dict)
