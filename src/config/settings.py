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
        self.LMSTUDIO_EXTRA_HOSTS = [
            host.strip()
            for host in os.getenv("LMSTUDIO_EXTRA_HOSTS", "").split(",")
            if host.strip()
        ]
        self.LMSTUDIO_CHAT_MODEL = os.getenv("LMSTUDIO_CHAT_MODEL", "")
        self.LMSTUDIO_REQUIRE_SERVER = os.getenv("LMSTUDIO_REQUIRE_SERVER", "").lower() in ("1", "true", "yes")

        # ----- Document ingestion -----
        self.DOCS_PATH = os.getenv("DOCS_PATH", "/mnt/Documents/Documents")
        self.CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
        self.CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))

        # ----- Cache TTL -----
        self.CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))

    @property
    def LM_EMBED_URL(self):
        """Embeddings endpoint URL for LM Studio."""
        return self.LM_EMBED_URLS[0]

    @property
    def LM_EMBED_URLS(self):
        """List of embeddings endpoints including fallbacks."""
        return [f"{root}/v1/embeddings" for root in self._lmstudio_api_roots()]

    @property
    def LM_LLM_URL(self):
        """Completions endpoint URL for LM Studio."""
        return self.LM_LLM_URLS[0]

    @property
    def LM_LLM_URLS(self):
        """List of completion endpoints including fallbacks."""
        return [f"{root}/v1/completions" for root in self._lmstudio_api_roots()]

    def _lmstudio_api_roots(self):
        """
        Ordered list of candidate LM Studio API roots (host + port) including fallbacks.

        Priority:
            1) Explicit LMSTUDIO_HOST
            2) Any hosts supplied via LMSTUDIO_EXTRA_HOSTS (comma-separated)
            3) Automatically add host.containers.internal when primary host is localhost/loopback
               so containers can reach the host
            4) Automatically add 127.0.0.1 when primary host is host.containers.internal
               to keep local dev working without extra vars
        """
        unique_hosts = []

        def _add(hostname: str):
            if hostname and hostname not in unique_hosts:
                unique_hosts.append(hostname)

        _add(self.LMSTUDIO_HOST)
        for host in self.LMSTUDIO_EXTRA_HOSTS:
            _add(host)

        loopback_hosts = {"127.0.0.1", "localhost"}
        if self.LMSTUDIO_HOST in loopback_hosts:
            _add("host.containers.internal")
        if self.LMSTUDIO_HOST == "host.containers.internal":
            _add("127.0.0.1")

        podman_defaults = [
            "gateway.containers.internal",
            "10.0.2.2",   # slirp4netns default gateway
            "10.88.0.1",  # podman bridge default
        ]
        docker_defaults = [
            "host.docker.internal",
            "docker.for.mac.host.internal",
            "docker.for.win.host.internal",
            "172.17.0.1",
        ]

        for fallback in [*podman_defaults, *docker_defaults, "localhost"]:
            _add(fallback)

        return [f"http://{host}:{self.LMSTUDIO_PORT}" for host in unique_hosts]

    @property
    def LMSTUDIO_API_ROOTS(self):
        """Public accessor for candidate API roots."""
        return self._lmstudio_api_roots()
