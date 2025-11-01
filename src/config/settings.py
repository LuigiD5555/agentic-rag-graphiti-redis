import os
from dotenv import load_dotenv


class Config:
    """
    Centralized runtime configuration.

    Notes:
    - Vector DB backend is selected via VECTOR_BACKEND; default is "weaviate".
    """

    def __init__(self):
        load_dotenv()

        # ----- Vector DB backend selection -----
        # Current supported value: "weaviate"
        self.VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "weaviate").lower()

        # ----- Weaviate configuration -----
        self.WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://localhost:8080")
        self.WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY", "")
        self.WEAVIATE_CLASS = os.getenv("WEAVIATE_CLASS", "RAGDocument")
        # If running native multitenancy, keep True; else you can emulate with prefixes in the repository.
        self.WEAVIATE_MULTI_TENANCY = os.getenv("WEAVIATE_MULTI_TENANCY", "true").lower() in ("1", "true", "yes")
        self.WEAVIATE_TIMEOUT = int(os.getenv("WEAVIATE_TIMEOUT", "30"))
        self.WEAVIATE_GRPC_PORT = int(os.getenv("WEAVIATE_GRPC_PORT", "50051"))
        self.WEAVIATE_CONNECT_RETRIES = int(os.getenv("WEAVIATE_CONNECT_RETRIES", "5"))
        self.WEAVIATE_CONNECT_BACKOFF = float(os.getenv("WEAVIATE_CONNECT_BACKOFF", "2.0"))

        # ----- Embeddings -----
        self.EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

        # ----- Redis -----
        self.REDIS_HOST = os.getenv("REDIS_HOST", "redis")
        self.REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

        # ----- Neo4j -----
        self.NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        self.NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
        self.NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

        # ----- LM Studio host & port -----
        self.LMSTUDIO_HOST = os.getenv("LMSTUDIO_HOST", "host.containers.internal")
        self.LMSTUDIO_PORT = int(os.getenv("LMSTUDIO_PORT", "1234"))

        # ----- Document ingestion -----
        self.DOCS_PATH = os.getenv("DOCS_PATH", "/mnt/Documents/Documents")
        self.CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
        self.CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))

        # ----- Cache TTL -----
        self.CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))

    @property
    def LM_EMBED_URL(self):
        """Embeddings endpoint URL for LM Studio."""
        return f"http://{self.LMSTUDIO_HOST}:{self.LMSTUDIO_PORT}/v1/embeddings"

    @property
    def LM_LLM_URL(self):
        """Completions endpoint URL for LM Studio."""
        return f"http://{self.LMSTUDIO_HOST}:{self.LMSTUDIO_PORT}/v1/completions"
