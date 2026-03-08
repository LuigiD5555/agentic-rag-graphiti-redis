"""
Shared pytest fixtures and test helpers.

This module provides reusable test doubles, fixtures, and utilities
for all tests in the test suite.
"""

import os
from pathlib import Path
from collections import deque
from typing import Any, Dict, List, Optional

import pytest


# ============================================================================
# Pytest Configuration
# ============================================================================

@pytest.fixture(autouse=True)
def isolate_user_settings_file(tmp_path, monkeypatch):
    """
    Prevent tests from reading/writing the repo's `data/settings.json`.

    Config persists normalized settings to USER_SETTINGS_FILE during init; in
    tests we isolate this side-effect to a temp path.
    """
    monkeypatch.setenv("USER_SETTINGS_FILE", str(tmp_path / "settings.json"))
    yield


def _is_integration_item(item: pytest.Item) -> bool:
    """Detect integration tests by marker or file location."""
    if "integration" in item.keywords:
        return True
    return Path(str(item.fspath)).parts.count("integration") > 0


def pytest_collection_modifyitems(config, items):
    """
    Deselect integration tests unless RUN_INTEGRATION=1 is set.

    Using deselection instead of runtime skipping keeps default test runs
    cleaner and avoids large skip counts.
    """
    selected = []
    deselected = []
    for item in items:
        is_integration = _is_integration_item(item)
        is_host_preflight = "preflight_host" in item.keywords
        is_optional_ner = "tests/unit/storage/test_er_extraction.py" in item.nodeid

        if is_integration and os.getenv("RUN_INTEGRATION") != "1":
            deselected.append(item)
            continue

        if is_host_preflight and os.getenv("RUN_PREFLIGHT_HOST") != "1":
            deselected.append(item)
        elif is_optional_ner and os.getenv("RUN_OPTIONAL_NER") != "1":
            deselected.append(item)
        else:
            selected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        '--setup-fallback',
        action='store_true',
        default=False,
        help='Setup fallback directories when volumes are not accessible'
    )


def pytest_configure(config):
    """Register custom markers."""
    # Test category markers
    config.addinivalue_line(
        'markers',
        'unit: Unit tests (fast, no external dependencies)'
    )
    config.addinivalue_line(
        'markers',
        'integration: Integration tests (may require services)'
    )
    config.addinivalue_line(
        'markers',
        'slow: Tests that take significant time to run'
    )

    # External dependency markers
    config.addinivalue_line(
        'markers',
        'requires_weaviate: Tests requiring Weaviate to be running'
    )
    config.addinivalue_line(
        'markers',
        'requires_neo4j: Tests requiring Neo4j to be running'
    )
    config.addinivalue_line(
        'markers',
        'requires_lmstudio: Tests requiring LM Studio to be running'
    )

    # Infrastructure markers
    config.addinivalue_line(
        'markers',
        'infrastructure: Infrastructure and system tests'
    )
    config.addinivalue_line(
        'markers',
        'preflight: Pre-flight system checks'
    )
    config.addinivalue_line(
        'markers',
        'preflight_host: Host-only preflight checks (podman/systemd/compose/.env)'
    )
    config.addinivalue_line(
        'markers',
        'preflight_runtime: Runtime/container preflight checks'
    )
    config.addinivalue_line(
        'markers',
        'volumes: Volume verification tests'
    )


# ============================================================================
# Test Doubles - Embedding Services
# ============================================================================

class DummyEmbedding:
    """
    Test double for embedding services.

    Records all generate() calls for assertion and returns fixed vectors.
    """

    def __init__(self) -> None:
        self.calls: deque[str] = deque()

    def generate(self, text: str) -> List[float]:
        """Generate a fixed embedding vector and record the call."""
        self.calls.append(text)
        return [0.1, 0.2, 0.3, 0.4]


class DummyVectorStore:
    """
    Minimal vector store implementation for testing.

    Tracks upserts, searches, and supports exists() checks.
    """

    def __init__(self) -> None:
        self.upserts: deque[Dict[str, Any]] = deque()
        self._existing: set[str] = set()
        self.failures: deque[Dict[str, Any]] = deque()
        self.archived: deque[str] = deque()

    def upsert(
        self,
        key: Optional[str],
        vector: List[float],
        metadata: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> None:
        """Record an upsert operation."""
        self.upserts.append(
            {
                "key": key,
                "vector": list(vector),
                "metadata": dict(metadata),
                "tenant_id": tenant_id,
            }
        )
        if key:
            self._existing.add(key)

    def exists(self, point_id: str, tenant_id: Optional[str] = None) -> bool:
        """Check if a point exists in the store."""
        return point_id in self._existing

    def search(
        self,
        vector: List[float],
        limit: int = 10,
        tenant_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return empty search results."""
        return []


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def dummy_embedding():
    """Provide a reusable dummy embedding service."""
    return DummyEmbedding()


@pytest.fixture
def dummy_vector_store():
    """Provide a reusable dummy vector store."""
    return DummyVectorStore()


@pytest.fixture
def temp_file(tmp_path):
    """
    Provide a temporary file path factory.

    Usage:
        def test_something(temp_file):
            path = temp_file("test.txt", "content here")
    """
    def _create_file(name: str, content: str = "") -> Any:
        file_path = tmp_path / name
        file_path.write_text(content)
        return file_path

    return _create_file


# ============================================================================
# Helper Functions
# ============================================================================

def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text for comparison."""
    return " ".join(text.split())


def assert_contains_all(text: str, *substrings: str) -> None:
    """Assert that text contains all given substrings."""
    for substring in substrings:
        assert substring in text, f"Expected '{substring}' in text"


def assert_dict_subset(subset: Dict, superset: Dict) -> None:
    """Assert that all key-value pairs in subset are in superset."""
    for key, value in subset.items():
        assert key in superset, f"Key '{key}' not found"
        assert superset[key] == value, f"Value mismatch for '{key}'"
