"""
Unit tests for F3 plugins:
- GraphRetrievalPlugin (keyword extraction only — no live Neo4j)
- VersionMonitorPlugin (pure in-memory logic)
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import MagicMock

from swarm_rag.schemas.blackboard_schema import BlackboardState, CodeContext
from swarm_rag.plugins.graph_retrieval.plugin import GraphRetrievalPlugin, _extract_keywords
from swarm_rag.plugins.version_monitor.plugin import VersionMonitorPlugin


def _state(**kwargs) -> BlackboardState:
    base = dict(user_query="test", session_id="s1", timestamp="2026-01-01T00:00:00Z")
    base.update(kwargs)
    return BlackboardState(**base)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _hit(text: str, source: str = "doc.pdf", score: float = 0.8) -> dict:
    return {"chunk_id": source, "text": text, "score": score, "source": source}


# ---------------------------------------------------------------------------
# GraphRetrievalPlugin — keyword extraction (no I/O)
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    def test_extracts_long_words_from_query(self):
        state = _state(user_query="¿Cuál es el contrato vigente del proveedor principal?")
        kw = _extract_keywords(state)
        assert "contrato" in kw
        assert "vigente" in kw
        assert "proveedor" in kw
        assert "principal" in kw

    def test_stopwords_excluded(self):
        state = _state(user_query="cuál es una relación entre los contratos")
        kw = _extract_keywords(state)
        assert "una" not in kw
        assert "los" not in kw
        assert "entre" not in kw

    def test_code_symbols_included(self):
        state = _state(user_query="revisa el módulo")
        state.code_context = CodeContext(detected=True, symbols=["PaymentService", "InvoiceModel"])
        kw = _extract_keywords(state)
        assert "PaymentService" in kw
        assert "InvoiceModel" in kw

    def test_max_kw_respected(self):
        state = _state(user_query=" ".join([f"keyword{i}" for i in range(20)]))
        kw = _extract_keywords(state, max_kw=5)
        assert len(kw) <= 5

    def test_no_duplicates(self):
        state = _state(user_query="contrato contrato contrato vigente")
        kw = _extract_keywords(state)
        assert len(kw) == len(set(kw))


class TestGraphRetrievalPlugin:
    def _mock_repo(self, edges):
        repo = MagicMock()
        repo.get_related_context.return_value = edges
        return repo

    def test_hits_written_to_state(self):
        edges = [
            {"source": "ContractA", "relation": "RELATED_TO", "target": "Supplier", "topic": "legal"},
        ]
        plugin = GraphRetrievalPlugin(neo4j_repository=self._mock_repo(edges))
        state = _state(user_query="relacion entre contrato y proveedor")
        result = _run(plugin.run(state))
        assert len(result.retrieval.neo4j_hits) == 1
        assert "ContractA" in result.retrieval.neo4j_hits[0]["text"]

    def test_empty_edges_leaves_hits_empty(self):
        plugin = GraphRetrievalPlugin(neo4j_repository=self._mock_repo([]))
        state = _state(user_query="relacion entre elementos")
        result = _run(plugin.run(state))
        assert result.retrieval.neo4j_hits == []

    def test_no_keywords_skips_repo_call(self):
        repo = MagicMock()
        plugin = GraphRetrievalPlugin(neo4j_repository=repo)
        # Very short words — all filtered out
        state = _state(user_query="el la de un")
        _run(plugin.run(state))
        repo.get_related_context.assert_not_called()

    def test_hit_schema_has_required_fields(self):
        edges = [{"source": "A", "relation": "PART_OF", "target": "B", "topic": None}]
        plugin = GraphRetrievalPlugin(neo4j_repository=self._mock_repo(edges))
        state = _state(user_query="relacion modulo sistema")
        result = _run(plugin.run(state))
        hit = result.retrieval.neo4j_hits[0]
        assert "chunk_id" in hit
        assert "text" in hit
        assert "score" in hit
        assert "source" in hit


# ---------------------------------------------------------------------------
# VersionMonitorPlugin — pure logic
# ---------------------------------------------------------------------------

class TestVersionMonitorPlugin:
    def test_no_hits_produces_no_conflicts(self):
        state = _state()
        result = _run(VersionMonitorPlugin().run(state))
        assert result.version_conflicts == []
        assert result.active_versions == []

    def test_single_year_produces_no_conflict(self):
        state = _state()
        state.retrieval.weaviate_hits = [
            _hit("El contrato 2024 establece las condiciones"),
            _hit("Según el contrato 2024 las penalizaciones son"),
        ]
        result = _run(VersionMonitorPlugin().run(state))
        assert result.version_conflicts == []

    def test_two_different_years_produces_conflict(self):
        state = _state()
        state.retrieval.weaviate_hits = [
            _hit("El contrato 2023 establecía las condiciones", source="old.pdf"),
            _hit("El contrato 2024 vigente actualiza las condiciones", source="new.pdf"),
        ]
        result = _run(VersionMonitorPlugin().run(state))
        assert len(result.version_conflicts) == 1
        conflict = result.version_conflicts[0]
        assert conflict["type"] == "year_discrepancy"
        assert conflict["stale_year"] == 2023
        assert conflict["current_year"] == 2024

    def test_active_version_is_most_recent_year(self):
        state = _state()
        state.retrieval.weaviate_hits = [
            _hit("versión 2022", source="a.pdf"),
            _hit("versión 2025 vigente", source="b.pdf"),
        ]
        result = _run(VersionMonitorPlugin().run(state))
        assert result.active_versions[0]["year"] == 2025

    def test_vigente_and_obsoleto_conflict(self):
        state = _state()
        state.retrieval.neo4j_hits = [
            _hit("ContractA vigente -[RELATED_TO]-> Supplier", source="graph"),
            _hit("ContractB obsoleto -[RELATED_TO]-> Supplier", source="graph"),
        ]
        result = _run(VersionMonitorPlugin().run(state))
        conflict_types = [c["type"] for c in result.version_conflicts]
        assert "vigente_conflict" in conflict_types

    def test_three_years_produces_two_conflicts(self):
        state = _state()
        state.retrieval.weaviate_hits = [
            _hit("contrato 2022", source="a.pdf"),
            _hit("contrato 2023", source="b.pdf"),
            _hit("contrato 2024", source="c.pdf"),
        ]
        result = _run(VersionMonitorPlugin().run(state))
        # 2022 and 2023 are stale vs 2024
        year_conflicts = [c for c in result.version_conflicts if c["type"] == "year_discrepancy"]
        stale_years = {c["stale_year"] for c in year_conflicts}
        assert 2022 in stale_years
        assert 2023 in stale_years
