import pytest

from src.workflows.ingestion.helpers import build_ingestion_options_from_args
from src.workflows.query.conf import Config
from pytest_readable import readable



@pytest.fixture(autouse=True)
def clear_cached_env(monkeypatch):
    """Ensure per-test environment isolation for exclude-related variables."""
    for var in ("DOCS_EXCLUDE_DIRS", "DOCS_EXCLUDE_PATTERNS", "DOCS_EXCLUDE_FILE"):
        monkeypatch.delenv(var, raising=False)
    yield


@readable(
    intent="Verify config merges default env and file.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the config merges default env and file behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
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

    config = Config(
        DOCS_EXCLUDE_DIRS=("build", ".cache"),
        DOCS_EXCLUDE_GLOBS=("*.bak", "**/tmp/**"),
        DOCS_EXCLUDE_FILE=str(ignore_file),
    )

    excluded_dirs, excluded_globs = config.get_exclude_config()
    excluded_dirs = set(excluded_dirs)
    excluded_globs = set(excluded_globs)

    # Built-ins remain present via DEFAULT_EXCLUDED_FILES.
    assert ".git" in excluded_dirs

    # Env and file values get merged
    assert {"custom-dir", "build"}.issubset(excluded_dirs)
    assert "logs/**" in excluded_globs
    assert "*.cache" in excluded_globs
    assert "*.bak" in excluded_globs
    assert "**/tmp/**" in excluded_globs


@readable(
    intent="Verify config loads default ingestignore.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the config loads default ingestignore behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
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
    _, excluded_globs = config.get_exclude_config()
    excluded_globs = set(excluded_globs)

    assert "secrets.txt" in excluded_globs
    assert "data/private/**" in excluded_globs


@readable(
    intent="Verify helper loads ingestignore entries.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the helper loads ingestignore entries behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
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
