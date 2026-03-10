from pytest_readable import readable
import pytest

from src.workflows.query.embeddings_factory import get_embedding_service, _pick_context_model


class ConfigStub:
    """Minimal config stub for the embedding factory."""

    EMBEDDING_BACKEND = "lmstudio"
    EMBEDDING_MODEL = "base-embed-model"
    EMBEDDING_MODEL_QUERY = ""
    EMBEDDING_MODEL_INGEST = ""
    LMSTUDIO_EMBED_MODEL = ""


class ProviderStub:
    def __init__(self, value):
        self._value = value

    def embeddings(self):
        return self._value


@readable(
    intent="Ensure the factory delegates to the provider and returns its embedding service.",
    steps=[
        "Create a provider stub with a sentinel object",
        "Call get_embedding_service with that provider",
    ],
    criteria=[
        "The returned service is exactly the provider object",
    ],
)
def test_embeddings_factory_delegates_to_provider():
    sentinel = object()
    service = get_embedding_service(ConfigStub(), provider=ProviderStub(sentinel))
    assert service is sentinel


@readable(
    intent="Validate query model priority when a dedicated override exists.",
    steps=[
        "Set EMBEDDING_MODEL_QUERY",
        "Resolve model for query context",
    ],
    criteria=[
        "The query override model is selected",
    ],
)
def test_pick_context_model_prefers_query_override():
    cfg = ConfigStub()
    cfg.EMBEDDING_MODEL_QUERY = "query-embed-model"
    assert _pick_context_model(cfg, "query") == "query-embed-model"


@readable(
    intent="Validate ingest model priority when a dedicated override exists.",
    steps=[
        "Set EMBEDDING_MODEL_INGEST",
        "Resolve model for ingest context",
    ],
    criteria=[
        "The ingest override model is selected",
    ],
)
def test_pick_context_model_prefers_ingest_override():
    cfg = ConfigStub()
    cfg.EMBEDDING_MODEL_INGEST = "ingest-embed-model"
    assert _pick_context_model(cfg, "ingest") == "ingest-embed-model"


@readable(
    intent="Cover invalid context failure and ensure an explicit error is raised.",
    steps=[
        "Request an unsupported context",
        "Capture the exception",
    ],
    criteria=[
        "A ValueError is raised with an unknown-context message",
    ],
)
def test_pick_context_model_rejects_unknown_context():
    with pytest.raises(ValueError, match="Unknown embedding context"):
        _pick_context_model(ConfigStub(), "invalid")
