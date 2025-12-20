from src.main import FileDiscoveryService
from src.rag.cli.options import DiscoveryOptions


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
    opts = DiscoveryOptions(
        roots=(str(tmp_path),),
        allowed_exts=set(),
        excluded_dirs={"env"},
        excluded_globs={"logs/**", "*.tmp"},
        follow_symlinks=False,
        progress_every=0,
    )
    files, _ = discovery.discover(opts)

    assert str(keep_dir / "keep.md") in files
    assert all("logs" not in path for path in files)
    assert all(not path.endswith(".tmp") for path in files)


def test_file_discovery_respects_absolute_path_excludes(tmp_path):
    keep = tmp_path / "keep.md"
    keep.write_text("ok", encoding="utf-8")
    skip = tmp_path / "skip.md"
    skip.write_text("no", encoding="utf-8")

    discovery = FileDiscoveryService()
    opts = DiscoveryOptions(
        roots=(str(tmp_path),),
        allowed_exts=set(),
        excluded_dirs=set(),
        excluded_globs={str(skip)},
        follow_symlinks=False,
        progress_every=0,
    )
    files, _ = discovery.discover(opts)

    assert str(keep) in files
    assert str(skip) not in files
