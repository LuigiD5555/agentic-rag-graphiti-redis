import pytest

from src.workflows.ingestion.helpers import build_ingestion_options_from_args
from src.workflows.query.conf import Config


@pytest.fixture(autouse=True)
def clear_cached_env(monkeypatch):
    """Ensure per-test environment isolation for exclude-related variables."""
    for var in ("DOCS_EXCLUDE_DIRS", "DOCS_EXCLUDE_PATTERNS", "DOCS_EXCLUDE_FILE"):
        monkeypatch.delenv(var, raising=False)
    yield


def test_config_merges_default_env_and_file(tmp_path, monkeypatch):
    ignore_file = tmp_path / ".ingestignore"
    ignore_file.write_text(
        """
        # comments should be ignored
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


def test_config_loads_default_ingestignore(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ingestignore").write_text(
        """
        # file basename
        secrets.txt
        # relative path
        data/private/**
        """,
        encoding="utf-8",
    )

    config = Config()
    excluded_globs = set(config.DOCS_EXCLUDE_GLOBS)

    assert "secrets.txt" in excluded_globs
    assert "data/private/**" in excluded_globs


def test_helper_loads_ingestignore_entries(tmp_path):
    ignore_file = tmp_path / ".ingestignore"
    ignore_file.write_text(
        """
        custom-dir
        logs/**
        *.cache
        """,
        encoding="utf-8",
    )

    class Args:
        paths = None
        exts = None
        exclude_dirs = None
        exclude_patterns = None
        enabled_paths = None
        follow_symlinks = False
        dry_run = False
        per_file = False
        max_files = 0
        streaming = None
        log_level = None
        scan_progress = 0
        strategy = None
        phased_ingestion = None
        max_ram_percent = None
        run_id = None

    options = build_ingestion_options_from_args(
        Args(),
        Config(DOCS_EXCLUDE_FILE=str(ignore_file)),
    )

    assert "custom-dir" in options.excluded_directory_names
    assert "logs/**" in options.excluded_path_globs
    assert "*.cache" in options.excluded_path_globs
