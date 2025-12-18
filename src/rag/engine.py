"""Module that implements a hybrid RAG engine using vector and graph stores."""
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.rag.interfaces.embedding_interface import EmbeddingInterface
from src.rag.interfaces.vector_interface import VectorInterface, ScoredItem
from src.rag.interfaces.graph_interface import GraphInterface
from src.rag.interfaces.cache_interface import CacheServiceProtocol
from src.rag.interfaces.chat_interface import ChatInterface
from src import logger
from src.storage.graph.null_repository import NullGraphRepository
from src.utils.path_discovery import (
    classify_exclude_entries,
    load_excludes_from_files,
    load_enabled_paths_from_files,
    parse_list_env,
    value_as_list,
)


def _build_user_filter(user_id: Optional[str]) -> Dict[str, Any]:
    """Backend-agnostic filter description for user access control."""
    if not user_id:
        return {"visibility": "public"}
    return {
        "user_id": user_id,
        "owner_id": user_id,
        "visibility": "public",
    }


class AppConfig(BaseSettings):
    """Application configuration using Pydantic Settings.

    Automatically loads from:
    1. Default values defined here
    2. Environment variables
    3. .env file

    Pydantic handles all type coercion automatically.
    """

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=True,
        extra='allow',  # Allow dynamic attributes
    )

    # ===== Paths =====
    BASE_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent.parent)
    USER_SETTINGS_FILE: Path = Field(default="data/settings.json")

    # ===== Vector Store (Weaviate) =====
    VECTOR_BACKEND: str = "weaviate"
    WEAVIATE_URL: str = "http://localhost:8080"
    WEAVIATE_API_KEY: str = ""
    WEAVIATE_CLASS: str = "RAGDocument"
    WEAVIATE_TIMEOUT: int = 30
    WEAVIATE_GRPC_PORT: int = 50051
    WEAVIATE_CONNECT_RETRIES: int = 5
    WEAVIATE_CONNECT_BACKOFF: float = 2.0
    WEAVIATE_MULTI_TENANCY: bool = True
    WEAVIATE_DEFAULT_TENANT: str = "tenant-default"
    WEAVIATE_SKIP_INIT_CHECKS: bool = False

    # Vector stores configuration (Django-style)
    VECTOR_STORES: Dict[str, Dict[str, Any]] = Field(default_factory=lambda: {
        "default": {
            "ENGINE": "weaviate",
        }
    })

    # ===== Graph Store (Neo4j) =====
    NEO4J_URI: str = "bolt://neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # ===== Cache (Redis) =====
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    CACHE_TTL: int = 3600

    # ===== Provider (LM Studio) =====
    PROVIDER: str = "lmstudio"
    LMSTUDIO_HOST: str = "host.containers.internal"
    LMSTUDIO_PORT: int = 1234
    LMSTUDIO_EXTRA_HOSTS: List[str] = Field(default_factory=list)
    LMSTUDIO_CHAT_MODEL: str = ""
    LMSTUDIO_REQUIRE_SERVER: bool = False

    # ===== Embeddings =====
    EMBEDDING_DIM: int = 768
    EMBEDDING_MAX_TOKENS: int = 512
    EMBEDDING_BACKEND: str = "lmstudio"
    LOCAL_GPU_EMBED_MODEL: str = "all-MiniLM-L6-v2"
    LOCAL_GPU_DEVICE: str = "cuda"
    LOCAL_GPU_BATCH_SIZE: int = 32

    # ===== Ingestion =====
    DOCS_PATHS: List[str] = Field(default_factory=lambda: [
        "/mnt/Documents/Documents",
        "/mnt/resources/Libros/Aprendizaje",
    ])
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    DOCS_ENABLED_PATHS_FILE: str = ""
    DOCS_ENABLED_PATHS: tuple = ()
    DOCS_EXCLUDE_FILE: str = ""
    DOCS_EXCLUDE_DIRS: tuple = ()
    DOCS_EXCLUDE_GLOBS: tuple = ()
    DOCS_FILE_EXTS: tuple = (
        ".pdf", ".docx", ".doc", ".docm", ".rtf", ".txt", ".md", ".csv",
        ".xlsx", ".xls", ".xlsm", ".xlsb", ".xlt", ".ppt", ".pptx", ".pptm",
        ".pps", ".ppsx", ".odt", ".ods", ".odp", ".eml", ".msg",
        ".py", ".js", ".ts", ".tsx", ".java", ".go", ".rb", ".cs", ".php", ".c", ".cpp",
    )

    # ===== Apps =====
    INSTALLED_APPS: List[str] = Field(default_factory=lambda: [
        "src.providers.lmstudio.apps.LMStudioProviderAppConfig",
        "src.providers.openai.apps.OpenAIProviderAppConfig",
        "src.providers.huggingface.apps.HuggingFaceProviderAppConfig",
        "src.providers.anythingllm.apps.AnythingLLMProviderAppConfig",
        "src.providers.litellm_gateway.apps.LiteLLMGatewayAppConfig",
    ])
    AUTOLOAD_APP_ENTRYPOINTS: bool = False

    # Internal defaults (excluded directories/files)
    DEFAULT_EXCLUDED_FILES: set = Field(default_factory=lambda: {
        ".git", ".hg", ".svn", ".idea", ".vscode", ".vs",
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox",
        ".hypothesis", ".ipynb_checkpoints", ".venv", "venv", "env", "__pypackages__",
        "site-packages", "node_modules", ".next", ".nuxt", ".svelte-kit", ".parcel-cache",
        "build", "dist", "target", "out", "coverage", ".cache", ".gradle", ".terraform",
        ".DS_Store", "*.egg-info", ".eggs", ".coverage", "__MACOSX",
        "*.zip", "*.tar", "*.tar.gz", "*.rar", "*.7z", "*.gz", "*.tar.xz",
    })

    @field_validator('LMSTUDIO_EXTRA_HOSTS', mode='before')
    @classmethod
    def parse_extra_hosts(cls, v):
        """Parse comma-separated string or return list as-is."""
        if isinstance(v, str):
            return [h.strip() for h in v.split(",") if h.strip()]
        return v or []

    @field_validator('WEAVIATE_DEFAULT_TENANT')
    @classmethod
    def set_default_tenant(cls, v, info):
        """Set default tenant based on multi-tenancy setting."""
        data = info.data
        if data.get('WEAVIATE_MULTI_TENANCY'):
            return v or "tenant-default"
        return v or ""

    @field_validator('DOCS_FILE_EXTS', mode='before')
    @classmethod
    def normalize_file_extensions(cls, v):
        """Normalize file extensions to have leading dots."""
        if isinstance(v, str):
            v = parse_list_env(v)

        normalized = set()
        for ext in v:
            ext = str(ext).strip().lower()
            if ext:
                normalized.add(ext if ext.startswith('.') else f'.{ext}')
        return tuple(sorted(normalized))

    @computed_field
    @property
    def LM_EMBED_URL(self) -> str:
        """Primary embeddings endpoint URL."""
        return f"{self._lmstudio_api_roots[0]}/v1/embeddings"

    @computed_field
    @property
    def LM_LLM_URL(self) -> str:
        """Primary completions endpoint URL."""
        return f"{self._lmstudio_api_roots[0]}/v1/completions"

    @computed_field
    @property
    def _lmstudio_api_roots(self) -> List[str]:
        """Ordered list of LM Studio API roots with fallbacks."""
        hosts = []

        # Primary host
        hosts.append(self.LMSTUDIO_HOST)

        # Extra hosts
        hosts.extend(self.LMSTUDIO_EXTRA_HOSTS)

        # Auto-add container fallbacks
        if self.LMSTUDIO_HOST in {"127.0.0.1", "localhost"}:
            hosts.append("host.containers.internal")
        elif self.LMSTUDIO_HOST == "host.containers.internal":
            hosts.append("127.0.0.1")

        # Common container gateways
        for fallback in [
            "gateway.containers.internal", "10.0.2.2", "10.88.0.1",
            "host.docker.internal", "docker.for.mac.host.internal",
            "docker.for.win.host.internal", "172.17.0.1", "localhost"
        ]:
            if fallback not in hosts:
                hosts.append(fallback)

        # Deduplicate while preserving order
        seen = set()
        unique_hosts = []
        for h in hosts:
            if h and h not in seen:
                seen.add(h)
                unique_hosts.append(h)

        return [f"http://{h}:{self.LMSTUDIO_PORT}" for h in unique_hosts]

    def get_enabled_paths(self) -> tuple:
        """Build enabled paths from settings and files."""
        entries = []

        # From setting
        entries.extend(value_as_list(self.DOCS_ENABLED_PATHS))

        # From file
        entries.extend(load_enabled_paths_from_files(self.DOCS_ENABLED_PATHS_FILE))

        return tuple(e.strip() for e in entries if e.strip())

    def get_exclude_config(self) -> tuple[tuple, tuple]:
        """Build exclude configuration (dirs, globs) from settings and files."""
        raw_entries = list(self.DEFAULT_EXCLUDED_FILES)

        # From settings
        raw_entries.extend(value_as_list(self.DOCS_EXCLUDE_DIRS))
        raw_entries.extend(value_as_list(self.DOCS_EXCLUDE_GLOBS))

        # From files
        raw_entries.extend(load_excludes_from_files(self.DOCS_EXCLUDE_FILE))

        dirnames, globs = classify_exclude_entries(raw_entries)
        return tuple(sorted(dirnames)), tuple(sorted(globs))


