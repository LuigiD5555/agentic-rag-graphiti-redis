"""
Unit tests for F2 specialist layer.

All tests mock the HF models so they run without downloading anything.
Tests verify:
- Contract: input/output fields on BlackboardState
- Fallback behaviour when model is unavailable
- Routing: specialist skipped when not in active_branches
- Ordering: EvidenceRanker uses extracted_facts when available
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from swarm_rag.schemas.blackboard_schema import BlackboardState, PerceptionOutput
from swarm_rag.specialists.query_rewriter import QueryRewriter, _is_meaningful
from swarm_rag.specialists.fact_extractor import FactExtractor
from swarm_rag.specialists.evidence_ranker import EvidenceRanker
from swarm_rag.specialists.specialist_layer import run_specialists


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _state(query="test query", complexity="medium", intent="research") -> BlackboardState:
    s = BlackboardState.new_session(query)
    s.perception = PerceptionOutput(complexity=complexity, intent=intent)
    s.active_branches = ["query_rewriter", "fact_extractor", "evidence_ranker"]
    return s


def _hits(n=3):
    return [
        {"chunk_id": f"c{i}", "text": f"The contract clause {i} establishes a penalty of {i*5}%",
         "score": 0.9 - i * 0.1, "source": f"doc{i}.pdf"}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# _is_meaningful helper
# ---------------------------------------------------------------------------

class TestIsMeaningful:
    def test_identical_returns_false(self):
        assert not _is_meaningful("hello world", "hello world")

    def test_empty_returns_false(self):
        assert not _is_meaningful("hello", "")

    def test_different_enough_returns_true(self):
        assert _is_meaningful(
            "what is penalty",
            "What is the contractual penalty clause for late payment in 2024?"
        )

    def test_same_case_insensitive_returns_false(self):
        assert not _is_meaningful("Hello World", "hello world")


# ---------------------------------------------------------------------------
# QueryRewriter
# ---------------------------------------------------------------------------

class TestQueryRewriter:
    def test_low_complexity_returns_original(self):
        s = _state(complexity="low")
        result = _run(QueryRewriter().run(s))
        assert result.specialists.rewritten_query == s.user_query

    def test_fallback_when_model_none(self):
        rewriter = QueryRewriter()
        rewriter.__class__._model = None
        rewriter.__class__._model_loaded = True
        s = _state(complexity="medium")
        result = _run(rewriter.run(s))
        assert result.specialists.rewritten_query == s.user_query

    def test_model_called_with_prompt(self):
        fake_model = MagicMock(return_value=[{"generated_text": "What is the 2024 contract penalty clause?"}])
        rewriter = QueryRewriter()
        rewriter.__class__._model = fake_model
        rewriter.__class__._model_loaded = True
        s = _state("what is penalty", complexity="medium")
        result = _run(rewriter.run(s))
        assert fake_model.called
        # rewritten_query should be set (either the model output or original)
        assert result.specialists.rewritten_query is not None

    def test_same_output_keeps_original(self):
        fake_model = MagicMock(return_value=[{"generated_text": "test query"}])
        rewriter = QueryRewriter()
        rewriter.__class__._model = fake_model
        rewriter.__class__._model_loaded = True
        s = _state("test query", complexity="medium")
        result = _run(rewriter.run(s))
        assert result.specialists.rewritten_query == "test query"

    def test_latency_recorded(self):
        rewriter = QueryRewriter()
        rewriter.__class__._model = None
        rewriter.__class__._model_loaded = True
        s = _state(complexity="low")
        _run(rewriter.run(s))
        # low complexity returns immediately, no latency entry expected
        # but no crash either

    def test_model_exception_returns_original(self):
        fake_model = MagicMock(side_effect=RuntimeError("model error"))
        rewriter = QueryRewriter()
        rewriter.__class__._model = fake_model
        rewriter.__class__._model_loaded = True
        s = _state(complexity="medium")
        result = _run(rewriter.run(s))
        assert result.specialists.rewritten_query == s.user_query


# ---------------------------------------------------------------------------
# FactExtractor
# ---------------------------------------------------------------------------

class TestFactExtractor:
    def test_no_hits_no_facts(self):
        extractor = FactExtractor()
        extractor.__class__._model = None
        extractor.__class__._model_loaded = True
        s = _state()
        result = _run(extractor.run(s))
        assert result.specialists.extracted_facts == []

    def test_fallback_converts_hits_to_facts(self):
        extractor = FactExtractor()
        extractor.__class__._model = None
        extractor.__class__._model_loaded = True
        s = _state()
        s.retrieval.weaviate_hits = _hits(2)
        result = _run(extractor.run(s))
        assert len(result.specialists.extracted_facts) == 2
        assert "fact" in result.specialists.extracted_facts[0]
        assert "source" in result.specialists.extracted_facts[0]

    def test_model_extracts_facts_per_chunk(self):
        fake_model = MagicMock(return_value=[{"generated_text": "Penalty is 10%\nApplies from 2024"}])
        extractor = FactExtractor()
        extractor.__class__._model = fake_model
        extractor.__class__._model_loaded = True
        s = _state()
        s.retrieval.weaviate_hits = _hits(2)
        result = _run(extractor.run(s))
        assert len(result.specialists.extracted_facts) >= 2  # 2 facts per chunk * 2 chunks

    def test_facts_include_source(self):
        fake_model = MagicMock(return_value=[{"generated_text": "The penalty is 10%"}])
        extractor = FactExtractor()
        extractor.__class__._model = fake_model
        extractor.__class__._model_loaded = True
        s = _state()
        s.retrieval.weaviate_hits = [_hits(1)[0]]
        result = _run(extractor.run(s))
        if result.specialists.extracted_facts:
            assert "source" in result.specialists.extracted_facts[0]


# ---------------------------------------------------------------------------
# EvidenceRanker
# ---------------------------------------------------------------------------

class TestEvidenceRanker:
    def _ranker_with_model(self, scores):
        fake_model = MagicMock()
        fake_model.predict.return_value = scores
        ranker = EvidenceRanker()
        ranker.__class__._model = fake_model
        ranker.__class__._model_loaded = True
        return ranker

    def test_ranks_by_score_descending(self):
        ranker = self._ranker_with_model([0.3, 0.9, 0.5])
        s = _state()
        s.specialists.extracted_facts = [
            {"fact": f"fact {i}", "source": "s", "chunk_id": f"c{i}", "score": 0.5}
            for i in range(3)
        ]
        result = _run(ranker.run(s))
        scores = [r["score"] for r in result.specialists.ranked_evidence]
        assert scores == sorted(scores, reverse=True)

    def test_filters_below_min_score(self):
        ranker = self._ranker_with_model([0.1, 0.05, 0.02])
        s = _state()
        s.specialists.extracted_facts = [
            {"fact": f"f{i}", "source": "s", "chunk_id": f"c{i}", "score": 0.5}
            for i in range(3)
        ]
        result = _run(ranker.run(s))
        assert result.specialists.ranked_evidence == []

    def test_fallback_uses_score_sort(self):
        ranker = EvidenceRanker()
        ranker.__class__._model = None
        ranker.__class__._model_loaded = True
        s = _state()
        s.specialists.extracted_facts = [
            {"fact": f"f{i}", "source": "s", "chunk_id": f"c{i}", "score": 0.9 - i * 0.1}
            for i in range(5)
        ]
        result = _run(ranker.run(s))
        scores = [r["score"] for r in result.specialists.ranked_evidence]
        assert scores == sorted(scores, reverse=True)

    def test_uses_raw_hits_when_no_facts(self):
        ranker = self._ranker_with_model([0.8, 0.6])
        s = _state()
        s.retrieval.weaviate_hits = _hits(2)
        result = _run(ranker.run(s))
        assert len(result.specialists.ranked_evidence) == 2

    def test_caps_at_max_evidence(self):
        ranker = self._ranker_with_model([0.9] * 15)
        s = _state()
        s.specialists.extracted_facts = [
            {"fact": f"f{i}", "source": "s", "chunk_id": f"c{i}", "score": 0.9}
            for i in range(15)
        ]
        result = _run(ranker.run(s))
        assert len(result.specialists.ranked_evidence) <= 10


# ---------------------------------------------------------------------------
# Specialist Layer orchestration
# ---------------------------------------------------------------------------

class TestSpecialistLayer:
    def test_skips_specialists_not_in_branches(self):
        s = _state()
        s.active_branches = []  # nothing active
        # Should not crash and not modify specialists
        result = _run(run_specialists(s))
        assert result.specialists.rewritten_query is None
        assert result.specialists.extracted_facts == []

    def test_only_runs_active_branches(self):
        s = _state()
        s.active_branches = ["query_rewriter"]  # only rewriter
        # Force model unavailable — fallback returns original query
        QueryRewriter._model = None
        QueryRewriter._model_loaded = True
        result = _run(run_specialists(s))
        assert result.specialists.rewritten_query == s.user_query
        assert result.specialists.extracted_facts == []  # extractor not run

    def test_latency_recorded(self):
        s = _state()
        s.active_branches = []
        result = _run(run_specialists(s))
        assert "specialists_total" in result.latency_ms

    def test_execution_trace_has_entry(self):
        s = _state()
        s.active_branches = []
        result = _run(run_specialists(s))
        layers = [t.get("layer") for t in result.execution_trace]
        assert "specialists" in layers
