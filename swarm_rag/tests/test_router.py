"""
Unit tests for swarm_rag.core.router.Router

Tests run without any external dependencies (no Weaviate, Neo4j, LM Studio).
"""
from __future__ import annotations

import asyncio
import pytest
from pathlib import Path

from swarm_rag.core.router import Router
from swarm_rag.schemas.blackboard_schema import BlackboardState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(query: str) -> BlackboardState:
    return BlackboardState(
        user_query=query,
        session_id="test-session",
        timestamp="2026-01-01T00:00:00Z",
    )


def _route(query: str) -> list[str]:
    router = Router()
    state = _make_state(query)
    return asyncio.get_event_loop().run_until_complete(router.route(state))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRouterAlwaysOnPlugins:
    """Baseline plugins must always be present regardless of query content."""

    def test_simple_query_has_baseline_plugins(self):
        active = _route("What is the capital of France?")
        assert "retrieval" in active
        assert "context_compressor" in active
        assert "evidence_merger" in active

    def test_empty_ish_query_still_has_baseline(self):
        active = _route("hello")
        assert "retrieval" in active
        assert "evidence_merger" in active


class TestMathActivation:
    def test_calcula_triggers_math(self):
        active = _route("calcula el 15% de 200")
        assert "math_understanding" in active

    def test_percentage_symbol_triggers_math(self):
        active = _route("¿Cuánto es el 30% de 500?")
        assert "math_understanding" in active

    def test_divide_triggers_math(self):
        active = _route("divide 100 entre 4")
        assert "math_understanding" in active

    def test_pure_text_does_not_trigger_math(self):
        active = _route("¿Cuál es la política de devoluciones?")
        assert "math_understanding" not in active


class TestCodeActivation:
    def test_python_triggers_code(self):
        active = _route("Este método Python tiene un bug al calcular el IVA")
        assert "code_understanding" in active

    def test_bug_triggers_code(self):
        active = _route("hay un bug en la función de pago")
        assert "code_understanding" in active

    def test_clase_triggers_code(self):
        active = _route("explícame la clase PaymentProcessor")
        assert "code_understanding" in active

    def test_general_query_does_not_trigger_code(self):
        active = _route("¿Qué dice el contrato sobre las penalizaciones?")
        assert "code_understanding" not in active


class TestGraphActivation:
    def test_relacion_triggers_graph(self):
        active = _route("¿Qué relación hay entre el proveedor A y el contrato 2024?")
        assert "graph_retrieval" in active

    def test_depende_triggers_graph(self):
        active = _route("¿De qué depende el módulo de pagos?")
        assert "graph_retrieval" in active


class TestVersionActivation:
    def test_version_keyword_triggers_version_monitor(self):
        active = _route("¿Cuál es la versión vigente del contrato?")
        assert "version_monitor" in active

    def test_year_keyword_triggers_version_monitor(self):
        active = _route("Compara el contrato 2024 con el actual")
        assert "version_monitor" in active


class TestMemoryActivation:
    def test_recuerdas_triggers_memory(self):
        active = _route("¿Recuerdas qué solución aplicamos la semana pasada?")
        assert "memory_retrieval" in active

    def test_anteriormente_triggers_memory(self):
        active = _route("anteriormente hablamos de este problema")
        assert "memory_retrieval" in active


class TestMCPActivation:
    def test_git_triggers_mcp(self):
        active = _route("busca el último commit en el repo")
        assert "mcp_tool_agent" in active

    def test_digit_triggers_mcp(self):
        active = _route("usa digit para revisar el archivo")
        assert "mcp_tool_agent" in active


class TestCompoundQuery:
    """Compound queries should activate multiple specialist plugin chains."""

    def test_math_and_code_together(self):
        active = _route("calcula el descuento y corrígelo en el método Python")
        assert "math_understanding" in active
        assert "code_understanding" in active

    def test_version_and_graph_together(self):
        active = _route("muestra la relación entre las versiones del contrato 2024")
        assert "version_monitor" in active
        assert "graph_retrieval" in active

    def test_full_compound_query(self):
        """Simulates the 'compare contract + verify Python implementation' test case."""
        query = (
            "Compara el contrato 2024 con el vigente, "
            "verifica la implementación Python y calcula la diferencia porcentual"
        )
        active = _route(query)
        assert "retrieval" in active
        assert "math_understanding" in active
        assert "code_understanding" in active
        assert "version_monitor" in active


class TestStateUpdated:
    """Router must write active_plugins and intents back to the BlackboardState."""

    def test_active_plugins_written_to_state(self):
        router = Router()
        state = _make_state("calcula el total")
        asyncio.get_event_loop().run_until_complete(router.route(state))
        assert state.active_plugins  # non-empty
        assert "retrieval" in state.active_plugins

    def test_intents_written_to_state(self):
        router = Router()
        state = _make_state("calcula el IVA del contrato")
        asyncio.get_event_loop().run_until_complete(router.route(state))
        assert "math" in state.intents

    def test_pure_retrieval_intent_when_no_specialist(self):
        router = Router()
        state = _make_state("¿Qué dice el contrato sobre pagos?")
        asyncio.get_event_loop().run_until_complete(router.route(state))
        assert "retrieval" in state.intents
