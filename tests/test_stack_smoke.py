from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = PROJECT_ROOT / "podman-compose.yml"


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_STACK_SMOKE") != "1", reason="Set RUN_STACK_SMOKE=1 to enable stack smoke test")
def test_podman_compose_stack_smoke():
    """Spin up podman-compose stack and ensure core services stay Up."""
    compose_cmd = os.getenv("PODMAN_COMPOSE_CMD", "podman-compose")
    compose_parts = shlex.split(compose_cmd)
    if not compose_parts:
        pytest.skip("PODMAN_COMPOSE_CMD is empty")

    executable = compose_parts[0]
    if shutil.which(executable) is None:
        pytest.skip(f"Compose executable '{executable}' not found in PATH")

    base_cmd = compose_parts + ["-f", str(COMPOSE_FILE)]

    try:
        subprocess.run(base_cmd + ["up", "-d"], cwd=PROJECT_ROOT, check=True)

        ps = subprocess.run(
            base_cmd + ["ps"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        output = ps.stdout + ps.stderr

        expected = ["weaviate", "redis", "neo4j", "app"]
        missing = [name for name in expected if name not in output]
        assert not missing, f"Missing services in compose output: {missing}\n{output}"

        for line in output.splitlines():
            for name in expected:
                if name in line:
                    assert "Up" in line, f"Service '{name}' not reported as Up: {line}\n{output}"

    finally:
        subprocess.run(base_cmd + ["down", "--volumes", "--remove-orphans"], cwd=PROJECT_ROOT, check=False)
