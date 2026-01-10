"""Module that implements a hybrid RAG engine using vector and graph stores."""
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource

from src.rag.interfaces.embedding_interface import EmbeddingInterface
from src.rag.interfaces.vector_interface import VectorInterface, ScoredItem
from src.rag.interfaces.graph_interface import GraphInterface
from src.rag.interfaces.cache_interface import CacheServiceProtocol
from src.rag.interfaces.chat_interface import ChatInterface
from src import logger, settings
from src.storage.graph.null_repository import NullGraphRepository
from src.utils.path_discovery import (
    classify_exclude_entries,
    load_excludes_from_files,
    parse_list_env,
    value_as_list,
)


def _load_json_settings(json_path: Path) -> Dict[str, Any]:
    """Load settings from JSON file if it exists."""
    try:
        if json_path.is_file():
            content = json_path.read_text(encoding='utf-8')
            data = json.loads(content)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


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
    BASE_DIR: Path = Field(default_factory=lambda: settings.BASE_DIR)
    USER_SETTINGS_FILE: Path = Field(default_factory=lambda: settings.USER_SETTINGS_FILE)

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
    VECTOR_STORES: Dict[str, Dict[str, Any]] = Field(default_factory=lambda: settings.VECTOR_STORES)

    # ===== Graph Store (Neo4j) =====
    NEO4J_URI: str = "bolt://neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # ===== Cache (Redis) =====
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = Field(default_factory=lambda: settings.REDIS_PASSWORD)
    CACHE_TTL: int = Field(default_factory=lambda: settings.CACHE_TTL)

    # ===== API Configuration =====
    API_MODE: str = "openai"  # "openai" or "ollama"
    OPENAI_API_BASE: str = "http://127.0.0.1:1234/v1"
    OPENAI_API_KEY: str = "lm-studio"

    # ===== Provider (LM Studio) =====
    PROVIDER: str = "lmstudio"
    LMSTUDIO_HOST: str = "host.containers.internal"
    LMSTUDIO_PORT: int = 1234
    LMSTUDIO_EXTRA_HOSTS: List[str] = Field(default_factory=list)
    LMSTUDIO_CHAT_MODEL: str = ""
    LMSTUDIO_REQUIRE_SERVER: bool = False
    LMSTUDIO_KEEPALIVE_CHAT: int = 60
    LMSTUDIO_KEEPALIVE_EMBED: int = 30
    LMSTUDIO_KEEPALIVE_RERANK: int = 30
    LMSTUDIO_API_ROOTS: List[str] = Field(default_factory=list)

    # ===== Embeddings =====
    # Embeddings are provided by LM Studio with automatic dimension detection
    EMBEDDING_MODEL: str = ""  # Explicit model name (required, e.g., text-embedding-nomic-embed-text-v2-moe)
    EMBEDDING_DIM: int = Field(default_factory=lambda: settings.EMBEDDING_DIM)
    EMBEDDING_MAX_TOKENS: int = Field(default_factory=lambda: settings.EMBEDDING_MAX_TOKENS)

    # Dual Embeddings System
    ENABLE_DUAL_EMBEDDINGS: bool = False
    SMALL_EMBEDDING_MODEL: str = ""
    LARGE_EMBEDDING_MODEL: str = ""
    SMALL_EMBEDDING_DIM: int = 384
    LARGE_EMBEDDING_DIM: int = 768
    DUAL_EMBEDDINGS_SMALL_COLLECTION: str = "RAGDocument384"
    DUAL_EMBEDDINGS_LARGE_COLLECTION: str = "RAGDocument768"

    # ===== RAG Configuration =====
    ENABLE_RAG_GATING: bool = True
    MIN_RELEVANCE_SCORE: float = 0.5
    ENABLE_RERANKER: bool = False

    # RAG Profile System
    RAG_PROFILE: str = "auto"
    RAG_PERFORMANCE_PROFILE: str = "performance"
    RESOURCE_MODE: str = "performance"

    # RAG Performance Optimizations
    RAG_EMBED_BATCH_SIZE: int = 16
    RAG_EMBED_LOG_EVERY_N_CHUNKS: int = 20
    RAG_PARALLEL_WORKERS: int = 3
    RAG_PIPELINE_WORKERS: int = 3

    # RAG Caching
    RAG_EMBED_CACHE_ENABLED: bool = True
    RAG_EMBED_CACHE_TTL: int = 21600
    RAG_EMBED_CACHE_PREFIX: str = "embed:"
    RAG_EMBED_CACHE_DB: int = 0
    RAG_PDF_CACHE_ENABLED: bool = True
    RAG_PDF_CACHE_TTL: int = 2592000

    # ===== Ingestion =====
    DOCS_PATHS: List[str] = Field(default_factory=lambda: settings.DOCS_PATHS)
    CHUNK_SIZE: int = Field(default_factory=lambda: settings.CHUNK_SIZE)
    CHUNK_OVERLAP: int = Field(default_factory=lambda: settings.CHUNK_OVERLAP)
    INGEST_STREAMING: bool = Field(default_factory=lambda: settings.INGEST_STREAMING)
    DOCS_ENABLED_PATHS: tuple = Field(default_factory=lambda: settings.DOCS_ENABLED_PATHS)
    DUPLICATES_DOC_EXCEPTIONS: tuple = Field(default_factory=lambda: settings.DUPLICATES_DOC_EXCEPTIONS)
    DOCS_EXCLUDE_FILE: str = Field(default_factory=lambda: settings.DOCS_EXCLUDE_FILE)
    DOCS_EXCLUDE_DIRS: tuple = Field(default_factory=lambda: settings.DOCS_EXCLUDE_DIRS)
    DOCS_EXCLUDE_GLOBS: tuple = Field(default_factory=lambda: settings.DOCS_EXCLUDE_GLOBS)
    DOCS_FILE_EXTS: tuple = Field(default_factory=lambda: settings.DOCS_FILE_EXTS)

    # Auto-scan scheduler settings
    AUTO_SCAN_INTERVAL: int = Field(default_factory=lambda: settings.AUTO_SCAN_INTERVAL)
    AUTO_SCAN_INITIAL: bool = Field(default_factory=lambda: settings.AUTO_SCAN_INITIAL)
    AUTO_SCAN_INITIAL_WAIT: int = Field(default_factory=lambda: settings.AUTO_SCAN_INITIAL_WAIT)
    AUTO_SCAN_MAX_FILES: int = Field(default_factory=lambda: settings.AUTO_SCAN_MAX_FILES)

    # ===== Memory System =====
    MEMORY_TTL: int = 172800  # 48 hours
    MEMORY_WINDOW_SIZE: int = 10
    CHECKPOINT_NS: str = "memory"
    COMPRESSION_MODEL_ENDPOINT: str = "http://127.0.0.1:1234/v1/chat/completions"
    COMPRESSION_MODEL_NAME: str = "lfm2-2.6b"
    COMPRESSION_MAX_TOKENS: int = 500
    MAX_STATE_SIZE_KB: int = 100
    COMPRESSION_THRESHOLD: float = 0.8
    ARTIFACTS_BASE_DIR: str = "/tmp/artifacts"
    ARTIFACTS_TTL_HOURS: int = 48
    THREAD_SECRET: str = "change-this-secret-in-production-use-openssl-rand"

    # ===== Temporal RAG =====
    TEMPORAL_RAG_ENABLED: bool = True
    TEMPORAL_TENANT_TTL: int = 86400  # 24 hours
    TEMPORAL_FILE_MAX_SIZE_MB: int = 50
    TEMPORAL_PROMOTION_THRESHOLD: int = 3
    TEMPORAL_PARETO_MIN_QUERIES: int = 5
    TEMPORAL_PARETO_TOP_PERCENT: int = 20
    TEMPORAL_CLEANUP_INTERVAL: int = 3600

    # ===== Web Search (SearXNG) =====
    ENABLE_RAG_WEB_SEARCH: bool = False
    RAG_WEB_SEARCH_ENGINE: str = "searxng"
    SEARXNG_QUERY_URL: str = "http://127.0.0.1:19105/search?q=<query>"
    SEARXNG_URL: str = "http://127.0.0.1:19105"
    ENABLE_WEB_FALLBACK: bool = False
    SEARXNG_TIMEOUT: float = 10.0
    SEARXNG_MAX_RESULTS: int = 5
    SEARXNG_LANGUAGE: str = "es"

    # ===== Processing Tools =====
    ENABLE_OFFICE_CONVERSION: bool = True
    ENABLE_EXTRACTOR_EXTRACTION: bool = True
    ENABLE_OCR: bool = False
    ENABLE_GPU_ACCELERATION: bool = False
    TOOL_OFFICE_URL: str = "http://host.containers.internal:9106"
    TOOL_FILEEXTRACTOR_URL: str = "http://host.containers.internal:9101"
    TOOL_OCR_URL: str = "http://host.containers.internal:9106"
    TOOL_GPU_URL: str = "http://host.containers.internal:9104"
    TOOL_REQUEST_TIMEOUT: int = 120
    TOOL_OFFICE_TIMEOUT: int = 60
    TOOL_EXTRACTOR_TIMEOUT: int = 180
    TOOL_OCR_TIMEOUT: int = 120
    TOOL_GPU_TIMEOUT: int = 60
    TOOL_IDLE_TIMEOUT_OFFICE: int = 600
    TOOL_IDLE_TIMEOUT_EXTRACTOR: int = 600
    TOOL_IDLE_TIMEOUT_OCR: int = 600
    TOOL_IDLE_TIMEOUT_GPU: int = 600
    OCR_DEFAULT_LANGUAGE: str = "eng"
    OCR_DEFAULT_PSM: int = 3
    ARCHIVE_MAX_SIZE_MB: int = 500
    ARCHIVE_MAX_FILES: int = 10000
    OFFICE_DEFAULT_OUTPUT_FORMAT: str = "txt"
    PREPROCESSING_WORK_DIR: str = "/tmp/rag-preprocessing"
    EXTERNAL_VOLUMES: str = "[]"

    # ===== Apps =====
    INSTALLED_APPS: List[str] = Field(default_factory=lambda: settings.INSTALLED_APPS)
    AUTOLOAD_APP_ENTRYPOINTS: bool = Field(default_factory=lambda: settings.AUTOLOAD_APP_ENTRYPOINTS)

    # Internal defaults (excluded directories/files)
    DEFAULT_EXCLUDED_FILES: set = Field(default_factory=lambda: settings._DEFAULT_EXCLUDED_FILES)

    @field_validator('LMSTUDIO_EXTRA_HOSTS', mode='before')
    @classmethod
    def parse_extra_hosts(cls, v):
        """Parse comma-separated string or return list as-is."""
        if isinstance(v, str):
            return [h.strip() for h in v.split(",") if h.strip()]
        return v or []

    @field_validator('DOCS_ENABLED_PATHS', 'DUPLICATES_DOC_EXCEPTIONS', mode='before')
    @classmethod
    def parse_tuple_fields(cls, v):
        """Parse comma/newline-separated strings or JSON arrays into tuples."""
        if isinstance(v, str):
            parsed = parse_list_env(v)
            return tuple(parsed) if parsed else ()
        if isinstance(v, (list, tuple)):
            return tuple(str(item).strip() for item in v if str(item).strip())
        return v or ()

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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customize settings sources to load from: init -> env -> .env -> JSON -> defaults.

        This allows data/settings.json to override .env values, enabling persistent
        user configuration that survives restarts.
        """
        # Create a custom source for JSON file
        class JsonSettingsSource(PydanticBaseSettingsSource):
            def get_field_value(self, field, field_name: str) -> tuple[Any, str, bool]:
                # Load JSON on first access
                if not hasattr(self, '_json_data'):
                    json_path = Path("data/settings.json")
                    if not json_path.is_absolute():
                        base_dir = Path(__file__).resolve().parent.parent.parent
                        json_path = base_dir / json_path
                    self._json_data = _load_json_settings(json_path)

                # Return value if present in JSON
                if field_name in self._json_data:
                    return self._json_data[field_name], field_name, False
                return None, field_name, False

            def __call__(self) -> Dict[str, Any]:
                if not hasattr(self, '_json_data'):
                    json_path = Path("data/settings.json")
                    if not json_path.is_absolute():
                        base_dir = Path(__file__).resolve().parent.parent.parent
                        json_path = base_dir / json_path
                    self._json_data = _load_json_settings(json_path)
                return self._json_data

        # Priority: init > env > dotenv > JSON > file_secret > defaults
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            JsonSettingsSource(settings_cls),
            file_secret_settings,
        )

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
        """Build enabled paths from settings only."""
        entries = []

        # From setting
        entries.extend(value_as_list(self.DOCS_ENABLED_PATHS))

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
