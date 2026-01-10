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
    VECTOR_BACKEND: str = Field(default_factory=lambda: settings.VECTOR_BACKEND)
    WEAVIATE_URL: str = Field(default_factory=lambda: settings.WEAVIATE_URL)
    WEAVIATE_API_KEY: str = Field(default_factory=lambda: settings.WEAVIATE_API_KEY)
    WEAVIATE_CLASS: str = Field(default_factory=lambda: settings.WEAVIATE_CLASS)
    WEAVIATE_TIMEOUT: int = Field(default_factory=lambda: settings.WEAVIATE_TIMEOUT)
    WEAVIATE_GRPC_PORT: int = Field(default_factory=lambda: settings.WEAVIATE_GRPC_PORT)
    WEAVIATE_CONNECT_RETRIES: int = Field(default_factory=lambda: settings.WEAVIATE_CONNECT_RETRIES)
    WEAVIATE_CONNECT_BACKOFF: float = Field(default_factory=lambda: settings.WEAVIATE_CONNECT_BACKOFF)
    WEAVIATE_MULTI_TENANCY: bool = Field(default_factory=lambda: settings.WEAVIATE_MULTI_TENANCY)
    WEAVIATE_DEFAULT_TENANT: str = Field(default_factory=lambda: settings.WEAVIATE_DEFAULT_TENANT)
    WEAVIATE_SKIP_INIT_CHECKS: bool = Field(default_factory=lambda: settings.WEAVIATE_SKIP_INIT_CHECKS)

    # Vector stores configuration (Django-style)
    VECTOR_STORES: Dict[str, Dict[str, Any]] = Field(default_factory=lambda: settings.VECTOR_STORES)

    # ===== Graph Store (Neo4j) =====
    NEO4J_URI: str = Field(default_factory=lambda: settings.NEO4J_URI)
    NEO4J_USER: str = Field(default_factory=lambda: settings.NEO4J_USER)
    NEO4J_PASSWORD: str = Field(default_factory=lambda: settings.NEO4J_PASSWORD)

    # ===== Cache (Redis) =====
    REDIS_HOST: str = Field(default_factory=lambda: settings.REDIS_HOST)
    REDIS_PORT: int = Field(default_factory=lambda: settings.REDIS_PORT)
    REDIS_DB: int = Field(default_factory=lambda: settings.REDIS_DB)
    REDIS_PASSWORD: str = Field(default_factory=lambda: settings.REDIS_PASSWORD)
    CACHE_TTL: int = Field(default_factory=lambda: settings.CACHE_TTL)

    # ===== API Configuration =====
    API_MODE: str = Field(default_factory=lambda: settings.API_MODE)
    API_PORT: int = Field(default_factory=lambda: settings.API_PORT)
    SOCKET_PORT: int = Field(default_factory=lambda: settings.SOCKET_PORT)
    OPENAI_API_BASE: str = Field(default_factory=lambda: settings.OPENAI_API_BASE)
    OPENAI_API_KEY: str = Field(default_factory=lambda: settings.OPENAI_API_KEY)

    # ===== Provider (LM Studio) =====
    PROVIDER: str = Field(default_factory=lambda: settings.PROVIDER)
    LMSTUDIO_HOST: str = Field(default_factory=lambda: settings.LMSTUDIO_HOST)
    LMSTUDIO_PORT: int = Field(default_factory=lambda: settings.LMSTUDIO_PORT)
    LMSTUDIO_EXTRA_HOSTS: List[str] = Field(default_factory=lambda: settings.LMSTUDIO_EXTRA_HOSTS)
    LMSTUDIO_CHAT_MODEL: str = Field(default_factory=lambda: settings.LMSTUDIO_CHAT_MODEL)
    LMSTUDIO_REQUIRE_SERVER: bool = Field(default_factory=lambda: settings.LMSTUDIO_REQUIRE_SERVER)
    LMSTUDIO_KEEPALIVE_CHAT: int = Field(default_factory=lambda: settings.LMSTUDIO_KEEPALIVE_CHAT)
    LMSTUDIO_KEEPALIVE_EMBED: int = Field(default_factory=lambda: settings.LMSTUDIO_KEEPALIVE_EMBED)
    LMSTUDIO_KEEPALIVE_RERANK: int = Field(default_factory=lambda: settings.LMSTUDIO_KEEPALIVE_RERANK)
    LMSTUDIO_API_ROOTS: List[str] = Field(default_factory=lambda: settings.LMSTUDIO_API_ROOTS)

    # ===== Embeddings =====
    EMBEDDING_MODEL: str = Field(default_factory=lambda: settings.EMBEDDING_MODEL)
    EMBEDDING_DIM: int = Field(default_factory=lambda: settings.EMBEDDING_DIM)
    EMBEDDING_MAX_TOKENS: int = Field(default_factory=lambda: settings.EMBEDDING_MAX_TOKENS)

    # Dual Embeddings System
    ENABLE_DUAL_EMBEDDINGS: bool = Field(default_factory=lambda: settings.ENABLE_DUAL_EMBEDDINGS)
    SMALL_EMBEDDING_MODEL: str = Field(default_factory=lambda: settings.SMALL_EMBEDDING_MODEL)
    LARGE_EMBEDDING_MODEL: str = Field(default_factory=lambda: settings.LARGE_EMBEDDING_MODEL)
    SMALL_EMBEDDING_DIM: int = Field(default_factory=lambda: settings.SMALL_EMBEDDING_DIM)
    LARGE_EMBEDDING_DIM: int = Field(default_factory=lambda: settings.LARGE_EMBEDDING_DIM)
    DUAL_EMBEDDINGS_SMALL_COLLECTION: str = Field(default_factory=lambda: settings.DUAL_EMBEDDINGS_SMALL_COLLECTION)
    DUAL_EMBEDDINGS_LARGE_COLLECTION: str = Field(default_factory=lambda: settings.DUAL_EMBEDDINGS_LARGE_COLLECTION)

    # ===== RAG Configuration =====
    ENABLE_RAG_GATING: bool = Field(default_factory=lambda: settings.ENABLE_RAG_GATING)
    MIN_RELEVANCE_SCORE: float = Field(default_factory=lambda: settings.MIN_RELEVANCE_SCORE)
    ENABLE_RERANKER: bool = Field(default_factory=lambda: settings.ENABLE_RERANKER)

    # RAG Generation Parameters
    RAG_DEFAULT_TEMPERATURE: float = Field(default_factory=lambda: settings.RAG_DEFAULT_TEMPERATURE)
    RAG_DEFAULT_MAX_TOKENS: int = Field(default_factory=lambda: settings.RAG_DEFAULT_MAX_TOKENS)
    RAG_DEFAULT_TOP_P: float = Field(default_factory=lambda: settings.RAG_DEFAULT_TOP_P)
    RAG_DEFAULT_FREQUENCY_PENALTY: float = Field(default_factory=lambda: settings.RAG_DEFAULT_FREQUENCY_PENALTY)
    RAG_DEFAULT_PRESENCE_PENALTY: float = Field(default_factory=lambda: settings.RAG_DEFAULT_PRESENCE_PENALTY)

    # RAG Retrieval Parameters
    RAG_DEFAULT_TOP_K: int = Field(default_factory=lambda: settings.RAG_DEFAULT_TOP_K)

    # RAG Profile System
    RAG_PROFILE: str = Field(default_factory=lambda: settings.RAG_PROFILE)
    RAG_PERFORMANCE_PROFILE: str = Field(default_factory=lambda: settings.RAG_PERFORMANCE_PROFILE)
    RESOURCE_MODE: str = Field(default_factory=lambda: settings.RESOURCE_MODE)

    # RAG Performance Optimizations
    RAG_EMBED_BATCH_SIZE: int = Field(default_factory=lambda: settings.RAG_EMBED_BATCH_SIZE)
    RAG_EMBED_LOG_EVERY_N_CHUNKS: int = Field(default_factory=lambda: settings.RAG_EMBED_LOG_EVERY_N_CHUNKS)
    RAG_PARALLEL_WORKERS: int = Field(default_factory=lambda: settings.RAG_PARALLEL_WORKERS)
    RAG_PIPELINE_WORKERS: int = Field(default_factory=lambda: settings.RAG_PIPELINE_WORKERS)

    # RAG Document Splitting Optimizations
    RAG_SPLIT_BATCH_SIZE: int = Field(default_factory=lambda: settings.RAG_SPLIT_BATCH_SIZE)
    RAG_SPLIT_LOG_EVERY_SECONDS: int = Field(default_factory=lambda: settings.RAG_SPLIT_LOG_EVERY_SECONDS)
    RAG_MAX_DOCS_PER_FILE: int = Field(default_factory=lambda: settings.RAG_MAX_DOCS_PER_FILE)

    # RAG Caching
    RAG_EMBED_CACHE_ENABLED: bool = Field(default_factory=lambda: settings.RAG_EMBED_CACHE_ENABLED)
    RAG_EMBED_CACHE_TTL: int = Field(default_factory=lambda: settings.RAG_EMBED_CACHE_TTL)
    RAG_EMBED_CACHE_PREFIX: str = Field(default_factory=lambda: settings.RAG_EMBED_CACHE_PREFIX)
    RAG_EMBED_CACHE_DB: int = Field(default_factory=lambda: settings.RAG_EMBED_CACHE_DB)
    RAG_PDF_CACHE_ENABLED: bool = Field(default_factory=lambda: settings.RAG_PDF_CACHE_ENABLED)
    RAG_PDF_CACHE_TTL: int = Field(default_factory=lambda: settings.RAG_PDF_CACHE_TTL)

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
    MEMORY_TTL: int = Field(default_factory=lambda: settings.MEMORY_TTL)
    MEMORY_WINDOW_SIZE: int = Field(default_factory=lambda: settings.MEMORY_WINDOW_SIZE)
    CHECKPOINT_NS: str = Field(default_factory=lambda: settings.CHECKPOINT_NS)
    COMPRESSION_MODEL_ENDPOINT: str = Field(default_factory=lambda: settings.COMPRESSION_MODEL_ENDPOINT)
    COMPRESSION_MODEL_NAME: str = Field(default_factory=lambda: settings.COMPRESSION_MODEL_NAME)
    COMPRESSION_MAX_TOKENS: int = Field(default_factory=lambda: settings.COMPRESSION_MAX_TOKENS)
    MAX_STATE_SIZE_KB: int = Field(default_factory=lambda: settings.MAX_STATE_SIZE_KB)
    COMPRESSION_THRESHOLD: float = Field(default_factory=lambda: settings.COMPRESSION_THRESHOLD)
    ARTIFACTS_BASE_DIR: str = Field(default_factory=lambda: settings.ARTIFACTS_BASE_DIR)
    ARTIFACTS_TTL_HOURS: int = Field(default_factory=lambda: settings.ARTIFACTS_TTL_HOURS)
    THREAD_SECRET: str = Field(default_factory=lambda: settings.THREAD_SECRET)

    # ===== ChatMemory Settings =====
    CHATMEMORY_TTL_DAYS: int = Field(default_factory=lambda: settings.CHATMEMORY_TTL_DAYS)
    CHATMEMORY_VECTORIZER: str = Field(default_factory=lambda: settings.CHATMEMORY_VECTORIZER)
    SNAPSHOT_TTL_DAYS: int = Field(default_factory=lambda: settings.SNAPSHOT_TTL_DAYS)
    SNAPSHOT_ENABLED: bool = Field(default_factory=lambda: settings.SNAPSHOT_ENABLED)
    SNAPSHOT_INTERVAL_HOURS: int = Field(default_factory=lambda: settings.SNAPSHOT_INTERVAL_HOURS)
    CLEANUP_ENABLED: bool = Field(default_factory=lambda: settings.CLEANUP_ENABLED)
    CLEANUP_INTERVAL_HOURS: int = Field(default_factory=lambda: settings.CLEANUP_INTERVAL_HOURS)
    TEMPORAL_CLEANUP_ENABLED: bool = Field(default_factory=lambda: settings.TEMPORAL_CLEANUP_ENABLED)
    TEMPORAL_CLEANUP_INTERVAL_HOURS: int = Field(default_factory=lambda: settings.TEMPORAL_CLEANUP_INTERVAL_HOURS)

    # ===== Temporal RAG =====
    TEMPORAL_RAG_ENABLED: bool = Field(default_factory=lambda: settings.TEMPORAL_RAG_ENABLED)
    TEMPORAL_TENANT_TTL: int = Field(default_factory=lambda: settings.TEMPORAL_TENANT_TTL)
    TEMPORAL_FILE_MAX_SIZE_MB: int = Field(default_factory=lambda: settings.TEMPORAL_FILE_MAX_SIZE_MB)
    TEMPORAL_PROMOTION_THRESHOLD: int = Field(default_factory=lambda: settings.TEMPORAL_PROMOTION_THRESHOLD)
    TEMPORAL_PARETO_MIN_QUERIES: int = Field(default_factory=lambda: settings.TEMPORAL_PARETO_MIN_QUERIES)
    TEMPORAL_PARETO_TOP_PERCENT: int = Field(default_factory=lambda: settings.TEMPORAL_PARETO_TOP_PERCENT)
    TEMPORAL_CLEANUP_INTERVAL: int = Field(default_factory=lambda: settings.TEMPORAL_CLEANUP_INTERVAL)

    # ===== Web Search (SearXNG) =====
    ENABLE_RAG_WEB_SEARCH: bool = Field(default_factory=lambda: settings.ENABLE_RAG_WEB_SEARCH)
    RAG_WEB_SEARCH_ENGINE: str = Field(default_factory=lambda: settings.RAG_WEB_SEARCH_ENGINE)
    SEARXNG_QUERY_URL: str = Field(default_factory=lambda: settings.SEARXNG_QUERY_URL)
    SEARXNG_URL: str = Field(default_factory=lambda: settings.SEARXNG_URL)
    ENABLE_WEB_FALLBACK: bool = Field(default_factory=lambda: settings.ENABLE_WEB_FALLBACK)
    SEARXNG_TIMEOUT: float = Field(default_factory=lambda: settings.SEARXNG_TIMEOUT)
    SEARXNG_MAX_RESULTS: int = Field(default_factory=lambda: settings.SEARXNG_MAX_RESULTS)
    SEARXNG_LANGUAGE: str = Field(default_factory=lambda: settings.SEARXNG_LANGUAGE)

    # ===== Processing Tools =====
    ENABLE_OFFICE_CONVERSION: bool = Field(default_factory=lambda: settings.ENABLE_OFFICE_CONVERSION)
    ENABLE_EXTRACTOR_EXTRACTION: bool = Field(default_factory=lambda: settings.ENABLE_EXTRACTOR_EXTRACTION)
    ENABLE_OCR: bool = Field(default_factory=lambda: settings.ENABLE_OCR)
    ENABLE_GPU_ACCELERATION: bool = Field(default_factory=lambda: settings.ENABLE_GPU_ACCELERATION)
    TOOL_OFFICE_URL: str = Field(default_factory=lambda: settings.TOOL_OFFICE_URL)
    TOOL_FILEEXTRACTOR_URL: str = Field(default_factory=lambda: settings.TOOL_FILEEXTRACTOR_URL)
    TOOL_OCR_URL: str = Field(default_factory=lambda: settings.TOOL_OCR_URL)
    TOOL_GPU_URL: str = Field(default_factory=lambda: settings.TOOL_GPU_URL)
    TOOL_REQUEST_TIMEOUT: int = Field(default_factory=lambda: settings.TOOL_REQUEST_TIMEOUT)
    TOOL_OFFICE_TIMEOUT: int = Field(default_factory=lambda: settings.TOOL_OFFICE_TIMEOUT)
    TOOL_EXTRACTOR_TIMEOUT: int = Field(default_factory=lambda: settings.TOOL_EXTRACTOR_TIMEOUT)
    TOOL_OCR_TIMEOUT: int = Field(default_factory=lambda: settings.TOOL_OCR_TIMEOUT)
    TOOL_GPU_TIMEOUT: int = Field(default_factory=lambda: settings.TOOL_GPU_TIMEOUT)
    TOOL_IDLE_TIMEOUT_OFFICE: int = Field(default_factory=lambda: settings.TOOL_IDLE_TIMEOUT_OFFICE)
    TOOL_IDLE_TIMEOUT_EXTRACTOR: int = Field(default_factory=lambda: settings.TOOL_IDLE_TIMEOUT_EXTRACTOR)
    TOOL_IDLE_TIMEOUT_OCR: int = Field(default_factory=lambda: settings.TOOL_IDLE_TIMEOUT_OCR)
    TOOL_IDLE_TIMEOUT_GPU: int = Field(default_factory=lambda: settings.TOOL_IDLE_TIMEOUT_GPU)
    OCR_DEFAULT_LANGUAGE: str = Field(default_factory=lambda: settings.OCR_DEFAULT_LANGUAGE)
    OCR_DEFAULT_PSM: int = Field(default_factory=lambda: settings.OCR_DEFAULT_PSM)
    ARCHIVE_MAX_SIZE_MB: int = Field(default_factory=lambda: settings.ARCHIVE_MAX_SIZE_MB)
    ARCHIVE_MAX_FILES: int = Field(default_factory=lambda: settings.ARCHIVE_MAX_FILES)
    OFFICE_DEFAULT_OUTPUT_FORMAT: str = Field(default_factory=lambda: settings.OFFICE_DEFAULT_OUTPUT_FORMAT)
    PREPROCESSING_WORK_DIR: str = Field(default_factory=lambda: settings.PREPROCESSING_WORK_DIR)
    EXTERNAL_VOLUMES: str = Field(default_factory=lambda: settings.EXTERNAL_VOLUMES)

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
