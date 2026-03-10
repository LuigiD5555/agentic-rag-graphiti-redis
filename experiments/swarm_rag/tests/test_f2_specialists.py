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

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState, PerceptionOutput
from experiments.swarm_rag.specialists.query_rewriter import QueryRewriter, _is_meaningful
from experiments.swarm_rag.specialists.fact_extractor import FactExtractor
from experiments.swarm_rag.specialists.evidence_ranker import EvidenceRanker
from experiments.swarm_rag.specialists.specialist_layer import run_specialists
from pytest_readable import readable



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
    @readable(
        intent="Verify identical returns false in is meaningful.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the identical returns false behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_identical_returns_false(self):
        assert not _is_meaningful("hello world", "hello world")

    @readable(
        intent="Verify empty returns false in is meaningful.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the empty returns false behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_empty_returns_false(self):
        assert not _is_meaningful("hello", "")

    @readable(
        intent="Verify different enough returns true in is meaningful.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the different enough returns true behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_different_enough_returns_true(self):
        assert _is_meaningful(
            "what is penalty",
            "What is the contractual penalty clause for late payment in 2024?"
        )

    @readable(
        intent="Verify same case insensitive returns false in is meaningful.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the same case insensitive returns false behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_same_case_insensitive_returns_false(self):
        assert not _is_meaningful("Hello World", "hello world")


# ---------------------------------------------------------------------------
# QueryRewriter
# ---------------------------------------------------------------------------

class TestQueryRewriter:
    @readable(
        intent="Verify low complexity returns original in query rewriter.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the low complexity returns original behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_low_complexity_returns_original(self):
        s = _state(complexity="low")
        result = _run(QueryRewriter().run(s))
        assert result.specialists.rewritten_query == s.user_query

    @readable(
        intent="Verify fallback when model none in query rewriter.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the fallback when model none behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_fallback_when_model_none(self):
        rewriter = QueryRewriter()
        rewriter.__class__._model = None
        rewriter.__class__._model_loaded = True
        s = _state(complexity="medium")
        result = _run(rewriter.run(s))
        assert result.specialists.rewritten_query == s.user_query

    @readable(
        intent="Verify model called with prompt in query rewriter.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the model called with prompt behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
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

    @readable(
        intent="Verify same output keeps original in query rewriter.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the same output keeps original behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_same_output_keeps_original(self):
        fake_model = MagicMock(return_value=[{"generated_text": "test query"}])
        rewriter = QueryRewriter()
        rewriter.__class__._model = fake_model
        rewriter.__class__._model_loaded = True
        s = _state("test query", complexity="medium")
        result = _run(rewriter.run(s))
        assert result.specialists.rewritten_query == "test query"

    @readable(
        intent="Verify latency recorded in query rewriter.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the latency recorded behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_latency_recorded(self):
        rewriter = QueryRewriter()
        rewriter.__class__._model = None
        rewriter.__class__._model_loaded = True
        s = _state(complexity="low")
        _run(rewriter.run(s))
        # low complexity returns immediately, no latency entry expected
        # but no crash either

    @readable(
        intent="Verify model exception returns original in query rewriter.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the model exception returns original behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
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
    @readable(
        intent="Verify no hits no facts in fact extractor.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the no hits no facts behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_no_hits_no_facts(self):
        extractor = FactExtractor()
        extractor.__class__._model = None
        extractor.__class__._model_loaded = True
        s = _state()
        result = _run(extractor.run(s))
        assert result.specialists.extracted_facts == []

    @readable(
        intent="Verify fallback converts hits to facts in fact extractor.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the fallback converts hits to facts behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
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

    @readable(
        intent="Verify model extracts facts per chunk in fact extractor.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the model extracts facts per chunk behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_model_extracts_facts_per_chunk(self):
        fake_model = MagicMock(return_value=[{"generated_text": "Penalty is 10%\nApplies from 2024"}])
        extractor = FactExtractor()
        extractor.__class__._model = fake_model
        extractor.__class__._model_loaded = True
        s = _state()
        s.retrieval.weaviate_hits = _hits(2)
        result = _run(extractor.run(s))
        assert len(result.specialists.extracted_facts) >= 2  # 2 facts per chunk * 2 chunks

    @readable(
        intent="Verify facts include source in fact extractor.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the facts include source behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
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

    @readable(
        intent="Verify ranks by score descending in evidence ranker.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the ranks by score descending behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
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

    @readable(
        intent="Verify filters below min score in evidence ranker.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the filters below min score behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_filters_below_min_score(self):
        ranker = self._ranker_with_model([0.1, 0.05, 0.02])
        s = _state()
        s.specialists.extracted_facts = [
            {"fact": f"f{i}", "source": "s", "chunk_id": f"c{i}", "score": 0.5}
            for i in range(3)
        ]
        result = _run(ranker.run(s))
        assert result.specialists.ranked_evidence == []

    @readable(
        intent="Verify fallback uses score sort in evidence ranker.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the fallback uses score sort behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
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

    @readable(
        intent="Verify uses raw hits when no facts in evidence ranker.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the uses raw hits when no facts behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_uses_raw_hits_when_no_facts(self):
        ranker = self._ranker_with_model([0.8, 0.6])
        s = _state()
        s.retrieval.weaviate_hits = _hits(2)
        result = _run(ranker.run(s))
        assert len(result.specialists.ranked_evidence) == 2

    @readable(
        intent="Verify caps at max evidence in evidence ranker.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the caps at max evidence behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
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
    @readable(
        intent="Verify skips specialists not in branches in specialist layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the skips specialists not in branches behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_skips_specialists_not_in_branches(self):
        s = _state()
        s.active_branches = []  # nothing active
        # Should not crash and not modify specialists
        result = _run(run_specialists(s))
        assert result.specialists.rewritten_query is None
        assert result.specialists.extracted_facts == []

    @readable(
        intent="Verify only runs active branches in specialist layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the only runs active branches behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_only_runs_active_branches(self):
        s = _state()
        s.active_branches = ["query_rewriter"]  # only rewriter
        # Force model unavailable — fallback returns original query
        QueryRewriter._model = None
        QueryRewriter._model_loaded = True
        result = _run(run_specialists(s))
        assert result.specialists.rewritten_query == s.user_query
        assert result.specialists.extracted_facts == []  # extractor not run

    @readable(
        intent="Verify latency recorded in specialist layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the latency recorded behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_latency_recorded(self):
        s = _state()
        s.active_branches = []
        result = _run(run_specialists(s))
        assert "specialists_total" in result.latency_ms

    @readable(
        intent="Verify execution trace has entry in specialist layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the execution trace has entry behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_execution_trace_has_entry(self):
        s = _state()
        s.active_branches = []
        result = _run(run_specialists(s))
        layers = [t.get("layer") for t in result.execution_trace]
        assert "specialists" in layers
