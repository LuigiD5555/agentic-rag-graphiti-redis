from src.workflows.query.conf import Config
from pytest_readable import readable



@readable(
    intent="Verify config defaults.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the config defaults behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
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
    assert isinstance(config.DOCS_PATHS, list)
    assert config.DOCS_PATHS

    # LM Studio endpoints derived from host/port
    assert config.LM_EMBED_URL.endswith("/v1/embeddings")
    assert config.LM_LLM_URL.endswith("/v1/completions")
    assert isinstance(config.LMSTUDIO_CHAT_MODEL, str)
    assert config.LMSTUDIO_REQUIRE_SERVER is False

    api_roots = config.LMSTUDIO_API_ROOTS
    assert isinstance(api_roots, list)
    if api_roots:
        assert api_roots[0].startswith("http://")
        assert config.LM_EMBED_URLS[0].startswith(api_roots[0])
        assert config.LM_LLM_URLS[0].startswith(api_roots[0])
