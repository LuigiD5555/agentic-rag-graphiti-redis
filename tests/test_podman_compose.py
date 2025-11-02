from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


def _load_compose():
    compose_path = Path("podman-compose.yml")
    assert compose_path.exists(), "podman-compose.yml must exist at repository root."
    return yaml.safe_load(compose_path.read_text())


def test_podman_compose_defines_required_services():
    compose = _load_compose()
    services = compose.get("services", {})
    for service_name in ("weaviate", "redis", "neo4j", "app"):
        assert service_name in services, f"{service_name} service must be defined."

    weaviate = services["weaviate"]
    assert weaviate["image"].startswith("docker.io/semitechnologies/weaviate:")
    assert "8080:8080" in weaviate["ports"]
    assert any(
        env.startswith("PERSISTENCE_DATA_PATH=") for env in weaviate.get("environment", [])
    )

    redis = services["redis"]
    assert redis["image"].startswith("docker.io/library/redis")
    assert "6379:6379" in redis["ports"]

    neo4j = services["neo4j"]
    assert neo4j["image"].startswith("docker.io/library/neo4j")
    assert {"7474:7474", "7687:7687"}.issubset(set(neo4j["ports"]))

    app = services["app"]
    assert app.get("env_file") == ".env"
    volumes = app.get("volumes", [])
    assert any(volume.endswith(":Z") for volume in volumes), "App volume must mount host documents."
