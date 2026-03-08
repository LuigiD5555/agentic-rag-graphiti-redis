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


def test_embeddings_factory_delegates_to_provider():
    """Ensure the factory returns the provider's embedding service."""
    sentinel = object()
    service = get_embedding_service(ConfigStub(), provider=ProviderStub(sentinel))
    assert service is sentinel


def test_pick_context_model_prefers_query_override():
    cfg = ConfigStub()
    cfg.EMBEDDING_MODEL_QUERY = "query-embed-model"
    assert _pick_context_model(cfg, "query") == "query-embed-model"


def test_pick_context_model_prefers_ingest_override():
    cfg = ConfigStub()
    cfg.EMBEDDING_MODEL_INGEST = "ingest-embed-model"
    assert _pick_context_model(cfg, "ingest") == "ingest-embed-model"
