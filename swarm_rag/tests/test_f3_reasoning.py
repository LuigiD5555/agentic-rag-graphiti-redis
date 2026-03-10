"""
Tests for F3 Reasoning/Integration Layer and Generator.

All external calls (LLM, SentenceTransformer) are mocked.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from swarm_rag.schemas.blackboard_schema import (
    BlackboardState, PerceptionOutput, SpecialistOutput, RetrievalOutput,
)
from swarm_rag.reasoning.confidence_estimator import (
    estimate_confidence, _heuristic_confidence, _cosine,
)
from swarm_rag.reasoning.integration_layer import run_integration
from swarm_rag.generator.prompt_builder import build_prompt, load_generator_params
from swarm_rag.generator.slm_verbalizer import SLMVerbalizer


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _state(complexity="low", intent="research", tone="neutral") -> BlackboardState:
    s = BlackboardState.new_session("¿Cuál es la penalización del contrato vigente?")
    s.perception = PerceptionOutput(complexity=complexity, intent=intent, tone=tone)
    return s


def _evidence(n=3, score=0.8):
    return [
        {"fact": f"El contrato establece penalización del {i*5}%",
         "source": f"doc{i}.pdf", "chunk_id": f"c{i}", "score": score - i * 0.05}
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# Cosine similarity helper
# ---------------------------------------------------------------------------

class TestCosine:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert abs(_cosine(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine(a, b)) < 1e-6

    def test_zero_vector_returns_zero(self):
        assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# Heuristic confidence
# ---------------------------------------------------------------------------

class TestHeuristicConfidence:
    def test_empty_evidence_returns_low(self):
        assert _heuristic_confidence([]) == 0.2

    def test_high_score_evidence_returns_high(self):
        ev = [{"score": 0.9} for _ in range(5)]
        result = _heuristic_confidence(ev)
        assert result > 0.8

    def test_low_score_evidence_returns_low(self):
        ev = [{"score": 0.1} for _ in range(2)]
        result = _heuristic_confidence(ev)
        assert result < 0.4

    def test_capped_at_0_85(self):
        ev = [{"score": 1.0} for _ in range(10)]
        assert _heuristic_confidence(ev) <= 0.85


# ---------------------------------------------------------------------------
# Confidence estimator (mocked SentenceTransformer)
# ---------------------------------------------------------------------------

class TestEstimateConfidence:
    def test_empty_evidence_returns_zero(self):
        assert estimate_confidence("query", [], []) == 0.0

    def test_conflict_penalty_applied(self):
        ev = _evidence(3, 0.8)
        conflicts = [{"description": "conflict 1"}, {"description": "conflict 2"}]
        score_no_conflict = estimate_confidence("query", ev, [])
        score_with_conflict = estimate_confidence("query", ev, conflicts)
        assert score_with_conflict < score_no_conflict

    def test_heuristic_used_when_no_model(self):
        import swarm_rag.reasoning.confidence_estimator as ce
        with patch.object(ce, "_model", None):
            with patch.object(ce, "_model_tried", True):
                result = estimate_confidence("query", _evidence(3), [])
        assert 0.0 < result <= 1.0

    def test_semantic_used_when_model_available(self):
        import swarm_rag.reasoning.confidence_estimator as ce
        mock_model = MagicMock()
        mock_model.encode.return_value = [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2], [0.7, 0.3]]
        with patch.object(ce, "_model", mock_model):
            result = estimate_confidence("query about penalty", _evidence(3), [])
        assert mock_model.encode.called
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# Integration Layer
# ---------------------------------------------------------------------------

class TestIntegrationLayer:
    def test_builds_structured_answer_from_evidence(self):
        s = _state()
        s.specialists.ranked_evidence = _evidence(3)
        result = _run(run_integration(s))
        assert result.reasoning.structured_answer
        assert "penalización" in result.reasoning.structured_answer.lower() or "contrato" in result.reasoning.structured_answer.lower()

    def test_confidence_computed(self):
        s = _state()
        s.specialists.ranked_evidence = _evidence(3)
        result = _run(run_integration(s))
        assert 0.0 <= result.reasoning.confidence_score <= 1.0

    def test_empty_evidence_produces_empty_answer(self):
        s = _state()
        result = _run(run_integration(s))
        assert result.reasoning.structured_answer == ""

    def test_escalation_when_low_confidence(self):
        import swarm_rag.reasoning.confidence_estimator as ce
        with patch.object(ce, "_model", None), patch.object(ce, "_model_tried", True):
            s = _state()
            # No evidence → confidence=0 → escalate
            result = _run(run_integration(s))
        assert result.reasoning.escalate_to_llm is True

    def test_no_escalation_when_good_evidence(self):
        import swarm_rag.reasoning.confidence_estimator as ce
        with patch.object(ce, "_model", None), patch.object(ce, "_model_tried", True):
            s = _state()
            s.specialists.ranked_evidence = [{"fact": "clear fact", "score": 0.95, "source": "s"}] * 5
            result = _run(run_integration(s))
        # heuristic: avg=0.95 + bonus → well above 0.6
        assert result.reasoning.escalate_to_llm is False

    def test_version_conflicts_trigger_escalation(self):
        import swarm_rag.reasoning.confidence_estimator as ce
        with patch.object(ce, "_model", None), patch.object(ce, "_model_tried", True):
            s = _state()
            s.specialists.ranked_evidence = _evidence(3, 0.9)
            s.retrieval.version_conflicts = [{"d": "c1"}, {"d": "c2"}, {"d": "c3"}]
            result = _run(run_integration(s))
        assert result.reasoning.escalate_to_llm is True  # 3 conflicts > max=2

    def test_math_result_in_answer(self):
        s = _state()
        s.specialists.math_result = 42.0
        result = _run(run_integration(s))
        assert "42.0" in result.reasoning.structured_answer

    def test_latency_recorded(self):
        s = _state()
        result = _run(run_integration(s))
        assert "reasoning" in result.latency_ms

    def test_key_points_populated(self):
        s = _state()
        s.specialists.ranked_evidence = _evidence(3)
        result = _run(run_integration(s))
        assert isinstance(result.reasoning.key_points, list)

    def test_high_complexity_adds_outline(self):
        s = _state(complexity="high")
        s.specialists.ranked_evidence = _evidence(3)
        result = _run(run_integration(s))
        if result.reasoning.key_points:
            assert "OUTLINE" in result.reasoning.structured_answer


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

class TestPromptBuilder:
    def test_returns_two_strings(self):
        s = _state()
        s.reasoning.structured_answer = "HECHOS: el contrato dice X"
        sys_p, user_msg = build_prompt(s)
        assert isinstance(sys_p, str) and len(sys_p) > 10
        assert isinstance(user_msg, str) and len(user_msg) > 10

    def test_formal_tone_uses_formal_system(self):
        s = _state(tone="formal")
        s.reasoning.structured_answer = "HECHOS: fact"
        sys_p, _ = build_prompt(s)
        assert "formal" in sys_p.lower() or "profesional" in sys_p.lower()

    def test_evidence_in_user_message(self):
        s = _state()
        s.reasoning.structured_answer = "HECHOS: penalización del 10%"
        _, user_msg = build_prompt(s)
        assert "penalización del 10%" in user_msg

    def test_query_in_user_message(self):
        s = _state()
        s.reasoning.structured_answer = "HECHOS: fact"
        _, user_msg = build_prompt(s)
        assert s.user_query in user_msg

    def test_escalation_note_added(self):
        s = _state()
        s.reasoning.structured_answer = "HECHOS: fact"
        s.reasoning.escalate_to_llm = True
        s.reasoning.confidence_score = 0.3
        _, user_msg = build_prompt(s)
        assert "confianza" in user_msg.lower() or "NOTA" in user_msg

    def test_load_generator_params_returns_dict(self):
        params = load_generator_params()
        assert "temperature" in params
        assert "max_tokens" in params
        assert 0.0 < params["temperature"] < 1.0


# ---------------------------------------------------------------------------
# SLM Verbalizer
# ---------------------------------------------------------------------------

class TestSLMVerbalizer:
    def _make_verbalizer(self, response="La penalización es del 10%."):
        chat = MagicMock()
        chat.chat.return_value = response
        return SLMVerbalizer(chat), chat

    def test_calls_chat_and_sets_final_response(self):
        v, chat = self._make_verbalizer()
        s = _state()
        s.reasoning.structured_answer = "HECHOS: penalización 10%"
        result = _run(v.run(s))
        assert chat.chat.called
        assert result.final_response == "La penalización es del 10%."

    def test_no_structured_answer_returns_fallback(self):
        v, chat = self._make_verbalizer()
        s = _state()
        result = _run(v.run(s))
        assert not chat.chat.called
        assert result.final_response  # fallback message

    def test_escalates_to_llm_api_when_flagged(self):
        chat = MagicMock()
        chat.chat.return_value = "local response"
        llm_api = MagicMock()
        llm_api.chat.return_value = "api response"
        v = SLMVerbalizer(chat, llm_api)
        s = _state()
        s.reasoning.structured_answer = "HECHOS: fact"
        s.reasoning.escalate_to_llm = True
        result = _run(v.run(s))
        assert llm_api.chat.called
        assert not chat.chat.called
        assert result.final_response == "api response"

    def test_chat_exception_returns_fallback(self):
        chat = MagicMock()
        chat.chat.side_effect = RuntimeError("LLM down")
        v = SLMVerbalizer(chat)
        s = _state()
        s.reasoning.structured_answer = "HECHOS: fact"
        result = _run(v.run(s))
        assert result.final_response  # fallback, not crash

    def test_latency_recorded(self):
        v, _ = self._make_verbalizer()
        s = _state()
        s.reasoning.structured_answer = "HECHOS: fact"
        result = _run(v.run(s))
        assert "generator" in result.latency_ms
