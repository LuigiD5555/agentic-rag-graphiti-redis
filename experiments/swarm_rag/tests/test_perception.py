"""
Tests for F1 Perception Layer detectors and perception_layer orchestrator.
No external dependencies required — all F1 implementations are regex/heuristic.
"""
from __future__ import annotations

import asyncio
import pytest

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState
from experiments.swarm_rag.perception.detectors import (
    detect_language, detect_math, detect_code,
    classify_intent, classify_domain, estimate_complexity,
    extract_entities, extract_keywords, classify_tone,
)
from experiments.swarm_rag.perception.perception_layer import run_perception
from pytest_readable import readable



def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Math detector
# ---------------------------------------------------------------------------

class TestMathDetector:
    @readable(
        intent="Verify calcula triggers math in math detector.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the calcula triggers math behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_calcula_triggers_math(self):
        assert _run(detect_math("calcula el 15% de 200"))["needs_math"] is True

    @readable(
        intent="Verify percent symbol triggers math in math detector.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the percent symbol triggers math behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_percent_symbol_triggers_math(self):
        assert _run(detect_math("¿Cuánto es el 30% de 500?"))["needs_math"] is True

    @readable(
        intent="Verify arithmetic expression triggers math in math detector.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the arithmetic expression triggers math behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_arithmetic_expression_triggers_math(self):
        assert _run(detect_math("100 + 200 * 3"))["needs_math"] is True

    @readable(
        intent="Verify general query no math in math detector.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the general query no math behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_general_query_no_math(self):
        assert _run(detect_math("¿Qué dice el contrato?"))["needs_math"] is False


# ---------------------------------------------------------------------------
# Code detector
# ---------------------------------------------------------------------------

class TestCodeDetector:
    @readable(
        intent="Verify python triggers code in code detector.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the python triggers code behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_python_triggers_code(self):
        assert _run(detect_code("este método Python tiene un bug"))["needs_code"] is True

    @readable(
        intent="Verify def block triggers code in code detector.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the def block triggers code behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_def_block_triggers_code(self):
        assert _run(detect_code("def calculate_penalty(rate):"))["needs_code"] is True

    @readable(
        intent="Verify backtick block triggers code in code detector.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the backtick block triggers code behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_backtick_block_triggers_code(self):
        assert _run(detect_code("revisa `payment_service.py`"))["needs_code"] is True

    @readable(
        intent="Verify general query no code in code detector.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the general query no code behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_general_query_no_code(self):
        assert _run(detect_code("¿Qué dice el contrato?"))["needs_code"] is False


# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------

class TestIntentClassifier:
    @readable(
        intent="Verify math intent in intent classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the math intent behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_math_intent(self):
        assert _run(classify_intent("calcula el resultado"))["intent"] == "math"

    @readable(
        intent="Verify code intent in intent classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the code intent behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_code_intent(self):
        assert _run(classify_intent("hay un bug en la función"))["intent"] == "code"

    @readable(
        intent="Verify research intent in intent classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the research intent behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_research_intent(self):
        assert _run(classify_intent("qué dice el contrato sobre"))["intent"] == "research"

    @readable(
        intent="Verify memory intent in intent classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the memory intent behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_memory_intent(self):
        assert _run(classify_intent("recuerdas la solución que aplicamos"))["intent"] == "memory"

    @readable(
        intent="Verify general fallback in intent classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the general fallback behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_general_fallback(self):
        assert _run(classify_intent("hola"))["intent"] == "general"


# ---------------------------------------------------------------------------
# Domain classifier
# ---------------------------------------------------------------------------

class TestDomainClassifier:
    @readable(
        intent="Verify law domain in domain classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the law domain behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_law_domain(self):
        assert _run(classify_domain("el contrato vigente establece"))["domain"] == "law"

    @readable(
        intent="Verify finance domain in domain classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the finance domain behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_finance_domain(self):
        assert _run(classify_domain("el precio y el IVA aplicable"))["domain"] == "finance"

    @readable(
        intent="Verify tech domain in domain classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the tech domain behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_tech_domain(self):
        assert _run(classify_domain("el algoritmo de la API"))["domain"] == "tech"

    @readable(
        intent="Verify general fallback in domain classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the general fallback behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_general_fallback(self):
        assert _run(classify_domain("el tiempo está bien hoy"))["domain"] == "general"


# ---------------------------------------------------------------------------
# Complexity estimator
# ---------------------------------------------------------------------------

class TestComplexityEstimator:
    @readable(
        intent="Verify short query is low in complexity estimator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the short query is low behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_short_query_is_low(self):
        assert _run(estimate_complexity("¿qué es un contrato?"))["complexity"] == "low"

    @readable(
        intent="Verify medium query in complexity estimator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the medium query behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_medium_query(self):
        assert _run(estimate_complexity(
            "compara el contrato 2024 con el vigente y explica las diferencias"
        ))["complexity"] in ("medium", "high")

    @readable(
        intent="Verify long query is high in complexity estimator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the long query is high behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_long_query_is_high(self):
        long = " ".join(["palabra"] * 35)
        assert _run(estimate_complexity(long))["complexity"] == "high"

    @readable(
        intent="Verify multiple questions raises complexity in complexity estimator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the multiple questions raises complexity behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_multiple_questions_raises_complexity(self):
        assert _run(estimate_complexity("¿qué dice? ¿cuándo aplica?"))["complexity"] in ("medium", "high")


# ---------------------------------------------------------------------------
# Keyword extractor
# ---------------------------------------------------------------------------

class TestKeywordExtractor:
    @readable(
        intent="Verify extracts long words in keyword extractor.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the extracts long words behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_extracts_long_words(self):
        result = _run(extract_keywords("contrato vigente penalización anual"))
        assert "contrato" in result["keywords"]
        assert "vigente" in result["keywords"]

    @readable(
        intent="Verify stopwords excluded in keyword extractor.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the stopwords excluded behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_stopwords_excluded(self):
        result = _run(extract_keywords("el contrato de los proveedores"))
        assert "contrato" in result["keywords"]
        for stop in ("el", "los", "de"):
            assert stop not in result["keywords"]

    @readable(
        intent="Verify max 10 keywords in keyword extractor.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the max 10 keywords behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_max_10_keywords(self):
        long = " ".join([f"palabra{i}larga" for i in range(20)])
        result = _run(extract_keywords(long))
        assert len(result["keywords"]) <= 10


# ---------------------------------------------------------------------------
# Tone classifier
# ---------------------------------------------------------------------------

class TestToneClassifier:
    @readable(
        intent="Verify formal tone in tone classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the formal tone behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_formal_tone(self):
        assert _run(classify_tone("según el presente contrato, mediante el cual"))["tone"] == "formal"

    @readable(
        intent="Verify technical tone in tone classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the technical tone behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_technical_tone(self):
        assert _run(classify_tone("implementa la función en el API endpoint"))["tone"] == "technical"

    @readable(
        intent="Verify casual tone in tone classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the casual tone behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_casual_tone(self):
        assert _run(classify_tone("hola, gracias por tu ayuda"))["tone"] == "casual"

    @readable(
        intent="Verify neutral fallback in tone classifier.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the neutral fallback behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_neutral_fallback(self):
        assert _run(classify_tone("cuál es la respuesta"))["tone"] == "neutral"


# ---------------------------------------------------------------------------
# Full perception_layer orchestration
# ---------------------------------------------------------------------------

class TestPerceptionLayer:
    @readable(
        intent="Verify perception populates all fields in perception layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the perception populates all fields behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_perception_populates_all_fields(self):
        state = BlackboardState.new_session("calcula el 15% del contrato vigente")
        state = _run(run_perception(state.user_query, state))
        p = state.perception
        assert p.needs_math is True
        assert p.intent == "math"
        assert isinstance(p.language, str) and len(p.language) >= 2  # langdetect varies on short text
        assert p.complexity in ("low", "medium", "high")
        assert isinstance(p.keywords, list)

    @readable(
        intent="Verify code query detected in perception layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the code query detected behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_code_query_detected(self):
        state = BlackboardState.new_session("hay un bug en el método Python de pago")
        state = _run(run_perception(state.user_query, state))
        assert state.perception.needs_code is True
        assert state.perception.intent == "code"

    @readable(
        intent="Verify latency recorded in perception layer.",
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
        state = BlackboardState.new_session("test query para latencia")
        state = _run(run_perception(state.user_query, state))
        assert "perception" in state.latency_ms
        assert state.latency_ms["perception"] >= 0

    @readable(
        intent="Verify execution trace entry in perception layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the execution trace entry behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_execution_trace_entry(self):
        state = BlackboardState.new_session("test")
        state = _run(run_perception(state.user_query, state))
        layers = [t["layer"] for t in state.execution_trace]
        assert "perception" in layers

    @readable(
        intent="Verify compound math and code in perception layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the compound math and code behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_compound_math_and_code(self):
        state = BlackboardState.new_session(
            "calcula el descuento y corrige el bug en el método Python"
        )
        state = _run(run_perception(state.user_query, state))
        assert state.perception.needs_math is True
        assert state.perception.needs_code is True
