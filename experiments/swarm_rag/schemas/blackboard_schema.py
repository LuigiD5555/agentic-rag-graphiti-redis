"""
Blackboard shared state — v3 schema.

Four structured sub-states written by each layer:
  perception  <- Perception Layer (encoders)
  retrieval   <- Knowledge Layer (Weaviate + Neo4j)
  specialists <- Specialist Layer (seq2seq)
  reasoning   <- Integration/Reasoning Layer

The generador final (SLM) reads reasoning.structured_answer only.
State is per-query and cleaned up after response delivery.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field


class PerceptionOutput(BaseModel):
    intent: str = "general"
    domain: str = "general"
    entities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    language: str = "es"
    complexity: str = "low"
    needs_retrieval: bool = True
    needs_math: bool = False
    needs_code: bool = False
    tone: str = "neutral"


class RetrievalOutput(BaseModel):
    weaviate_hits: list[dict] = Field(default_factory=list)
    neo4j_hits: list[dict] = Field(default_factory=list)
    memory_hits: list[dict] = Field(default_factory=list)
    version_conflicts: list[dict] = Field(default_factory=list)


class SpecialistOutput(BaseModel):
    rewritten_query: Optional[str] = None
    subquestions: list[str] = Field(default_factory=list)
    retrieved_plan: Optional[dict] = None
    extracted_facts: list[dict] = Field(default_factory=list)
    ranked_evidence: list[dict] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    conflicts_found: list[dict] = Field(default_factory=list)
    math_result: Optional[Any] = None
    code_analysis: Optional[dict] = None


class ReasoningOutput(BaseModel):
    structured_answer: Optional[str] = None
    key_points: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    confidence_score: float = 0.0
    escalate_to_llm: bool = False


class BlackboardState(BaseModel):
    session_id: str
    user_query: str
    timestamp: str

    perception: PerceptionOutput = Field(default_factory=PerceptionOutput)
    retrieval: RetrievalOutput = Field(default_factory=RetrievalOutput)
    specialists: SpecialistOutput = Field(default_factory=SpecialistOutput)
    reasoning: ReasoningOutput = Field(default_factory=ReasoningOutput)

    final_response: Optional[str] = None
    execution_trace: list[dict] = Field(default_factory=list)
    latency_ms: dict = Field(default_factory=dict)
    active_branches: list[str] = Field(default_factory=list)

    @classmethod
    def new_session(cls, query: str, session_id: Optional[str] = None) -> "BlackboardState":
        return cls(
            session_id=session_id or str(uuid.uuid4()),
            user_query=query,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
        )

    def clear_temp(self) -> None:
        """Clear intermediate data, keeping final_response and execution_trace."""
        self.retrieval = RetrievalOutput()
        self.specialists = SpecialistOutput()
        self.reasoning = ReasoningOutput()
        self.active_branches = []
