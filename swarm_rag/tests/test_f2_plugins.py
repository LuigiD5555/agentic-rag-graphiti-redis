"""
Unit tests for F2 core plugins:
- ContextCompressorPlugin
- EvidenceMerger

RetrievalPlugin is integration-only (requires live Weaviate) — tested separately.
All tests run without external dependencies.
"""
from __future__ import annotations

import asyncio
import pytest

from swarm_rag.schemas.blackboard_schema import BlackboardState, MathContext, CodeContext
from swarm_rag.plugins.context_compressor.plugin import ContextCompressorPlugin, _dedup_and_filter
from swarm_rag.plugins.evidence_merger.merger import EvidenceMerger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(**kwargs) -> BlackboardState:
    base = dict(user_query="test", session_id="s1", timestamp="2026-01-01T00:00:00Z")
    base.update(kwargs)
    return BlackboardState(**base)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_hits(n: int, base_score: float = 0.8) -> list[dict]:
    return [
        {"chunk_id": f"c{i}", "text": f"text {i}", "score": base_score - i * 0.05, "source": f"doc{i}.pdf"}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# _dedup_and_filter unit tests
# ---------------------------------------------------------------------------

class TestDedupAndFilter:
    def test_filters_below_min_score(self):
        hits = [
            {"chunk_id": "a", "text": "x", "score": 0.8},
            {"chunk_id": "b", "text": "y", "score": 0.2},
        ]
        result = _dedup_and_filter(hits, min_score=0.5, max_hits=10)
        assert len(result) == 1
        assert result[0]["chunk_id"] == "a"

    def test_deduplicates_by_chunk_id_keeps_highest_score(self):
        hits = [
            {"chunk_id": "a", "text": "x", "score": 0.6},
            {"chunk_id": "a", "text": "x", "score": 0.9},
        ]
        result = _dedup_and_filter(hits, min_score=0.0, max_hits=10)
        assert len(result) == 1
        assert result[0]["score"] == 0.9

    def test_trims_to_max_hits(self):
        hits = _make_hits(20, base_score=0.9)
        result = _dedup_and_filter(hits, min_score=0.0, max_hits=5)
        assert len(result) == 5

    def test_sorted_by_score_descending(self):
        hits = [
            {"chunk_id": "a", "score": 0.5},
            {"chunk_id": "b", "score": 0.9},
            {"chunk_id": "c", "score": 0.7},
        ]
        result = _dedup_and_filter(hits, min_score=0.0, max_hits=10)
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_empty_input_returns_empty(self):
        assert _dedup_and_filter([], min_score=0.5, max_hits=10) == []


# ---------------------------------------------------------------------------
# ContextCompressorPlugin tests
# ---------------------------------------------------------------------------

class TestContextCompressorPlugin:
    def test_filters_low_score_weaviate_hits(self):
        state = _state()
        state.retrieval.weaviate_hits = [
            {"chunk_id": "a", "score": 0.8, "text": "good"},
            {"chunk_id": "b", "score": 0.1, "text": "bad"},
        ]
        result = _run(ContextCompressorPlugin(min_score=0.5).run(state))
        assert len(result.retrieval.weaviate_hits) == 1
        assert result.retrieval.weaviate_hits[0]["chunk_id"] == "a"

    def test_empty_lists_stay_empty(self):
        state = _state()
        result = _run(ContextCompressorPlugin().run(state))
        assert result.retrieval.weaviate_hits == []
        assert result.retrieval.neo4j_hits == []
        assert result.retrieval.memory_hits == []

    def test_all_three_lists_processed(self):
        state = _state()
        state.retrieval.weaviate_hits = _make_hits(5, 0.9)
        state.retrieval.neo4j_hits = _make_hits(3, 0.8)
        state.retrieval.memory_hits = _make_hits(4, 0.7)
        result = _run(ContextCompressorPlugin(min_score=0.0, max_hits=2).run(state))
        assert len(result.retrieval.weaviate_hits) == 2
        assert len(result.retrieval.neo4j_hits) == 2
        assert len(result.retrieval.memory_hits) == 2


# ---------------------------------------------------------------------------
# EvidenceMerger tests
# ---------------------------------------------------------------------------

class TestEvidenceMerger:
    def test_empty_state_produces_empty_summary(self):
        state = _state()
        result = _run(EvidenceMerger().run(state))
        assert result.evidence_summary == ""

    def test_weaviate_hits_appear_in_summary(self):
        state = _state()
        state.retrieval.weaviate_hits = [
            {"chunk_id": "a", "text": "El contrato vigente dice X", "score": 0.9, "source": "contrato.pdf"}
        ]
        result = _run(EvidenceMerger().run(state))
        assert "El contrato vigente dice X" in result.evidence_summary
        assert "contrato.pdf" in result.evidence_summary

    def test_math_result_appears_in_summary(self):
        state = _state()
        state.math_context = MathContext(detected=True, problem_type="percentage", result=15.0)
        result = _run(EvidenceMerger().run(state))
        assert "15.0" in result.evidence_summary
        assert "MATEMÁTICO" in result.evidence_summary

    def test_code_result_appears_in_summary(self):
        state = _state()
        state.code_context = CodeContext(detected=True, language="Python", result="def foo(): pass")
        result = _run(EvidenceMerger().run(state))
        assert "Python" in result.evidence_summary
        assert "def foo()" in result.evidence_summary

    def test_version_conflicts_appear_in_summary(self):
        state = _state()
        state.version_conflicts = [{"description": "v2024 contradicts vigente"}]
        result = _run(EvidenceMerger().run(state))
        assert "v2024 contradicts vigente" in result.evidence_summary
        assert "VERSIÓN" in result.evidence_summary

    def test_memory_hits_appear_in_summary(self):
        state = _state()
        state.retrieval.memory_hits = [
            {"chunk_id": "m1", "text": "Solución anterior aplicada", "score": 0.75, "source": "memory"}
        ]
        result = _run(EvidenceMerger().run(state))
        assert "Solución anterior aplicada" in result.evidence_summary
        assert "SESIÓN" in result.evidence_summary

    def test_sections_separated_by_divider(self):
        state = _state()
        state.retrieval.weaviate_hits = [
            {"chunk_id": "a", "text": "fact 1", "score": 0.9, "source": "s1"}
        ]
        state.math_context = MathContext(detected=True, result=42)
        result = _run(EvidenceMerger().run(state))
        assert "─" in result.evidence_summary  # section separator present

    def test_tool_results_appear_in_summary(self):
        state = _state()
        state.tool_results = [{"tool": "git", "output": "commit abc123"}]
        result = _run(EvidenceMerger().run(state))
        assert "commit abc123" in result.evidence_summary
        assert "git" in result.evidence_summary
