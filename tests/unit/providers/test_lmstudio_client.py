import pytest
import requests

from src.backends.llm.lmstudio.client import LLMService


class ConfigStub:
    LMSTUDIO_API_ROOTS = ["http://fail-host:1234", "http://good-host:1234"]
    LMSTUDIO_HOST = "fail-host"
    LMSTUDIO_PORT = 1234
    LMSTUDIO_CHAT_MODEL = ""
    LMSTUDIO_REQUIRE_SERVER = False


class ModelManagerStub:
    def __init__(self):
        self.api_root = ConfigStub.LMSTUDIO_API_ROOTS[0]

    def get_first_language_model(self):
        return "stub-llm"


class ResponseStub:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_llm_service_fallback(monkeypatch):
    service = LLMService(ConfigStub, ModelManagerStub())

    def fake_post(url, json, timeout):
        if "fail-host" in url:
            raise requests.exceptions.ConnectionError("down")
        return ResponseStub({
            "choices": [
                {"message": {"content": "response"}}
            ]
        })

    monkeypatch.setattr(requests, "post", fake_post)

    text = service.complete("hello")

    assert text == "response"
    assert service.api_root == ConfigStub.LMSTUDIO_API_ROOTS[1]


def test_llm_service_respects_explicit_model():
    class ConfigExplicit(ConfigStub):
        LMSTUDIO_CHAT_MODEL = "microsoft/phi-4-mini-reasoning"

    service = LLMService(ConfigExplicit, ModelManagerStub())
    assert service.model == "microsoft/phi-4-mini-reasoning"


def test_llm_service_require_live_raises(monkeypatch):
    class ConfigRequire(ConfigStub):
        LMSTUDIO_REQUIRE_SERVER = True

    service = LLMService(ConfigRequire, ModelManagerStub())

    def fake_post(url, json, timeout):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(RuntimeError):
        service.complete("hello")
