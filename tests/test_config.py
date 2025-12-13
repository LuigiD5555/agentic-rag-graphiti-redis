from src.settings import Config


def test_config_defaults():
    config = Config()

    # Vector database defaults
    assert config.WEAVIATE_URL.startswith("http")
    assert isinstance(config.WEAVIATE_CLASS, str)
    assert isinstance(config.WEAVIATE_MULTI_TENANCY, bool)
    assert isinstance(config.WEAVIATE_GRPC_PORT, int)
    assert isinstance(config.WEAVIATE_CONNECT_RETRIES, int)
    assert isinstance(config.WEAVIATE_CONNECT_BACKOFF, float)

    # Ingestion pipeline defaults
    assert isinstance(config.CHUNK_SIZE, int)
    assert isinstance(config.CHUNK_OVERLAP, int)

    # LM Studio endpoints derived from host/port
    assert config.LM_EMBED_URL.endswith("/v1/embeddings")
    assert config.LM_LLM_URL.endswith("/v1/completions")
    assert config.LMSTUDIO_CHAT_MODEL == ""
    assert config.LMSTUDIO_REQUIRE_SERVER is False

    api_roots = config.LMSTUDIO_API_ROOTS
    assert api_roots, "LMSTUDIO_API_ROOTS should provide at least one endpoint"
    assert api_roots[0].startswith("http://")
    assert any("host.containers.internal" in root for root in api_roots)
    assert any("127.0.0.1" in root for root in api_roots)
    assert any("gateway.containers.internal" in root for root in api_roots)
    assert config.LM_EMBED_URLS[0].startswith(api_roots[0])
    assert config.LM_LLM_URLS[0].startswith(api_roots[0])
