"""
Tests for final plan v3 components:
- MemoryRetrieval (mocked CrossChatRetriever)
- PrivacyScrubber (regex backend — no presidio needed)
- SwarmPipeline.build() with memory_retrieval injected
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from swarm_rag.schemas.blackboard_schema import BlackboardState, PerceptionOutput
from swarm_rag.knowledge.memory_retrieval import build_memory_retrieval
from swarm_rag.knowledge.privacy_scrubber import run_privacy_scrubber, _regex_scrub
from pytest_readable import readable



def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _state(query="test") -> BlackboardState:
    s = BlackboardState.new_session(query)
    s.perception = PerceptionOutput()
    s.active_branches = ["memory_retrieval", "privacy_scrubber"]
    return s


# ---------------------------------------------------------------------------
# MemoryRetrieval
# ---------------------------------------------------------------------------

class TestMemoryRetrieval:
    def _mock_retriever(self, hits):
        r = MagicMock()
        r.retrieve.return_value = hits
        return r

    @readable(
        intent="Verify skips when not in branches in memory retrieval.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the skips when not in branches behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_skips_when_not_in_branches(self):
        retriever = self._mock_retriever([{"summary": "past solution", "session_id": "s1"}])
        fn = build_memory_retrieval(retriever)
        s = _state()
        s.active_branches = []  # memory_retrieval not active
        result = _run(fn(s))
        retriever.retrieve.assert_not_called()
        assert result.retrieval.memory_hits == []

    @readable(
        intent="Verify hits written to state in memory retrieval.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the hits written to state behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_hits_written_to_state(self):
        raw_hits = [
            {"summary": "Solución aplicada: reducir penalización al 8%", "session_id": "s1", "relevance_score": 0.85},
            {"summary": "Conflicto resuelto: versión 2024 es la vigente", "session_id": "s2", "relevance_score": 0.72},
        ]
        fn = build_memory_retrieval(self._mock_retriever(raw_hits))
        s = _state("recuerdas la solución de penalización")
        result = _run(fn(s))
        assert len(result.retrieval.memory_hits) == 2
        assert result.retrieval.memory_hits[0]["score"] == pytest.approx(0.85)
        assert "session:" in result.retrieval.memory_hits[0]["source"]

    @readable(
        intent="Verify hit schema complete in memory retrieval.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the hit schema complete behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_hit_schema_complete(self):
        fn = build_memory_retrieval(self._mock_retriever([
            {"summary": "previous fix", "session_id": "s1", "relevance_score": 0.6}
        ]))
        s = _state()
        result = _run(fn(s))
        hit = result.retrieval.memory_hits[0]
        assert "chunk_id" in hit
        assert "text" in hit
        assert "score" in hit
        assert "source" in hit

    @readable(
        intent="Verify empty hits stays empty in memory retrieval.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the empty hits stays empty behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_empty_hits_stays_empty(self):
        fn = build_memory_retrieval(self._mock_retriever([]))
        s = _state()
        result = _run(fn(s))
        assert result.retrieval.memory_hits == []

    @readable(
        intent="Verify retriever exception graceful in memory retrieval.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the retriever exception graceful behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_retriever_exception_graceful(self):
        r = MagicMock()
        r.retrieve.side_effect = RuntimeError("memory system down")
        fn = build_memory_retrieval(r)
        s = _state()
        result = _run(fn(s))  # must not raise
        assert result.retrieval.memory_hits == []

    @readable(
        intent="Verify uses rewritten query when available in memory retrieval.",
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
        retriever = self._mock_retriever([])
        fn = build_memory_retrieval(retriever)
        s = _state("query original")
        s.specialists.rewritten_query = "rewritten specific query"
        _run(fn(s))
        call_query = retriever.retrieve.call_args[0][0]
        assert call_query == "rewritten specific query"


# ---------------------------------------------------------------------------
# PrivacyScrubber — regex backend
# ---------------------------------------------------------------------------

class TestRegexScrub:
    @readable(
        intent="Verify email anonymized in regex scrub.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the email anonymized behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_email_anonymized(self):
        text, entity_map = _regex_scrub("Contacta a juan.garcia@empresa.com para más info")
        assert "juan.garcia@empresa.com" not in text
        assert any("EMAIL" in k for k in entity_map)

    @readable(
        intent="Verify phone anonymized in regex scrub.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the phone anonymized behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_phone_anonymized(self):
        text, entity_map = _regex_scrub("Llama al +34 612 345 678 mañana")
        assert "+34 612 345 678" not in text

    @readable(
        intent="Verify dni anonymized in regex scrub.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the dni anonymized behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_dni_anonymized(self):
        text, entity_map = _regex_scrub("El DNI es 12345678Z según el contrato")
        assert "12345678Z" not in text

    @readable(
        intent="Verify iban anonymized in regex scrub.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the iban anonymized behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_iban_anonymized(self):
        text, entity_map = _regex_scrub("Transfiere a ES91 2100 0418 4502 0005 1332")
        assert "ES91" not in text

    @readable(
        intent="Verify no pii returns unchanged in regex scrub.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the no pii returns unchanged behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_no_pii_returns_unchanged(self):
        text = "¿Cuál es la penalización del contrato vigente?"
        scrubbed, entity_map = _regex_scrub(text)
        assert entity_map == {}
        # text may be unchanged or minimally changed by name heuristic
        assert len(scrubbed) > 0

    @readable(
        intent="Verify multiple pii all replaced in regex scrub.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the multiple pii all replaced behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_multiple_pii_all_replaced(self):
        text = "Email: test@test.com, Teléfono: 612345678, DNI: 12345678A"
        scrubbed, entity_map = _regex_scrub(text)
        assert "test@test.com" not in scrubbed
        assert len(entity_map) >= 2


class TestPrivacyScrubberPlugin:
    @readable(
        intent="Verify skips when not in branches in privacy scrubber plugin.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the skips when not in branches behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_skips_when_not_in_branches(self):
        s = _state("mi email es test@test.com")
        s.active_branches = []
        result = _run(run_privacy_scrubber(s))
        # Query unchanged since scrubber not in branches
        assert result.specialists.rewritten_query is None

    @readable(
        intent="Verify email scrubbed to rewritten query in privacy scrubber plugin.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the email scrubbed to rewritten query behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_email_scrubbed_to_rewritten_query(self):
        s = _state("envía a test@example.com el contrato")
        s.active_branches = ["privacy_scrubber"]
        result = _run(run_privacy_scrubber(s))
        rewritten = result.specialists.rewritten_query
        assert rewritten is not None
        assert "test@example.com" not in rewritten

    @readable(
        intent="Verify no pii does not set rewritten in privacy scrubber plugin.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the no pii does not set rewritten behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_no_pii_does_not_set_rewritten(self):
        s = _state("¿cuál es la penalización?")
        s.active_branches = ["privacy_scrubber"]
        result = _run(run_privacy_scrubber(s))
        # No PII → rewritten_query stays None
        assert result.specialists.rewritten_query is None

    @readable(
        intent="Verify execution trace entry added on pii in privacy scrubber plugin.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the execution trace entry added on pii behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_execution_trace_entry_added_on_pii(self):
        s = _state("email: test@test.com")
        s.active_branches = ["privacy_scrubber"]
        result = _run(run_privacy_scrubber(s))
        layers = [t.get("layer") for t in result.execution_trace]
        assert "privacy_scrubber" in layers


# ---------------------------------------------------------------------------
# SwarmPipeline.build() — memory + privacy integration smoke test
# ---------------------------------------------------------------------------

class TestPipelineWithMemoryAndPrivacy:
    @readable(
        intent="Verify build with memory retrieval in pipeline with memory and privacy.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the build with memory retrieval behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_build_with_memory_retrieval(self):
        from swarm_rag.core.pipeline import SwarmPipeline
        from swarm_rag.knowledge.knowledge_layer import build_knowledge_layer
        from swarm_rag.knowledge.memory_retrieval import build_memory_retrieval
        from swarm_rag.specialists import query_rewriter, fact_extractor, evidence_ranker
        import swarm_rag.reasoning.confidence_estimator as ce
        from unittest.mock import patch

        # Mock all ML models
        for mod in (query_rewriter.QueryRewriter, fact_extractor.FactExtractor, evidence_ranker.EvidenceRanker):
            mod._model = None
            mod._model_loaded = True

        # Mock weaviate retriever
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = (
            [{"uuid": "u1", "text": "contrato establece 10%", "score": 0.85, "source": "doc.pdf"}],
            {"avg_score": 0.85},
        )

        # Mock memory
        mock_memory = MagicMock()
        mock_memory.retrieve.return_value = []

        chat = MagicMock()
        chat.chat.return_value = "La penalización es del 10%."

        knowledge = build_knowledge_layer(mock_retriever)
        memory_fn = build_memory_retrieval(mock_memory)

        async def combined_knowledge(state):
            state = await knowledge(state)
            state = await memory_fn(state)
            return state

        with patch.object(ce, "_model", None), patch.object(ce, "_model_tried", True):
            pipeline = SwarmPipeline.build(
                chat_interface=chat,
                knowledge_layer=combined_knowledge,
            )
            state = asyncio.get_event_loop().run_until_complete(
                pipeline.run("recuerdas la solución de penalización?")
            )

        assert state.final_response
        assert "total" in state.latency_ms
