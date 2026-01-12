from src.workflows.query.embeddings_factory import get_embedding_service


class ConfigStub:
    """Minimal config stub for the embedding factory."""

    EMBEDDING_BACKEND = "lmstudio"


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
