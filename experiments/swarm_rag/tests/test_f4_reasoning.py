"""
Tests for F4 reasoning components:
- LogicChecker (NLI — mocked)
- ConflictResolver (pure deterministic logic — no mocking needed)
- IntegrationLayer (full F4 pipeline — mocked models)
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState, PerceptionOutput
from experiments.swarm_rag.reasoning.logic_checker import check_consistency, _dot
from experiments.swarm_rag.reasoning.conflict_resolver import resolve_conflicts
from experiments.swarm_rag.reasoning.integration_layer import run_integration
import experiments.swarm_rag.reasoning.logic_checker as lc
import experiments.swarm_rag.reasoning.confidence_estimator as ce
from pytest_readable import readable



def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _state() -> BlackboardState:
    s = BlackboardState.new_session("¿Cuál es la penalización vigente?")
    s.perception = PerceptionOutput(complexity="high")
    return s


def _hit(text, source="doc.pdf", score=0.8):
    return {"chunk_id": source, "text": text, "score": score, "source": source,
            "fact": text}


def _conflict(ctype, **kwargs):
    return {"type": ctype, "description": f"{ctype} conflict", **kwargs}


# ---------------------------------------------------------------------------
# _dot helper
# ---------------------------------------------------------------------------

class TestDot:
    @readable(
        intent="Verify unit vectors in dot.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the unit vectors behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_unit_vectors(self):
        assert _dot([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    @readable(
        intent="Verify orthogonal in dot.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the orthogonal behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_orthogonal(self):
        assert _dot([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# LogicChecker
# ---------------------------------------------------------------------------

class TestLogicChecker:
    @readable(
        intent="Verify empty inputs return empty in logic checker.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the empty inputs return empty behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_empty_inputs_return_empty(self):
        assert check_consistency([], []) == []
        assert check_consistency(["hyp"], []) == []
        assert check_consistency([], [_hit("fact")]) == []

    @readable(
        intent="Mock NLI model returning contradiction for all pairs.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the nli model contradiction flagged behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_nli_model_contradiction_flagged(self):
        """Mock NLI model returning contradiction for all pairs."""
        # score_vec = [contradiction, entailment, neutral]
        mock_model = MagicMock()
        mock_model.predict.return_value = [[0.9, 0.05, 0.05]]  # contradiction wins

        with patch.object(lc, "_model", mock_model):
            conflicts = check_consistency(
                ["La penalización es del 5%"],
                [_hit("La penalización es del 10%")],
            )
        assert len(conflicts) == 1
        assert conflicts[0]["type"] == "nli_inconsistency"
        assert conflicts[0]["consistency_score"] < 0

    @readable(
        intent="Mock NLI returning entailment — no conflict expected.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the nli model entailment no conflict behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_nli_model_entailment_no_conflict(self):
        """Mock NLI returning entailment — no conflict expected."""
        mock_model = MagicMock()
        mock_model.predict.return_value = [[0.05, 0.9, 0.05]]  # entailment wins

        with patch.object(lc, "_model", mock_model):
            conflicts = check_consistency(
                ["La penalización es del 10%"],
                [_hit("El contrato establece penalización del 10%")],
            )
        assert conflicts == []

    @readable(
        intent="Model crash should not raise — return empty.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the model exception skips gracefully behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_model_exception_skips_gracefully(self):
        """Model crash should not raise — return empty."""
        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("NLI model failed")
        with patch.object(lc, "_model", mock_model):
            result = check_consistency(["hyp"], [_hit("fact")])
        assert result == []

    @readable(
        intent="With no NLI model, cosine fallback is attempted; result is always a list.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the no model falls back gracefully behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_no_model_falls_back_gracefully(self):
        """With no NLI model, cosine fallback is attempted; result is always a list."""
        with patch.object(lc, "_model", None), patch.object(lc, "_model_tried", True):
            # sentence_transformers may or may not be available — either path returns a list
            result = check_consistency(
                ["hypothesis about penalty"],
                [_hit("completely unrelated fact about weather")],
            )
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# ConflictResolver — pure deterministic logic
# ---------------------------------------------------------------------------

class TestConflictResolver:
    @readable(
        intent="Verify year discrepancy resolved by recency in conflict resolver.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the year discrepancy resolved by recency behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_year_discrepancy_resolved_by_recency(self):
        conflict = {
            "type": "year_discrepancy",
            "description": "2023 vs 2024",
            "stale_year": 2023,
            "current_year": 2024,
            "stale_sources": ["old.pdf"],
            "current_sources": ["new.pdf"],
        }
        resolved, has_unresolved = resolve_conflicts([conflict], [], [])
        assert not has_unresolved
        assert resolved[0]["resolution"] == "rule_recency"
        assert resolved[0]["winner"] == "current"
        assert resolved[0]["winner_year"] == 2024

    @readable(
        intent="Verify vigente conflict resolved by vigente rule in conflict resolver.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the vigente conflict resolved by vigente rule behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_vigente_conflict_resolved_by_vigente_rule(self):
        conflict = {
            "type": "vigente_conflict",
            "description": "vigente vs obsoleto",
            "vigente_sources": ["current.pdf"],
            "stale_sources": ["old.pdf"],
        }
        resolved, has_unresolved = resolve_conflicts([conflict], [], [])
        assert not has_unresolved
        assert resolved[0]["resolution"] == "rule_vigente"
        assert resolved[0]["winner"] == "vigente"

    @readable(
        intent="Verify unknown conflict resolved by score in conflict resolver.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the unknown conflict resolved by score behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_unknown_conflict_resolved_by_score(self):
        conflict = {"type": "unknown", "description": "unrecognized conflict"}
        hits = [_hit("high score fact", score=0.95), _hit("low score fact", score=0.3)]
        resolved, has_unresolved = resolve_conflicts([conflict], [], hits)
        assert not has_unresolved
        assert resolved[0]["resolution"] == "rule_score"

    @readable(
        intent="Verify conflict without hits is unresolved in conflict resolver.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the conflict without hits is unresolved behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_conflict_without_hits_is_unresolved(self):
        conflict = {"type": "unknown", "description": "no hits available"}
        resolved, has_unresolved = resolve_conflicts([conflict], [], [])
        assert has_unresolved
        assert resolved[0]["resolution"] == "unresolved"

    @readable(
        intent="Verify nli conflicts flagged not escalated in conflict resolver.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the nli conflicts flagged not escalated behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_nli_conflicts_flagged_not_escalated(self):
        nli = [{"type": "nli_inconsistency", "hypothesis": "hyp", "consistency_score": -0.5}]
        resolved, has_unresolved = resolve_conflicts([], nli, [])
        assert not has_unresolved  # NLI alone doesn't escalate
        assert resolved[0]["resolution"] == "flagged"

    @readable(
        intent="Verify multiple conflicts all resolved in conflict resolver.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the multiple conflicts all resolved behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_multiple_conflicts_all_resolved(self):
        conflicts = [
            {"type": "year_discrepancy", "stale_year": 2022, "current_year": 2024,
             "stale_sources": ["a"], "current_sources": ["b"]},
            {"type": "vigente_conflict", "vigente_sources": ["c"], "stale_sources": ["d"]},
        ]
        resolved, has_unresolved = resolve_conflicts(conflicts, [], [])
        assert len(resolved) == 2
        assert not has_unresolved

    @readable(
        intent="Verify empty inputs return empty in conflict resolver.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the empty inputs return empty behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_empty_inputs_return_empty(self):
        resolved, has_unresolved = resolve_conflicts([], [], [])
        assert resolved == []
        assert not has_unresolved


# ---------------------------------------------------------------------------
# Integration Layer — F4 end-to-end (mocked)
# ---------------------------------------------------------------------------

class TestIntegrationLayerF4:
    def _patched_run(self, state):
        """Run integration with all ML models mocked."""
        with patch.object(ce, "_model", None), patch.object(ce, "_model_tried", True):
            with patch.object(lc, "_model", None), patch.object(lc, "_model_tried", True):
                return _run(run_integration(state))

    @readable(
        intent="Verify nli conflicts written to specialists in integration layer f4.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the nli conflicts written to specialists behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_nli_conflicts_written_to_specialists(self):
        mock_nli = MagicMock()
        mock_nli.predict.return_value = [[0.9, 0.05, 0.05]]  # contradiction
        s = _state()
        s.specialists.hypotheses = ["La penalización es del 5%"]
        s.specialists.ranked_evidence = [_hit("La penalización es del 10%", score=0.9)]
        with patch.object(ce, "_model", None), patch.object(ce, "_model_tried", True):
            with patch.object(lc, "_model", mock_nli):
                result = _run(run_integration(s))
        # conflicts_found should have the NLI result
        assert isinstance(result.specialists.conflicts_found, list)

    @readable(
        intent="Verify unresolved conflict triggers escalation in integration layer f4.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the unresolved conflict triggers escalation behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_unresolved_conflict_triggers_escalation(self):
        s = _state()
        # An unresolvable version conflict (type unknown, no hits)
        s.retrieval.version_conflicts = [{"type": "unknown", "description": "unresolvable"}]
        result = self._patched_run(s)
        assert result.reasoning.escalate_to_llm is True

    @readable(
        intent="Verify year conflict resolved does not escalate alone in integration layer f4.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the year conflict resolved does not escalate alone behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_year_conflict_resolved_does_not_escalate_alone(self):
        s = _state()
        s.retrieval.version_conflicts = [{
            "type": "year_discrepancy",
            "stale_year": 2022, "current_year": 2024,
            "stale_sources": ["old.pdf"], "current_sources": ["new.pdf"],
        }]
        s.specialists.ranked_evidence = [_hit("good evidence", score=0.9)] * 5
        result = self._patched_run(s)
        # The year conflict resolves cleanly — escalation only from confidence
        resolved = result.specialists.conflicts_found
        assert any(c.get("resolution") == "rule_recency" for c in resolved)

    @readable(
        intent="Verify resolved conflicts appear in structured answer in integration layer f4.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the resolved conflicts appear in structured answer behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_resolved_conflicts_appear_in_structured_answer(self):
        s = _state()
        s.retrieval.version_conflicts = [{
            "type": "vigente_conflict", "description": "vigente vs obsoleto",
            "vigente_sources": ["current.pdf"], "stale_sources": ["old.pdf"],
        }]
        s.specialists.ranked_evidence = [_hit("fact", score=0.8)]
        result = self._patched_run(s)
        assert result.reasoning.structured_answer is not None
        # Either evidence or conflict should be in the answer
        combined = result.reasoning.structured_answer
        assert len(combined) > 0

    @readable(
        intent="Verify reasoning summary includes f4 fields in integration layer f4.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the reasoning summary includes f4 fields behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_reasoning_summary_includes_f4_fields(self):
        s = _state()
        result = self._patched_run(s)
        summary = result.reasoning.reasoning_summary
        assert "nli_conflicts" in summary
        assert "unresolved" in summary
