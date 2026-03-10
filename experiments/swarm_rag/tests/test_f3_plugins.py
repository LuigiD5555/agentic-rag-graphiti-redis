"""
Unit tests for F3 plugins (v3 schema):
- GraphRetrievalPlugin (keyword extraction + mock repo)
- VersionMonitorPlugin (pure in-memory)
"""
from __future__ import annotations
import asyncio
from unittest.mock import MagicMock
import pytest

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState
from experiments.swarm_rag.plugins.graph_retrieval.plugin import GraphRetrievalPlugin, _extract_keywords
from experiments.swarm_rag.plugins.version_monitor.plugin import VersionMonitorPlugin
from pytest_readable import readable



def _state(query="test") -> BlackboardState:
    return BlackboardState.new_session(query)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _hit(text, source="doc.pdf", score=0.8):
    return {"chunk_id": source, "text": text, "score": score, "source": source}


class TestExtractKeywords:
    @readable(
        intent="Verify extracts long words in extract keywords.",
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
        s = _state("relacion entre contrato vigente proveedor principal")
        kw = _extract_keywords(s)
        assert "contrato" in kw
        assert "vigente" in kw

    @readable(
        intent="Verify stopwords excluded in extract keywords.",
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
        s = _state("entre los contratos vigentes")
        kw = _extract_keywords(s)
        assert "entre" not in kw
        assert "los" not in kw

    @readable(
        intent="Verify max kw respected in extract keywords.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the max kw respected behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_max_kw_respected(self):
        s = _state(" ".join([f"keyword{i}" for i in range(20)]))
        assert len(_extract_keywords(s, max_kw=5)) <= 5

    @readable(
        intent="Verify no duplicates in extract keywords.",
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
        s = _state("contrato contrato contrato")
        kw = _extract_keywords(s)
        assert len(kw) == len(set(kw))


class TestGraphRetrievalPlugin:
    def _repo(self, edges):
        r = MagicMock()
        r.get_related_context.return_value = edges
        return r

    @readable(
        intent="Verify hits written in graph retrieval plugin.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the hits written behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_hits_written(self):
        edges = [{"source": "ContractA", "relation": "RELATED_TO", "target": "Supplier", "topic": "legal"}]
        s = _state("relacion entre contrato proveedor")
        result = _run(GraphRetrievalPlugin(self._repo(edges)).run(s))
        assert len(result.retrieval.neo4j_hits) == 1
        assert "ContractA" in result.retrieval.neo4j_hits[0]["text"]

    @readable(
        intent="Verify no keywords skips repo in graph retrieval plugin.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the no keywords skips repo behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_no_keywords_skips_repo(self):
        r = MagicMock()
        s = _state("el la de un")
        _run(GraphRetrievalPlugin(r).run(s))
        r.get_related_context.assert_not_called()

    @readable(
        intent="Verify hit schema in graph retrieval plugin.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the hit schema behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_hit_schema(self):
        edges = [{"source": "A", "relation": "PART_OF", "target": "B", "topic": None}]
        s = _state("relacion modulo sistema")
        result = _run(GraphRetrievalPlugin(self._repo(edges)).run(s))
        hit = result.retrieval.neo4j_hits[0]
        for field in ("chunk_id", "text", "score", "source"):
            assert field in hit


class TestVersionMonitorPlugin:
    @readable(
        intent="Verify no hits no conflicts in version monitor plugin.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the no hits no conflicts behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_no_hits_no_conflicts(self):
        result = _run(VersionMonitorPlugin().run(_state()))
        assert result.retrieval.version_conflicts == []

    @readable(
        intent="Verify single year no conflict in version monitor plugin.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the single year no conflict behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_single_year_no_conflict(self):
        s = _state()
        s.retrieval.weaviate_hits = [_hit("contrato 2024"), _hit("penalización 2024")]
        result = _run(VersionMonitorPlugin().run(s))
        assert result.retrieval.version_conflicts == []

    @readable(
        intent="Verify two years conflict in version monitor plugin.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the two years conflict behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_two_years_conflict(self):
        s = _state()
        s.retrieval.weaviate_hits = [_hit("contrato 2023", "old.pdf"), _hit("contrato 2024", "new.pdf")]
        result = _run(VersionMonitorPlugin().run(s))
        assert len(result.retrieval.version_conflicts) == 1
        assert result.retrieval.version_conflicts[0]["stale_year"] == 2023

    @readable(
        intent="Verify vigente obsoleto conflict in version monitor plugin.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the vigente obsoleto conflict behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_vigente_obsoleto_conflict(self):
        s = _state()
        s.retrieval.neo4j_hits = [_hit("ContractA vigente -[RELATED_TO]-> Supplier"), _hit("ContractB obsoleto -[RELATED_TO]-> Supplier")]
        result = _run(VersionMonitorPlugin().run(s))
        types = [c["type"] for c in result.retrieval.version_conflicts]
        assert "vigente_conflict" in types
