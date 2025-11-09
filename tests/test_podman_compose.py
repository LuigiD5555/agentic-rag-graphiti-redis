from pathlib import Path
import re
import pytest

yaml = pytest.importorskip("yaml")


def _load_compose():
    """
    Load the podman-compose.yml as a Python dict.
    """
    compose_path = Path("podman-compose.yml")
    assert compose_path.exists(), "podman-compose.yml must exist at repository root."
    return yaml.safe_load(compose_path.read_text())


def _port_mapping_allows_variable_or_literal(mapping: str, host_port: int, container_port: int) -> bool:
    """
    Return True if a single ports entry `mapping` allows either a literal mapping
    like "8080:8080" or an env-interpolated form like
    "${HOST_WEAVIATE_HTTP_PORT:-8080}:${WEAVIATE_HTTP_PORT:-8080}".

    Rules:
    - Left side (host) can be the exact host_port or a ${VAR[: -default]}.
    - Right side (container) can be the exact container_port or a ${VAR[: -default]}.
    - We only validate shape and the container side ending up at the required port
      either literally or via env var; same for host side.
    """
    if ":" not in mapping:
        return False

    left, right = mapping.split(":", 1)

    def _is_literal_port(side: str, expected: int) -> bool:
        return side == str(expected)

    def _is_env_var(side: str) -> bool:
        # Accept ${VAR} or ${VAR:-default}
        return bool(re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}", side))

    left_ok = _is_literal_port(left, host_port) or _is_env_var(left)
    right_ok = _is_literal_port(right, container_port) or _is_env_var(right)
    return left_ok and right_ok


def _ports_include_literal_or_env(ports_list, host_port: int, container_port: int) -> bool:
    """
    Return True if `ports_list` contains either the exact literal mapping
    or at least one entry that matches the accepted env-var pattern for the pair.
    """
    expected_literal = f"{host_port}:{container_port}"
    if expected_literal in ports_list:
        return True
    return any(
        _port_mapping_allows_variable_or_literal(p, host_port, container_port)
        for p in ports_list
    )


def test_podman_compose_defines_required_services():
    """
    Validate required services and allow ports expressed as literals or env-interpolated strings.
    """
    compose = _load_compose()
    services = compose.get("services", {})
    for service_name in ("weaviate", "redis", "neo4j", "app"):
        assert service_name in services, f"{service_name} service must be defined."

    weaviate = services["weaviate"]
    assert weaviate["image"].startswith("docker.io/semitechnologies/weaviate:")
    assert _ports_include_literal_or_env(weaviate["ports"], 8080, 8080)
    assert any(
        env.startswith("PERSISTENCE_DATA_PATH=") for env in weaviate.get("environment", [])
    )

    redis = services["redis"]
    assert redis["image"].startswith("docker.io/library/redis")
    assert _ports_include_literal_or_env(redis["ports"], 6379, 6379)

    neo4j = services["neo4j"]
    assert neo4j["image"].startswith("docker.io/library/neo4j")
    assert _ports_include_literal_or_env(neo4j["ports"], 7474, 7474)
    assert _ports_include_literal_or_env(neo4j["ports"], 7687, 7687)

    app = services["app"]
    assert app.get("env_file") == ".env"
    volumes = app.get("volumes", [])
    assert any(volume.endswith(":Z") for volume in volumes), "App volume must mount host documents."
