"""
Tests for core/router.py v2 — reads state.perception.
"""
from __future__ import annotations
import pytest
from swarm_rag.schemas.blackboard_schema import BlackboardState, PerceptionOutput
from swarm_rag.core.router import route


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
    def test_always_has_retrieval_and_merger(self):
        active = route(_state())
        assert "retrieval_weaviate" in active
        assert "evidence_merger" in active

    def test_result_written_to_state(self):
        s = _state()
        route(s)
        assert s.active_branches  # non-empty

    def test_no_duplicates(self):
        active = route(_state(complexity="high", needs_math=True))
        assert len(active) == len(set(active))


class TestComplexityRouting:
    def test_low_complexity_no_specialist(self):
        active = route(_state(complexity="low"))
        assert "query_rewriter" not in active
        assert "subquestion_generator" not in active

    def test_medium_adds_rewriter(self):
        active = route(_state(complexity="medium"))
        assert "query_rewriter" in active
        assert "subquestion_generator" not in active

    def test_high_adds_rewriter_and_subquestions(self):
        active = route(_state(complexity="high"))
        assert "query_rewriter" in active
        assert "subquestion_generator" in active


class TestMathRouting:
    def test_needs_math_adds_math_branches(self):
        active = route(_state(needs_math=True))
        assert "math_specialist" in active
        assert "math_tool_agent" in active

    def test_no_math_no_math_branches(self):
        active = route(_state(needs_math=False))
        assert "math_specialist" not in active


class TestCodeRouting:
    def test_needs_code_adds_code_branches(self):
        active = route(_state(needs_code=True))
        assert "code_specialist" in active
        assert "code_agent_mcp" in active

    def test_no_code_no_code_branches(self):
        active = route(_state(needs_code=False))
        assert "code_specialist" not in active


class TestVersionConflictRouting:
    def test_version_conflicts_add_resolver(self):
        s = _state()
        s.retrieval.version_conflicts = [{"description": "conflict"}]
        active = route(s)
        assert "conflict_resolver" in active

    def test_no_conflicts_no_resolver(self):
        active = route(_state())
        assert "conflict_resolver" not in active


class TestReasoningAlwaysAdded:
    def test_integration_layer_always_present(self):
        for complexity in ("low", "medium", "high"):
            active = route(_state(complexity=complexity))
            assert "integration_layer" in active
            assert "evidence_ranker" in active
