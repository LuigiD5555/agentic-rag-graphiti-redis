from __future__ import annotations

from src.storage.vector.weaviate_repository import WeaviateRepository


def _make_repo(timeout: int = 15) -> WeaviateRepository:
    repo = object.__new__(WeaviateRepository)
    repo._timeout = timeout
    repo._connect_retries = 1
    repo._connect_backoff = 0.1
    return repo


def test_nodes_payload_has_leader_detects_various_shapes():
    repo = _make_repo()

    leader_payload = {
        "nodes": [
            {"role": "FOLLOWER"},
            {"role": "LEADER", "status": "READY"},
        ]
    }
    assert repo._nodes_payload_has_leader(leader_payload)

    alt_payload = [
        {"raft": {"state": "Leader"}, "status": "Healthy"},
    ]
    assert repo._nodes_payload_has_leader(alt_payload)

    missing = {"nodes": [{"role": "FOLLOWER"}]}
    assert not repo._nodes_payload_has_leader(missing)


def test_build_additional_config_uses_timeout_values():
    repo = _make_repo(timeout=42)
    additional = repo._build_additional_config()

    # Depending on client version, AdditionalConfig may be None; guard accordingly.
    assert additional is not None
    assert additional.timeout.init == 42
    assert additional.timeout.query == 42
    assert additional.timeout.insert == 42
