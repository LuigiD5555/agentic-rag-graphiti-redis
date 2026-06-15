from typing import Optional

import pytest
import requests

from src.backends.llm.lmstudio.embeddings import EmbeddingService
from pytest_readable import readable



class ConfigStub:
    def __init__(self, embed_model: Optional[str] = None, dim: int = 4, hosts: Optional[list[str]] = None) -> None:
        base_hosts = hosts or ["http://localhost:8080", "http://host.containers.internal:8080"]
        self.LMSTUDIO_API_ROOTS = base_hosts
        self.LM_EMBED_URLS = [f"{root}/v1/embeddings" for root in base_hosts]
        self.LM_LLM_URLS = [f"{root}/v1/completions" for root in base_hosts]
        self.LM_EMBED_URL = self.LM_EMBED_URLS[0]
        self.EMBEDDING_DIM = dim
        self.EMBEDDING_MODEL = embed_model
        self.LMSTUDIO_REQUIRE_SERVER = False


class ModelManagerStub:
    def __init__(self, model_name: Optional[str], api_root: str = "http://localhost:8080") -> None:
        self._model_name = model_name
        self.api_root = api_root

    def get_model_dimensions(self, model_name: str) -> Optional[int]:
        """Return dimension size for model."""
        return None  # Let config handle dimensions


class ResponseStub:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


@readable(
    intent="Test that EMBEDDING_MODEL must be explicitly configured.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the embeddings requires explicit model behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_embeddings_requires_explicit_model():
    """Test that EMBEDDING_MODEL must be explicitly configured."""
    config = ConfigStub(embed_model=None, dim=6)
    manager = ModelManagerStub(model_name=None)

    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL must be explicitly configured"):
        EmbeddingService(config, manager)


@readable(
    intent="Verify embeddings parse valid response.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the embeddings parse valid response behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_embeddings_parse_valid_response(monkeypatch):
    config = ConfigStub(embed_model="test-embed", dim=4)
    manager = ModelManagerStub(model_name="test-embed")

    service = EmbeddingService(config, manager)

    def fake_post(*_args, **_kwargs):
        return ResponseStub({"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]})

    monkeypatch.setattr(service, "_post_json", fake_post)
    vector = service.generate("tokenize this text")

    assert vector == pytest.approx([0.1, 0.2, 0.3, 0.4])


@readable(
    intent="Verify embeddings invalid dimension returns dummy.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the embeddings invalid dimension returns dummy behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_embeddings_invalid_dimension_returns_dummy(monkeypatch):
    config = ConfigStub(embed_model="test-embed", dim=5)
    manager = ModelManagerStub(model_name="test-embed")

    service = EmbeddingService(config, manager)

    def fake_post(*_args, **_kwargs):
        return ResponseStub({"data": [{"embedding": [0.1, 0.2]}]})

    monkeypatch.setattr(service, "_post_json", fake_post)
    vector = service.generate("text")

    assert vector == [0.0] * 5


@readable(
    intent="Verify embeddings attempts fallback hosts.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the embeddings attempts fallback hosts behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_embeddings_attempts_fallback_hosts(monkeypatch):
    config = ConfigStub(embed_model="test-embed", dim=4)
    manager = ModelManagerStub(model_name="test-embed", api_root=config.LMSTUDIO_API_ROOTS[0])

    service = EmbeddingService(config, manager)

    attempts = {"count": 0}

    def fake_post(url, *_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise requests.exceptions.ConnectionError("boom")
        return ResponseStub({"data": [{"embedding": [0.4, 0.5, 0.6, 0.7]}]})

    monkeypatch.setattr(service, "_post_json", fake_post)

    vector = service.generate("text")

    assert attempts["count"] == 2
    assert vector == pytest.approx([0.4, 0.5, 0.6, 0.7])


@readable(
    intent="Test that missing EMBEDDING_MODEL raises RuntimeError.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the embeddings require live without model raises behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_embeddings_require_live_without_model_raises():
    """Test that missing EMBEDDING_MODEL raises RuntimeError."""
    config = ConfigStub(embed_model=None, dim=4)
    config.LMSTUDIO_REQUIRE_SERVER = True
    manager = ModelManagerStub(model_name=None)

    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL must be explicitly configured"):
        EmbeddingService(config, manager)


@readable(
    intent="Verify embeddings require live raises on connection failure.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the embeddings require live raises on connection failure behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_embeddings_require_live_raises_on_connection_failure(monkeypatch):
    config = ConfigStub(embed_model="test-embed", dim=4)
    config.LMSTUDIO_REQUIRE_SERVER = True
    manager = ModelManagerStub(model_name="test-embed", api_root=config.LMSTUDIO_API_ROOTS[0])

    service = EmbeddingService(config, manager)

    def fake_post(url, *_args, **_kwargs):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(service, "_post_json", fake_post)

    with pytest.raises(RuntimeError):
        service.generate("texto")
