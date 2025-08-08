from src.config import Config


def test_config_defaults():
    config = Config()
    assert config.QDRANT_URL.startswith("http"), "QDRANT_URL must be a valid URL"
    assert isinstance(config.CHUNK_SIZE, int)
    assert isinstance(config.CHUNK_OVERLAP, int)
