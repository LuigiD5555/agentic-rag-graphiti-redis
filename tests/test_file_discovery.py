from __future__ import annotations

from src.main import FileDiscoveryService


def test_file_discovery_respects_directory_and_glob_excludes(tmp_path):
    keep_dir = tmp_path / "keep"
    keep_dir.mkdir()
    (keep_dir / "keep.md").write_text("ok", encoding="utf-8")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "skip.log").write_text("skip", encoding="utf-8")
    nested_logs = logs_dir / "nested"
    nested_logs.mkdir()
    (nested_logs / "data.txt").write_text("skip", encoding="utf-8")

    env_dir = tmp_path / "env"
    env_dir.mkdir()
    (env_dir / "data.md").write_text("skip", encoding="utf-8")

    (tmp_path / "notes.tmp").write_text("tmp", encoding="utf-8")

    discovery = FileDiscoveryService()
    files, _ = discovery.discover(
        roots=[str(tmp_path)],
        allowed_extensions=set(),
        excluded_directory_names={"env"},
        excluded_path_globs={"logs/**", "*.tmp"},
        follow_symbolic_links=False,
        progress_every=0,
    )

    assert str(keep_dir / "keep.md") in files
    assert all("logs" not in path for path in files)
    assert all(not path.endswith(".tmp") for path in files)
