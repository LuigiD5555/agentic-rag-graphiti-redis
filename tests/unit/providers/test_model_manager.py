import requests
import pytest

from src.backends.llm.lmstudio.model_manager import ModelManager
from pytest_readable import readable



class ResponseStub:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@readable(
    intent="Verify model manager uses fallback host.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the model manager uses fallback host behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_model_manager_uses_fallback_host(monkeypatch):
    hosts = ["http://fail-host:1234", "http://good-host:1234"]

    def fake_get(url, timeout):
        if "fail-host" in url:
            raise requests.exceptions.ConnectionError("fail")
        return ResponseStub({"data": [{"id": "test-embed"}, {"id": "test-chat"}]})

    monkeypatch.setattr(requests, "get", fake_get)

    mm = ModelManager(hosts)

    assert mm.api_root == hosts[1]
    assert mm.embedding_models == ["test-embed"]
    assert mm.language_models == ["test-chat"]
    assert hosts[0] in mm.failed_roots


@readable(
    intent="Verify model manager records failure when all hosts unreachable.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the model manager records failure when all hosts unreachable behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_model_manager_records_failure_when_all_hosts_unreachable(monkeypatch):
    hosts = ["http://nowhere:1234"]

    def fake_get(url, timeout):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(requests, "get", fake_get)

    mm = ModelManager(hosts)
    assert mm.api_root == hosts[0]
    assert mm.embedding_models == []
    assert mm.language_models == []
    assert hosts[0] in mm.failed_roots


@readable(
    intent="Verify model manager require live raises.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the model manager require live raises behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_model_manager_require_live_raises(monkeypatch):
    hosts = ["http://fail-host:1234"]

    def fake_get(url, timeout):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(RuntimeError):
        ModelManager(hosts, require_live=True)
