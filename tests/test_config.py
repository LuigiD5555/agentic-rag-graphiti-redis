from src.config.settings import Config


def test_config_defaults():
    config = Config()
    assert config.WEAVIATE_URL.startswith("http"), "WEAVIATE_URL must be a valid URL"
    assert isinstance(config.WEAVIATE_CLASS, str)
    assert isinstance(config.WEAVIATE_MULTI_TENANCY, bool)
    assert isinstance(config.WEAVIATE_GRPC_PORT, int)
    assert isinstance(config.WEAVIATE_CONNECT_RETRIES, int)
    assert isinstance(config.WEAVIATE_CONNECT_BACKOFF, float)
    assert isinstance(config.CHUNK_SIZE, int)
    assert isinstance(config.CHUNK_OVERLAP, int)