# Global config instance
config = AppConfig()



class RAGEngine:
    """Hybrid RAG engine combining vector search and graph search."""

    def __init__(
        self,
        embedding: EmbeddingInterface,
        vector_store: VectorInterface,
        graph_store: GraphInterface | None,
        cache: CacheServiceProtocol,
        llm: ChatInterface,
        mark_cache: bool = True,
        default_top_k: int = 5,
        default_tenant: Optional[str] = None,
    ) -> None:
        self.embedding = embedding
        self.vector = vector_store
        self.graph = graph_store or NullGraphRepository()
        self.cache = cache
        self.llm = llm
        self.mark_cache = mark_cache
        self.default_top_k = default_top_k
        self.default_tenant = default_tenant

    def _retrieve_vector_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> str:
        """Retrieve context from vector store."""
        logger.info("Retrieving vector context for query: %s", query)
        vector = self.embedding.generate(query)
        filters = _build_user_filter(user_id)
        hits: List[ScoredItem] = self.vector.search(
            vector=vector,
            top_k=top_k or self.default_top_k,
            filters=filters,
            tenant_id=tenant_id or self.default_tenant,
        ) or []

        parts: List[str] = []
        for h in hits:
            payload = h.payload or {}
            parts.append(payload.get("content") or payload.get("structure_summary") or "")
        return "\n".join([p for p in parts if p])

    def _retrieve_graph_context(self, query: str) -> str:
        """Retrieve context from graph store."""
        logger.info("Retrieving graph context for query: %s", query)
        results = self.graph.search(query)
        return "\n".join(results)

    def _build_prompt(self, query: str, vector_context: str, graph_context: str) -> str:
        """Construct the final prompt for the LLM."""
        context = f"Vector DB:\n{vector_context}\n\nGraph:\n{graph_context}"
        return f"Context:\n{context}\n\nQuestion: {query}\nAnswer in detail:"

    def answer(self, query: str, user_id: Optional[str] = None, tenant_id: Optional[str] = None) -> str:
        """Generate an answer by combining vector + graph context with caching."""
        cache_key = f"{tenant_id or ''}|{user_id or ''}|{query}"
        cached = self.cache.get(cache_key)
        if cached:
            logger.info("Cache hit for query: %s", query)
            return f"[CACHE] {cached}" if self.mark_cache else cached

        vector_context = self._retrieve_vector_context(query, user_id=user_id, tenant_id=tenant_id)
        graph_context = self._retrieve_graph_context(query)

        prompt = self._build_prompt(query, vector_context, graph_context)
        response = self.llm.complete(prompt)

        self.cache.set(cache_key, response)
        logger.info("Cached response for key: %s", cache_key)

        return response
