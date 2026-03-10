"""
Tests for F1 Perception Layer detectors and perception_layer orchestrator.
No external dependencies required — all F1 implementations are regex/heuristic.
"""
from __future__ import annotations

import asyncio
import pytest

from swarm_rag.schemas.blackboard_schema import BlackboardState
from swarm_rag.perception.detectors import (
    detect_language, detect_math, detect_code,
    classify_intent, classify_domain, estimate_complexity,
    extract_entities, extract_keywords, classify_tone,
)
from swarm_rag.perception.perception_layer import run_perception


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Math detector
# ---------------------------------------------------------------------------

class TestMathDetector:
    def test_calcula_triggers_math(self):
        assert _run(detect_math("calcula el 15% de 200"))["needs_math"] is True

    def test_percent_symbol_triggers_math(self):
        assert _run(detect_math("¿Cuánto es el 30% de 500?"))["needs_math"] is True

    def test_arithmetic_expression_triggers_math(self):
        assert _run(detect_math("100 + 200 * 3"))["needs_math"] is True

    def test_general_query_no_math(self):
        assert _run(detect_math("¿Qué dice el contrato?"))["needs_math"] is False


# ---------------------------------------------------------------------------
# Code detector
# ---------------------------------------------------------------------------

class TestCodeDetector:
    def test_python_triggers_code(self):
        assert _run(detect_code("este método Python tiene un bug"))["needs_code"] is True

    def test_def_block_triggers_code(self):
        assert _run(detect_code("def calculate_penalty(rate):"))["needs_code"] is True

    def test_backtick_block_triggers_code(self):
        assert _run(detect_code("revisa `payment_service.py`"))["needs_code"] is True

    def test_general_query_no_code(self):
        assert _run(detect_code("¿Qué dice el contrato?"))["needs_code"] is False


# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------

class TestIntentClassifier:
    def test_math_intent(self):
        assert _run(classify_intent("calcula el resultado"))["intent"] == "math"

    def test_code_intent(self):
        assert _run(classify_intent("hay un bug en la función"))["intent"] == "code"

    def test_research_intent(self):
        assert _run(classify_intent("qué dice el contrato sobre"))["intent"] == "research"

    def test_memory_intent(self):
        assert _run(classify_intent("recuerdas la solución que aplicamos"))["intent"] == "memory"

    def test_general_fallback(self):
        assert _run(classify_intent("hola"))["intent"] == "general"


# ---------------------------------------------------------------------------
# Domain classifier
# ---------------------------------------------------------------------------

class TestDomainClassifier:
    def test_law_domain(self):
        assert _run(classify_domain("el contrato vigente establece"))["domain"] == "law"

    def test_finance_domain(self):
        assert _run(classify_domain("el precio y el IVA aplicable"))["domain"] == "finance"

    def test_tech_domain(self):
        assert _run(classify_domain("el algoritmo de la API"))["domain"] == "tech"

    def test_general_fallback(self):
        assert _run(classify_domain("el tiempo está bien hoy"))["domain"] == "general"


# ---------------------------------------------------------------------------
# Complexity estimator
# ---------------------------------------------------------------------------

class TestComplexityEstimator:
    def test_short_query_is_low(self):
        assert _run(estimate_complexity("¿qué es un contrato?"))["complexity"] == "low"

    def test_medium_query(self):
        assert _run(estimate_complexity(
            "compara el contrato 2024 con el vigente y explica las diferencias"
        ))["complexity"] in ("medium", "high")

    def test_long_query_is_high(self):
        long = " ".join(["palabra"] * 35)
        assert _run(estimate_complexity(long))["complexity"] == "high"

    def test_multiple_questions_raises_complexity(self):
        assert _run(estimate_complexity("¿qué dice? ¿cuándo aplica?"))["complexity"] in ("medium", "high")


# ---------------------------------------------------------------------------
# Keyword extractor
# ---------------------------------------------------------------------------

class TestKeywordExtractor:
    def test_extracts_long_words(self):
        result = _run(extract_keywords("contrato vigente penalización anual"))
        assert "contrato" in result["keywords"]
        assert "vigente" in result["keywords"]

    def test_stopwords_excluded(self):
        result = _run(extract_keywords("el contrato de los proveedores"))
        assert "contrato" in result["keywords"]
        for stop in ("el", "los", "de"):
            assert stop not in result["keywords"]

    def test_max_10_keywords(self):
        long = " ".join([f"palabra{i}larga" for i in range(20)])
        result = _run(extract_keywords(long))
        assert len(result["keywords"]) <= 10


# ---------------------------------------------------------------------------
# Tone classifier
# ---------------------------------------------------------------------------

class TestToneClassifier:
    def test_formal_tone(self):
        assert _run(classify_tone("según el presente contrato, mediante el cual"))["tone"] == "formal"

    def test_technical_tone(self):
        assert _run(classify_tone("implementa la función en el API endpoint"))["tone"] == "technical"

    def test_casual_tone(self):
        assert _run(classify_tone("hola, gracias por tu ayuda"))["tone"] == "casual"

    def test_neutral_fallback(self):
        assert _run(classify_tone("cuál es la respuesta"))["tone"] == "neutral"


# ---------------------------------------------------------------------------
# Full perception_layer orchestration
# ---------------------------------------------------------------------------

class TestPerceptionLayer:
    def test_perception_populates_all_fields(self):
        state = BlackboardState.new_session("calcula el 15% del contrato vigente")
        state = _run(run_perception(state.user_query, state))
        p = state.perception
        assert p.needs_math is True
        assert p.intent == "math"
        assert isinstance(p.language, str) and len(p.language) >= 2  # langdetect varies on short text
        assert p.complexity in ("low", "medium", "high")
        assert isinstance(p.keywords, list)

    def test_code_query_detected(self):
        state = BlackboardState.new_session("hay un bug en el método Python de pago")
        state = _run(run_perception(state.user_query, state))
        assert state.perception.needs_code is True
        assert state.perception.intent == "code"

    def test_latency_recorded(self):
        state = BlackboardState.new_session("test query para latencia")
        state = _run(run_perception(state.user_query, state))
        assert "perception" in state.latency_ms
        assert state.latency_ms["perception"] >= 0

    def test_execution_trace_entry(self):
        state = BlackboardState.new_session("test")
        state = _run(run_perception(state.user_query, state))
        layers = [t["layer"] for t in state.execution_trace]
        assert "perception" in layers

    def test_compound_math_and_code(self):
        state = BlackboardState.new_session(
            "calcula el descuento y corrige el bug en el método Python"
        )
        state = _run(run_perception(state.user_query, state))
        assert state.perception.needs_math is True
        assert state.perception.needs_code is True
