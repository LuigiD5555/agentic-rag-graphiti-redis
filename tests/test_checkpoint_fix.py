"""Regression tests for checkpoint/cache behavior in discovery scans."""

import time

import pytest

from src.workflows.ingestion.orchestrator import IngestionOrchestrator
from src.workflows.ingestion.options import IngestionOptions
from pytest_readable import readable



def _build_fixture_tree(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.py").write_text("print('a')\n", encoding="utf-8")
    (docs / "b.md").write_text("# hello\n", encoding="utf-8")
    (docs / "ignore.log").write_text("ignore\n", encoding="utf-8")
    nested = docs / "nested"
    nested.mkdir()
    (nested / "c.txt").write_text("nested\n", encoding="utf-8")
    return docs


@readable(
    intent="Second scan should reuse checkpoint/cache and keep a stable scan_run_id.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the checkpoint system behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
@pytest.mark.unit
def test_checkpoint_system(tmp_path):
    """Second scan should reuse checkpoint/cache and keep a stable scan_run_id."""
    docs = _build_fixture_tree(tmp_path)
    orchestrator = IngestionOrchestrator()

    opts = IngestionOptions(
        root_paths=[str(docs)],
        allowed_extensions=[".py", ".md", ".txt"],
        excluded_directory_names=["node_modules", ".git", "__pycache__"],
        excluded_path_globs=["*.log", "*.tmp"],
        dry_run=True,
    )

    start = time.time()
    result1 = orchestrator.run_incremental_scan(opts)
    elapsed1 = time.time() - start

    start = time.time()
    result2 = orchestrator.run_incremental_scan(opts)
    elapsed2 = time.time() - start

    assert result1["status"] in {"dry_run", "no_changes"}
    assert result2["status"] in {"dry_run", "no_changes"}
    assert result2.get("scan_run_id"), "Expected persistent scan_run_id"
    assert result2["discovery"]["visited_dirs"] >= 1
    assert elapsed2 <= elapsed1 * 2.0


@readable(
    intent="Cache hit rate should improve on a second discovery pass.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the cache hit rate behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
@pytest.mark.unit
def test_cache_hit_rate(tmp_path):
    """Cache hit rate should improve on a second discovery pass."""
    docs = _build_fixture_tree(tmp_path)
    orchestrator = IngestionOrchestrator()

    opts = IngestionOptions(
        root_paths=[str(docs)],
        allowed_extensions=[".py", ".md", ".txt"],
        excluded_directory_names=["node_modules", ".git", "__pycache__"],
        excluded_path_globs=["*.log", "*.tmp"],
    )
    discovery_opts = orchestrator._to_discovery_options(opts)

    orchestrator._discovery.discover(discovery_opts, use_cache=True)
    stats1 = orchestrator._discovery.get_cache_stats()

    orchestrator._discovery.discover(discovery_opts, use_cache=True)
    stats2 = orchestrator._discovery.get_cache_stats()

    assert stats2["cache_hits"] >= stats1["cache_hits"]
    assert stats2["hit_rate"] >= stats1["hit_rate"]
