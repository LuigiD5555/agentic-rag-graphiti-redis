from __future__ import annotations

import pytest

from src.config.settings import Config


@pytest.fixture(autouse=True)
def clear_cached_env(monkeypatch):
    """Ensure per-test environment isolation for exclude-related variables."""
    for var in ("DOCS_EXCLUDE_DIRS", "DOCS_EXCLUDE_PATTERNS", "DOCS_EXCLUDE_FILE"):
        monkeypatch.delenv(var, raising=False)
    yield


def test_config_merges_default_env_and_file(tmp_path, monkeypatch):
    ignore_file = tmp_path / ".ragignore"
    ignore_file.write_text(
        """
        # comentarios deben ignorarse
        custom-dir
        logs/**
        *.cache
        """,
        encoding="utf-8",
    )

    monkeypatch.setenv("DOCS_EXCLUDE_DIRS", "build,.cache")
    monkeypatch.setenv("DOCS_EXCLUDE_PATTERNS", '["*.bak", "**/tmp/**"]')
    monkeypatch.setenv("DOCS_EXCLUDE_FILE", str(ignore_file))

    config = Config()

    excluded_dirs = set(config.DOCS_EXCLUDE_DIRS)
    excluded_globs = set(config.DOCS_EXCLUDE_GLOBS)

    # Defaults remain present
    assert ".git" in excluded_dirs

    # Env and file values get merged
    assert {"custom-dir", "build"}.issubset(excluded_dirs)
    assert "logs/**" in excluded_globs
    assert "*.cache" in excluded_globs
    assert "*.bak" in excluded_globs
    assert "**/tmp/**" in excluded_globs
