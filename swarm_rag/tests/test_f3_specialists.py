"""
Unit tests for F3 intermediate specialists.
All HF models are mocked — no downloads needed.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from swarm_rag.schemas.blackboard_schema import BlackboardState, PerceptionOutput
from swarm_rag.specialists.subquestion_generator import SubquestionGenerator, _SPLIT_PATTERNS
from swarm_rag.specialists.retrieval_planner import RetrievalPlanner
from swarm_rag.specialists.math_specialist import MathSpecialist, _try_eval
from swarm_rag.specialists.code_specialist import CodeSpecialist
from swarm_rag.specialists.hypothesis_generator import HypothesisGenerator
from swarm_rag.core.router import route
from pytest_readable import readable



def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _state(query="test", complexity="high", intent="research",
           needs_math=False, needs_code=False) -> BlackboardState:
    s = BlackboardState.new_session(query)
    s.perception = PerceptionOutput(
        complexity=complexity, intent=intent,
        needs_math=needs_math, needs_code=needs_code,
    )
    s.active_branches = [
        "subquestion_generator", "retrieval_planner",
        "math_specialist", "code_specialist",
        "fact_extractor", "hypothesis_generator",
        "evidence_ranker",
    ]
    return s


def _evidence(n=3):
    return [
        {"fact": f"El contrato {i} establece penalización del {i*5}%",
         "source": f"doc{i}.pdf", "chunk_id": f"c{i}", "score": 0.9 - i * 0.1}
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# SubquestionGenerator
# ---------------------------------------------------------------------------

class TestSubquestionGenerator:
    @readable(
        intent="Verify skips low complexity in subquestion generator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the skips low complexity behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_skips_low_complexity(self):
        s = _state(complexity="low")
        result = _run(SubquestionGenerator().run(s))
        assert result.specialists.subquestions == []

    @readable(
        intent="Verify skips medium complexity in subquestion generator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the skips medium complexity behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_skips_medium_complexity(self):
        s = _state(complexity="medium")
        result = _run(SubquestionGenerator().run(s))
        assert result.specialists.subquestions == []

    @readable(
        intent="Verify heuristic split on conjunction in subquestion generator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the heuristic split on conjunction behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_heuristic_split_on_conjunction(self):
        gen = SubquestionGenerator()
        gen.__class__._model = None
        gen.__class__._model_loaded = True
        s = _state("compara el contrato 2024 y además verifica la implementación Python")
        result = _run(gen.run(s))
        assert len(result.specialists.subquestions) >= 1

    @readable(
        intent="Verify model output parsed in subquestion generator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the model output parsed behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_model_output_parsed(self):
        fake = MagicMock(return_value=[{"generated_text": "1. ¿Cuál es el contrato?\n2. ¿Qué dice sobre penalizaciones?"}])
        gen = SubquestionGenerator()
        gen.__class__._model = fake
        gen.__class__._model_loaded = True
        s = _state("compara el contrato y verifica")
        result = _run(gen.run(s))
        assert len(result.specialists.subquestions) >= 1

    @readable(
        intent="Verify model exception falls back to heuristic in subquestion generator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the model exception falls back to heuristic behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_model_exception_falls_back_to_heuristic(self):
        fake = MagicMock(side_effect=RuntimeError("model error"))
        gen = SubquestionGenerator()
        gen.__class__._model = fake
        gen.__class__._model_loaded = True
        s = _state("compara el contrato 2024 y además verifica Python")
        result = _run(gen.run(s))
        assert isinstance(result.specialists.subquestions, list)

    @readable(
        intent="Verify max subquestions capped in subquestion generator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the max subquestions capped behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_max_subquestions_capped(self):
        fake = MagicMock(return_value=[{"generated_text": "\n".join([f"{i}. question {i}" for i in range(10)])}])
        gen = SubquestionGenerator()
        gen.__class__._model = fake
        gen.__class__._model_loaded = True
        s = _state("complex multi-part question")
        result = _run(gen.run(s))
        assert len(result.specialists.subquestions) <= 5


# ---------------------------------------------------------------------------
# RetrievalPlanner
# ---------------------------------------------------------------------------

class TestRetrievalPlanner:
    @readable(
        intent="Verify fallback plan from keywords in retrieval planner.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the fallback plan from keywords behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_fallback_plan_from_keywords(self):
        planner = RetrievalPlanner()
        planner.__class__._model = None
        planner.__class__._model_loaded = True
        s = _state("¿Cuál es la penalización del contrato vigente?")
        s.perception.keywords = ["penalización", "contrato", "vigente"]
        s.specialists.subquestions = ["¿Cuál es la penalización?", "¿Cuándo aplica?"]
        result = _run(planner.run(s))
        plan = result.specialists.retrieved_plan
        assert plan is not None
        assert "weaviate_queries" in plan
        assert len(plan["weaviate_queries"]) >= 1

    @readable(
        intent="Verify plan includes subquestions in retrieval planner.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the plan includes subquestions behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_plan_includes_subquestions(self):
        planner = RetrievalPlanner()
        planner.__class__._model = None
        planner.__class__._model_loaded = True
        s = _state()
        s.specialists.subquestions = ["sub1", "sub2"]
        result = _run(planner.run(s))
        plan = result.specialists.retrieved_plan
        assert any("sub1" in q or "sub2" in q for q in plan.get("weaviate_queries", []))

    @readable(
        intent="Verify model json output parsed in retrieval planner.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the model json output parsed behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_model_json_output_parsed(self):
        json_output = '{"weaviate_queries": ["penalización contrato"], "neo4j_focus": ["Contrato2024"], "memory_query": null}'
        fake = MagicMock(return_value=[{"generated_text": json_output}])
        planner = RetrievalPlanner()
        planner.__class__._model = fake
        planner.__class__._model_loaded = True
        s = _state("¿Cuál es la penalización?")
        result = _run(planner.run(s))
        plan = result.specialists.retrieved_plan
        assert "penalización contrato" in plan.get("weaviate_queries", [])

    @readable(
        intent="Verify latency recorded in retrieval planner.",
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
        planner = RetrievalPlanner()
        planner.__class__._model = None
        planner.__class__._model_loaded = True
        s = _state()
        result = _run(planner.run(s))
        assert "retrieval_planner" in result.latency_ms


# ---------------------------------------------------------------------------
# MathSpecialist
# ---------------------------------------------------------------------------

class TestMathSpecialist:
    @readable(
        intent="Verify skips when no math in math specialist.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the skips when no math behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_skips_when_no_math(self):
        s = _state(needs_math=False)
        result = _run(MathSpecialist().run(s))
        assert result.specialists.math_result is None

    @readable(
        intent="Verify percentage regex fallback in math specialist.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the percentage regex fallback behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_percentage_regex_fallback(self):
        spec = MathSpecialist()
        spec.__class__._model = None
        spec.__class__._model_loaded = True
        s = _state("calcula el 15% de 200", needs_math=True)
        result = _run(spec.run(s))
        assert result.specialists.math_result == pytest.approx(30.0, rel=1e-3)

    @readable(
        intent="Verify percentage with comma in math specialist.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the percentage with comma behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_percentage_with_comma(self):
        spec = MathSpecialist()
        spec.__class__._model = None
        spec.__class__._model_loaded = True
        s = _state("¿Cuánto es el 7,5% de 1000?", needs_math=True)
        result = _run(spec.run(s))
        assert result.specialists.math_result == pytest.approx(75.0, rel=1e-3)

    @readable(
        intent="Verify numbers extracted when no formula in math specialist.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the numbers extracted when no formula behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_numbers_extracted_when_no_formula(self):
        spec = MathSpecialist()
        spec.__class__._model = None
        spec.__class__._model_loaded = True
        s = _state("las cifras son 100, 200 y 300", needs_math=True)
        result = _run(spec.run(s))
        assert result.specialists.math_result is not None

    @readable(
        intent="Verify try eval simple in math specialist.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the try eval simple behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_try_eval_simple(self):
        assert _try_eval("2 + 3") == pytest.approx(5.0)
        assert _try_eval("10 / 4") == pytest.approx(2.5)
        assert _try_eval("invalid!!") is None

    @readable(
        intent="Verify latency recorded in math specialist.",
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
        spec = MathSpecialist()
        spec.__class__._model = None
        spec.__class__._model_loaded = True
        s = _state("el 10% de 500", needs_math=True)
        result = _run(spec.run(s))
        assert "math_specialist" in result.latency_ms


# ---------------------------------------------------------------------------
# CodeSpecialist
# ---------------------------------------------------------------------------

class TestCodeSpecialist:
    @readable(
        intent="Verify skips when no code in code specialist.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the skips when no code behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_skips_when_no_code(self):
        s = _state(needs_code=False)
        result = _run(CodeSpecialist().run(s))
        assert result.specialists.code_analysis is None

    @readable(
        intent="Verify regex detects python in code specialist.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the regex detects python behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_regex_detects_python(self):
        spec = CodeSpecialist()
        spec.__class__._model = None
        spec.__class__._model_loaded = True
        s = _state("hay un bug en el método Python de pago", needs_code=True)
        result = _run(spec.run(s))
        assert result.specialists.code_analysis["language"] == "Python"

    @readable(
        intent="Verify regex detects debug task in code specialist.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the regex detects debug task behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_regex_detects_debug_task(self):
        spec = CodeSpecialist()
        spec.__class__._model = None
        spec.__class__._model_loaded = True
        s = _state("el error ocurre en la función calcular()", needs_code=True)
        result = _run(spec.run(s))
        assert result.specialists.code_analysis["task_type"] == "debug"

    @readable(
        intent="Verify symbols extracted in code specialist.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the symbols extracted behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_symbols_extracted(self):
        spec = CodeSpecialist()
        spec.__class__._model = None
        spec.__class__._model_loaded = True
        s = _state("la clase PaymentService tiene un bug", needs_code=True)
        result = _run(spec.run(s))
        assert "PaymentService" in result.specialists.code_analysis["symbols"]

    @readable(
        intent="Verify tool hint present in code specialist.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the tool hint present behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_tool_hint_present(self):
        spec = CodeSpecialist()
        spec.__class__._model = None
        spec.__class__._model_loaded = True
        s = _state("revisa el diff del método Python", needs_code=True)
        result = _run(spec.run(s))
        assert "tool_hint" in result.specialists.code_analysis

    @readable(
        intent="Verify sql detected in code specialist.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the sql detected behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_sql_detected(self):
        spec = CodeSpecialist()
        spec.__class__._model = None
        spec.__class__._model_loaded = True
        s = _state("la query SELECT está fallando", needs_code=True)
        result = _run(spec.run(s))
        assert result.specialists.code_analysis["language"] == "SQL"

    @readable(
        intent="Verify latency recorded in code specialist.",
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
        spec = CodeSpecialist()
        spec.__class__._model = None
        spec.__class__._model_loaded = True
        s = _state("bug en Python", needs_code=True)
        result = _run(spec.run(s))
        assert "code_specialist" in result.latency_ms


# ---------------------------------------------------------------------------
# HypothesisGenerator
# ---------------------------------------------------------------------------

class TestHypothesisGenerator:
    @readable(
        intent="Verify skips when no evidence in hypothesis generator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the skips when no evidence behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_skips_when_no_evidence(self):
        s = _state()
        result = _run(HypothesisGenerator().run(s))
        assert result.specialists.hypotheses == []

    @readable(
        intent="Verify simple hypothesis from top evidence in hypothesis generator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the simple hypothesis from top evidence behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_simple_hypothesis_from_top_evidence(self):
        gen = HypothesisGenerator()
        gen.__class__._model = None
        gen.__class__._model_loaded = True
        s = _state()
        s.specialists.ranked_evidence = _evidence(2)
        result = _run(gen.run(s))
        assert len(result.specialists.hypotheses) >= 1
        assert result.specialists.hypotheses[0]  # not empty

    @readable(
        intent="Verify model output parsed in hypothesis generator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the model output parsed behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_model_output_parsed(self):
        fake = MagicMock(return_value=[{"generated_text": "La penalización es del 10%.\nEl cambio aplica desde 2024."}])
        gen = HypothesisGenerator()
        gen.__class__._model = fake
        gen.__class__._model_loaded = True
        s = _state()
        s.specialists.ranked_evidence = _evidence(3)
        result = _run(gen.run(s))
        assert len(result.specialists.hypotheses) >= 1

    @readable(
        intent="Verify max hypotheses capped in hypothesis generator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the max hypotheses capped behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_max_hypotheses_capped(self):
        fake = MagicMock(return_value=[{"generated_text": "\n".join([f"hypothesis {i}" for i in range(10)])}])
        gen = HypothesisGenerator()
        gen.__class__._model = fake
        gen.__class__._model_loaded = True
        s = _state()
        s.specialists.ranked_evidence = _evidence(3)
        result = _run(gen.run(s))
        assert len(result.specialists.hypotheses) <= 3

    @readable(
        intent="Verify uses rewritten query when available in hypothesis generator.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the uses rewritten query when available behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_uses_rewritten_query_when_available(self):
        fake = MagicMock(return_value=[{"generated_text": "La penalización vigente es del 8%."}])
        gen = HypothesisGenerator()
        gen.__class__._model = fake
        gen.__class__._model_loaded = True
        s = _state()
        s.specialists.rewritten_query = "¿Cuál es la tasa de penalización vigente?"
        s.specialists.ranked_evidence = _evidence(2)
        _run(gen.run(s))
        call_args = fake.call_args[0][0]
        assert "tasa de penalización vigente" in call_args

    @readable(
        intent="Verify latency recorded in hypothesis generator.",
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
        gen = HypothesisGenerator()
        gen.__class__._model = None
        gen.__class__._model_loaded = True
        s = _state()
        s.specialists.ranked_evidence = _evidence(2)
        result = _run(gen.run(s))
        assert "hypothesis_generator" in result.latency_ms


# ---------------------------------------------------------------------------
# Router — F3 branches
# ---------------------------------------------------------------------------

class TestRouterF3Branches:
    def _state_with_perception(self, complexity, needs_math=False, needs_code=False):
        s = BlackboardState.new_session("test")
        s.perception = PerceptionOutput(complexity=complexity, needs_math=needs_math, needs_code=needs_code)
        return s

    @readable(
        intent="Verify high complexity adds subquestion and planner in router f3 branches.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the high complexity adds subquestion and planner behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_high_complexity_adds_subquestion_and_planner(self):
        s = self._state_with_perception("high")
        active = route(s)
        assert "subquestion_generator" in active
        assert "retrieval_planner" in active

    @readable(
        intent="Verify medium complexity does not add planner in router f3 branches.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the medium complexity does not add planner behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_medium_complexity_does_not_add_planner(self):
        s = self._state_with_perception("medium")
        active = route(s)
        assert "subquestion_generator" not in active
        assert "retrieval_planner" not in active

    @readable(
        intent="Verify medium adds fact extractor and hypothesis in router f3 branches.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the medium adds fact extractor and hypothesis behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_medium_adds_fact_extractor_and_hypothesis(self):
        s = self._state_with_perception("medium")
        active = route(s)
        assert "fact_extractor" in active
        assert "hypothesis_generator" in active

    @readable(
        intent="Verify math adds math specialist in router f3 branches.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the math adds math specialist behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_math_adds_math_specialist(self):
        s = self._state_with_perception("low", needs_math=True)
        active = route(s)
        assert "math_specialist" in active

    @readable(
        intent="Verify code adds code specialist in router f3 branches.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the code adds code specialist behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_code_adds_code_specialist(self):
        s = self._state_with_perception("low", needs_code=True)
        active = route(s)
        assert "code_specialist" in active
