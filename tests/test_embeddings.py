"""
Test the EmbeddingService class.
"""
from src.embeddings import EmbeddingService
from src.config.settings import Config


def test_embeddings_fallback(monkeypatch):
    """
    Test fallback to dummy mode when no embeddings are available.
    """
    config = Config()

    # Force connection failure by mocking _get_available_models
    def mock_get_models(self):
        raise ConnectionError()

    monkeypatch.setattr(EmbeddingService, "_get_available_models", mock_get_models)

    service = EmbeddingService(config)

    # Ensure dummy mode is enabled
    assert service.use_dummy is True

    # Generate embedding and validate properties
    embedding = service.generate("test")
    assert isinstance(embedding, list)
    assert len(embedding) == 768
    assert all(v == 0.0 for v in embedding)
