"""
Unit tests for F2 core plugins (v3 schema):
- ContextCompressorPlugin
- EvidenceMerger
"""
from __future__ import annotations
import asyncio
import pytest
from swarm_rag.schemas.blackboard_schema import BlackboardState
from swarm_rag.plugins.context_compressor.plugin import ContextCompressorPlugin, _dedup_and_filter
from swarm_rag.plugins.evidence_merger.merger import EvidenceMerger
from pytest_readable import readable



def _state(**kwargs) -> BlackboardState:
    s = BlackboardState.new_session("test")
    return s


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_hits(n, base_score=0.8):
    return [{"chunk_id": f"c{i}", "text": f"text {i}", "score": base_score - i * 0.05, "source": f"doc{i}.pdf"} for i in range(n)]


class TestDedupAndFilter:
    @readable(
        intent="Verify filters below min score in dedup and filter.",
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
        hits = [{"chunk_id": "a", "text": "x", "score": 0.8}, {"chunk_id": "b", "text": "y", "score": 0.2}]
        assert len(_dedup_and_filter(hits, 0.5, 10)) == 1

    @readable(
        intent="Verify deduplicates keeps highest score in dedup and filter.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the deduplicates keeps highest score behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_deduplicates_keeps_highest_score(self):
        hits = [{"chunk_id": "a", "score": 0.6}, {"chunk_id": "a", "score": 0.9}]
        result = _dedup_and_filter(hits, 0.0, 10)
        assert len(result) == 1 and result[0]["score"] == 0.9

    @readable(
        intent="Verify trims to max hits in dedup and filter.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the trims to max hits behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_trims_to_max_hits(self):
        assert len(_dedup_and_filter(_make_hits(20, 0.9), 0.0, 5)) == 5

    @readable(
        intent="Verify sorted descending in dedup and filter.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the sorted descending behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_sorted_descending(self):
        hits = [{"chunk_id": "a", "score": 0.5}, {"chunk_id": "b", "score": 0.9}]
        result = _dedup_and_filter(hits, 0.0, 10)
        assert result[0]["score"] == 0.9

    @readable(
        intent="Verify empty input in dedup and filter.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the empty input behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_empty_input(self):
        assert _dedup_and_filter([], 0.5, 10) == []


class TestContextCompressor:
    @readable(
        intent="Verify filters low score in context compressor.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the filters low score behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_filters_low_score(self):
        s = _state()
        s.retrieval.weaviate_hits = [{"chunk_id": "a", "score": 0.8, "text": "good"}, {"chunk_id": "b", "score": 0.1, "text": "bad"}]
        result = _run(ContextCompressorPlugin(min_score=0.5).run(s))
        assert len(result.retrieval.weaviate_hits) == 1

    @readable(
        intent="Verify all three lists in context compressor.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the all three lists behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_all_three_lists(self):
        s = _state()
        s.retrieval.weaviate_hits = _make_hits(5, 0.9)
        s.retrieval.neo4j_hits = _make_hits(3, 0.8)
        s.retrieval.memory_hits = _make_hits(4, 0.7)
        result = _run(ContextCompressorPlugin(min_score=0.0, max_hits=2).run(s))
        assert len(result.retrieval.weaviate_hits) == 2
        assert len(result.retrieval.neo4j_hits) == 2
        assert len(result.retrieval.memory_hits) == 2


class TestEvidenceMerger:
    @readable(
        intent="Verify empty state produces empty summary in evidence merger.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the empty state produces empty summary behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_empty_state_produces_empty_summary(self):
        s = _state()
        result = _run(EvidenceMerger().run(s))
        assert result.reasoning.structured_answer == ""

    @readable(
        intent="Verify weaviate hits in summary in evidence merger.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the weaviate hits in summary behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_weaviate_hits_in_summary(self):
        s = _state()
        s.retrieval.weaviate_hits = [{"chunk_id": "a", "text": "El contrato dice X", "score": 0.9, "source": "contrato.pdf"}]
        result = _run(EvidenceMerger().run(s))
        assert "El contrato dice X" in result.reasoning.structured_answer
        assert "contrato.pdf" in result.reasoning.structured_answer

    @readable(
        intent="Verify math result in summary in evidence merger.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the math result in summary behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_math_result_in_summary(self):
        s = _state()
        s.specialists.math_result = 15.0
        result = _run(EvidenceMerger().run(s))
        assert "15.0" in result.reasoning.structured_answer
        assert "MATEMÁTICO" in result.reasoning.structured_answer

    @readable(
        intent="Verify code analysis in summary in evidence merger.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the code analysis in summary behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_code_analysis_in_summary(self):
        s = _state()
        s.specialists.code_analysis = {"language": "Python", "result": "def foo(): pass", "issues": []}
        result = _run(EvidenceMerger().run(s))
        assert "Python" in result.reasoning.structured_answer

    @readable(
        intent="Verify version conflicts in summary in evidence merger.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the version conflicts in summary behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_version_conflicts_in_summary(self):
        s = _state()
        s.retrieval.version_conflicts = [{"description": "v2024 contradicts vigente"}]
        result = _run(EvidenceMerger().run(s))
        assert "v2024 contradicts vigente" in result.reasoning.structured_answer
        assert "VERSIÓN" in result.reasoning.structured_answer

    @readable(
        intent="Verify memory hits in summary in evidence merger.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the memory hits in summary behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_memory_hits_in_summary(self):
        s = _state()
        s.retrieval.memory_hits = [{"chunk_id": "m1", "text": "Solución anterior", "score": 0.75, "source": "memory"}]
        result = _run(EvidenceMerger().run(s))
        assert "Solución anterior" in result.reasoning.structured_answer

    @readable(
        intent="Verify sections separated by divider in evidence merger.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the sections separated by divider behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_sections_separated_by_divider(self):
        s = _state()
        s.retrieval.weaviate_hits = [{"chunk_id": "a", "text": "fact 1", "score": 0.9, "source": "s1"}]
        s.specialists.math_result = 42
        result = _run(EvidenceMerger().run(s))
        assert "─" in result.reasoning.structured_answer
