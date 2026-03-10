"""
Tests for the Knowledge Layer and pipeline integration.
All external services (Weaviate, Neo4j) are mocked.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_rag.schemas.blackboard_schema import BlackboardState, PerceptionOutput
from swarm_rag.knowledge.knowledge_layer import build_knowledge_layer
from swarm_rag.core.pipeline import SwarmPipeline
from pytest_readable import readable



def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _state(branches=None) -> BlackboardState:
    s = BlackboardState.new_session("¿Cuál es la penalización?")
    s.perception = PerceptionOutput(needs_retrieval=True, complexity="medium")
    s.active_branches = branches or ["retrieval_weaviate", "evidence_merger"]
    return s


def _mock_retriever(hits):
    r = MagicMock()
    r.retrieve.return_value = (hits, {"avg_score": 0.8})
    return r


def _weaviate_hits(n=3):
    return [
        {"uuid": f"u{i}", "text": f"Cláusula {i}: penalización del {i*5}%",
         "score": 0.9 - i * 0.1, "source": f"doc{i}.pdf"}
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# build_knowledge_layer factory
# ---------------------------------------------------------------------------

class TestBuildKnowledgeLayer:
    @readable(
        intent="Verify returns callable in build knowledge layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the returns callable behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_returns_callable(self):
        retriever = _mock_retriever(_weaviate_hits(2))
        fn = build_knowledge_layer(retriever)
        assert callable(fn)

    @readable(
        intent="Verify weaviate hits populated in build knowledge layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the weaviate hits populated behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_weaviate_hits_populated(self):
        retriever = _mock_retriever(_weaviate_hits(3))
        fn = build_knowledge_layer(retriever)
        s = _state()
        result = _run(fn(s))
        assert len(result.retrieval.weaviate_hits) == 3
        assert "text" in result.retrieval.weaviate_hits[0]

    @readable(
        intent="Verify weaviate hit schema in build knowledge layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the weaviate hit schema behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_weaviate_hit_schema(self):
        retriever = _mock_retriever(_weaviate_hits(1))
        fn = build_knowledge_layer(retriever)
        s = _state()
        result = _run(fn(s))
        hit = result.retrieval.weaviate_hits[0]
        assert "chunk_id" in hit
        assert "text" in hit
        assert "score" in hit
        assert "source" in hit

    @readable(
        intent="Verify empty retrieval still runs in build knowledge layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the empty retrieval still runs behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_empty_retrieval_still_runs(self):
        retriever = _mock_retriever([])
        fn = build_knowledge_layer(retriever)
        s = _state()
        result = _run(fn(s))
        assert result.retrieval.weaviate_hits == []

    @readable(
        intent="Verify neo4j runs when branch active in build knowledge layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the neo4j runs when branch active behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_neo4j_runs_when_branch_active(self):
        retriever = _mock_retriever(_weaviate_hits(2))
        neo4j = MagicMock()
        neo4j.get_related_context.return_value = [
            {"source": "A", "relation": "RELATED_TO", "target": "B", "topic": None}
        ]
        fn = build_knowledge_layer(retriever, neo4j_repository=neo4j)
        s = _state(branches=["retrieval_weaviate", "retrieval_neo4j", "evidence_merger"])
        result = _run(fn(s))
        neo4j.get_related_context.assert_called()

    @readable(
        intent="Verify neo4j skipped when not in branches in build knowledge layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the neo4j skipped when not in branches behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_neo4j_skipped_when_not_in_branches(self):
        retriever = _mock_retriever(_weaviate_hits(2))
        neo4j = MagicMock()
        fn = build_knowledge_layer(retriever, neo4j_repository=neo4j)
        s = _state(branches=["retrieval_weaviate"])  # no neo4j branch
        _run(fn(s))
        neo4j.get_related_context.assert_not_called()

    @readable(
        intent="Verify no neo4j repo skips graph in build knowledge layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the no neo4j repo skips graph behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_no_neo4j_repo_skips_graph(self):
        retriever = _mock_retriever(_weaviate_hits(2))
        fn = build_knowledge_layer(retriever, neo4j_repository=None)
        s = _state(branches=["retrieval_weaviate", "retrieval_neo4j"])
        result = _run(fn(s))
        # No crash, neo4j_hits stays empty
        assert result.retrieval.neo4j_hits == []

    @readable(
        intent="Verify latency recorded in build knowledge layer.",
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
        retriever = _mock_retriever(_weaviate_hits(2))
        fn = build_knowledge_layer(retriever)
        s = _state()
        result = _run(fn(s))
        assert "knowledge" in result.latency_ms

    @readable(
        intent="Verify context compressor applied in build knowledge layer.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the context compressor applied behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_context_compressor_applied(self):
        # Low-score hit should be filtered by compressor (min_score=0.3)
        hits = [
            {"uuid": "a", "text": "good", "score": 0.9, "source": "a.pdf"},
            {"uuid": "b", "text": "bad", "score": 0.1, "source": "b.pdf"},
        ]
        retriever = _mock_retriever(hits)
        fn = build_knowledge_layer(retriever)
        s = _state()
        result = _run(fn(s))
        scores = [h["score"] for h in result.retrieval.weaviate_hits]
        assert all(sc >= 0.3 for sc in scores)


# ---------------------------------------------------------------------------
# SwarmPipeline.build() integration
# ---------------------------------------------------------------------------

class TestSwarmPipelineBuild:
    @readable(
        intent="Verify build with weaviate creates knowledge layer in swarm pipeline build.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the build with weaviate creates knowledge layer behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_build_with_weaviate_creates_knowledge_layer(self):
        chat = MagicMock()
        chat.chat.return_value = "La penalización es del 10%."
        retriever = _mock_retriever(_weaviate_hits(2))
        pipeline = SwarmPipeline.build(chat_interface=chat, weaviate_retriever=retriever)
        # Knowledge layer should be wired (not passthrough)
        assert pipeline._knowledge is not None

    @readable(
        intent="Verify build without weaviate uses passthrough in swarm pipeline build.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the build without weaviate uses passthrough behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_build_without_weaviate_uses_passthrough(self):
        chat = MagicMock()
        chat.chat.return_value = "respuesta"
        pipeline = SwarmPipeline.build(chat_interface=chat)
        # With no retriever, knowledge layer is passthrough
        from swarm_rag.core.pipeline import _passthrough
        assert pipeline._knowledge is _passthrough

    @readable(
        intent="Verify full pipeline run no crash in swarm pipeline build.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the full pipeline run no crash behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_full_pipeline_run_no_crash(self):
        chat = MagicMock()
        chat.chat.return_value = "La penalización aplica desde el contrato vigente."
        retriever = _mock_retriever(_weaviate_hits(3))

        # Patch specialists to avoid model loading
        from swarm_rag.specialists import query_rewriter, fact_extractor, evidence_ranker
        query_rewriter.QueryRewriter._model = None
        query_rewriter.QueryRewriter._model_loaded = True
        fact_extractor.FactExtractor._model = None
        fact_extractor.FactExtractor._model_loaded = True
        evidence_ranker.EvidenceRanker._model = None
        evidence_ranker.EvidenceRanker._model_loaded = True

        import swarm_rag.reasoning.confidence_estimator as ce
        with patch.object(ce, "_model", None), patch.object(ce, "_model_tried", True):
            pipeline = SwarmPipeline.build(
                chat_interface=chat,
                weaviate_retriever=retriever,
            )
            state = _run(pipeline.run("¿Cuál es la penalización del contrato vigente?"))

        assert state.final_response
        assert state.perception.intent  # perception ran
        assert "total" in state.latency_ms

    @readable(
        intent="Verify final response from chat in swarm pipeline build.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the final response from chat behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_final_response_from_chat(self):
        expected = "La penalización es del 8% según el contrato vigente."
        chat = MagicMock()
        chat.chat.return_value = expected
        retriever = _mock_retriever(_weaviate_hits(2))

        from swarm_rag.specialists import query_rewriter, fact_extractor, evidence_ranker
        query_rewriter.QueryRewriter._model = None
        query_rewriter.QueryRewriter._model_loaded = True
        fact_extractor.FactExtractor._model = None
        fact_extractor.FactExtractor._model_loaded = True
        evidence_ranker.EvidenceRanker._model = None
        evidence_ranker.EvidenceRanker._model_loaded = True

        import swarm_rag.reasoning.confidence_estimator as ce
        with patch.object(ce, "_model", None), patch.object(ce, "_model_tried", True):
            pipeline = SwarmPipeline.build(chat_interface=chat, weaviate_retriever=retriever)
            state = _run(pipeline.run("¿Cuál es la penalización?"))

        assert state.final_response == expected
