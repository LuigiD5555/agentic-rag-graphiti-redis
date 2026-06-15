from pathlib import Path
import re
import pytest
from pytest_readable import readable


yaml = pytest.importorskip("yaml")
pytestmark = pytest.mark.preflight_host


def _load_compose():
    """
    Load the podman-compose.yml as a Python dict.
    """
    compose_path = Path(__file__).resolve().parents[3] / "podman-compose.yml"
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
    normalized = mapping.strip()
    if normalized[:1] == normalized[-1:] and normalized[:1] in {'"', "'"}:
        normalized = normalized[1:-1].strip()

    if ":" not in normalized:
        return False

    def _is_literal_port(side: str, expected: int) -> bool:
        return side == str(expected)

    def _is_env_var(side: str) -> bool:
        return bool(re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}", side))

    def _is_literal_ip(value: str) -> bool:
        return bool(re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", value))

    host_and_container = normalized
    ip_match = re.match(rf"^(?P<ip>(?:\d{{1,3}}\.){{3}}\d{{1,3}}):(?P<rest>.+)$", host_and_container)
    if ip_match:
        ip_part = ip_match.group("ip")
        if not _is_literal_ip(ip_part):
            return False
        host_and_container = ip_match.group("rest")

    if ":" not in host_and_container:
        return False

    host_part, container_part = host_and_container.rsplit(":", 1)
    left = host_part.strip()
    right = container_part.strip()

    def _is_literal_ip(value: str) -> bool:
        return bool(re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", value))

    left_ok = _is_literal_port(left, host_port) or _is_env_var(left)
    right_ok = _is_literal_port(right, container_port) or _is_env_var(right)
    return left_ok and right_ok


def _ports_include_literal_or_env(ports_list, host_port: int, container_port: int) -> bool:
    """
    Return True if `ports_list` contains either the exact literal mapping
    or at least one entry that matches the accepted env-var pattern for the pair.
    """
    return any(
        _port_mapping_allows_variable_or_literal(p, host_port, container_port)
        for p in ports_list
    )


@readable(
    intent="Validate required services and allow ports expressed as literals or env-interpolated strings.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the podman compose defines required services behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_podman_compose_defines_required_services():
    """
    Validate required services and allow ports expressed as literals or env-interpolated strings.
    """
    compose = _load_compose()
    services = compose.get("services", {})
    for service_name in ("weaviate", "neo4j", "app"):
        assert service_name in services, f"{service_name} service must be defined."

    weaviate = services["weaviate"]
    assert weaviate["image"].startswith("docker.io/semitechnologies/weaviate:")
    assert _ports_include_literal_or_env(weaviate["ports"], 8080, 8080)
    assert any(
        env.startswith("PERSISTENCE_DATA_PATH=") for env in weaviate.get("environment", [])
    )

    neo4j = services["neo4j"]
    assert neo4j["image"].startswith("docker.io/library/neo4j")
    assert _ports_include_literal_or_env(neo4j["ports"], 7474, 7474)
    assert _ports_include_literal_or_env(neo4j["ports"], 7687, 7687)

    app = services["app"]
    assert app.get("env_file") == ".env"
    volumes = app.get("volumes", [])
    assert any(volume.endswith(":Z") for volume in volumes), "App volume must mount host documents."
