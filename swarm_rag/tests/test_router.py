"""
Tests for core/router.py v2 — reads state.perception.
"""
from __future__ import annotations
import pytest
from swarm_rag.schemas.blackboard_schema import BlackboardState, PerceptionOutput
from swarm_rag.core.router import route
from pytest_readable import readable



def _state(intent="general", complexity="low", needs_math=False,
           needs_code=False, needs_retrieval=True) -> BlackboardState:
    s = BlackboardState.new_session("test query")
    s.perception = PerceptionOutput(
        intent=intent, complexity=complexity,
        needs_math=needs_math, needs_code=needs_code,
        needs_retrieval=needs_retrieval,
    )
    return s


class TestRouterAlwaysOn:
    @readable(
        intent="Verify always has retrieval and merger in router always on.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the always has retrieval and merger behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_always_has_retrieval_and_merger(self):
        active = route(_state())
        assert "retrieval_weaviate" in active
        assert "integration_layer" in active  # evidence_merger absorbed into integration_layer

    @readable(
        intent="Verify result written to state in router always on.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the result written to state behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_result_written_to_state(self):
        s = _state()
        route(s)
        assert s.active_branches  # non-empty

    @readable(
        intent="Verify no duplicates in router always on.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the no duplicates behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_no_duplicates(self):
        active = route(_state(complexity="high", needs_math=True))
        assert len(active) == len(set(active))


class TestComplexityRouting:
    @readable(
        intent="Verify low complexity no specialist in complexity routing.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the low complexity no specialist behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_low_complexity_no_specialist(self):
        active = route(_state(complexity="low"))
        assert "query_rewriter" not in active
        assert "subquestion_generator" not in active

    @readable(
        intent="Verify medium adds rewriter in complexity routing.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the medium adds rewriter behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_medium_adds_rewriter(self):
        active = route(_state(complexity="medium"))
        assert "query_rewriter" in active
        assert "subquestion_generator" not in active

    @readable(
        intent="Verify high adds rewriter and subquestions in complexity routing.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the high adds rewriter and subquestions behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_high_adds_rewriter_and_subquestions(self):
        active = route(_state(complexity="high"))
        assert "query_rewriter" in active
        assert "subquestion_generator" in active


class TestMathRouting:
    @readable(
        intent="Verify needs math adds math branches in math routing.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the needs math adds math branches behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_needs_math_adds_math_branches(self):
        active = route(_state(needs_math=True))
        assert "math_specialist" in active
        assert "math_specialist" in active  # math_tool_agent is stub, not activated

    @readable(
        intent="Verify no math no math branches in math routing.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the no math no math branches behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_no_math_no_math_branches(self):
        active = route(_state(needs_math=False))
        assert "math_specialist" not in active


class TestCodeRouting:
    @readable(
        intent="Verify needs code adds code branches in code routing.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the needs code adds code branches behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_needs_code_adds_code_branches(self):
        active = route(_state(needs_code=True))
        assert "code_specialist" in active
        assert "code_specialist" in active  # code_agent_mcp is stub, not activated

    @readable(
        intent="Verify no code no code branches in code routing.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the no code no code branches behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_no_code_no_code_branches(self):
        active = route(_state(needs_code=False))
        assert "code_specialist" not in active


class TestVersionConflictRouting:
    @readable(
        intent="Verify version conflicts add resolver in version conflict routing.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the version conflicts add resolver behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_version_conflicts_add_resolver(self):
        s = _state()
        s.retrieval.version_conflicts = [{"description": "conflict"}]
        active = route(s)
        assert "conflict_resolver" in active

    @readable(
        intent="Verify no conflicts no resolver in version conflict routing.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the no conflicts no resolver behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_no_conflicts_no_resolver(self):
        active = route(_state())
        assert "conflict_resolver" not in active


class TestReasoningAlwaysAdded:
    @readable(
        intent="Verify integration layer always present in reasoning always added.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the integration layer always present behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_integration_layer_always_present(self):
        for complexity in ("low", "medium", "high"):
            active = route(_state(complexity=complexity))
            assert "integration_layer" in active
            assert "evidence_ranker" in active
