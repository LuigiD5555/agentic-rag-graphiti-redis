from pathlib import Path

# Base path for resolving project-relative files (.env, data/settings.json, etc.).
BASE_DIR = Path(__file__).resolve().parent.parent

# Paths for environment file and user-editable settings (JSON).
ENV_FILE = BASE_DIR / ".env"
USER_SETTINGS_FILE = BASE_DIR / "data/settings.json"

# Vector store registry (aliases -> connection/config dict).
VECTOR_STORES = {
    "default": {
        "ENGINE": "weaviate",
        "NAME": "RAGDocument",
        "USER": "",
        "PASSWORD": "",
        "HOST": "localhost",
        "PORT": 8080,
        "SCHEME": "http",
        "PATH": "",
        "API_KEY": "",
        "AUTOCOMMIT": True,
        "ATOMIC_REQUESTS": False,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "TIME_ZONE": None,
        "OPTIONS": {
            "GRPC_PORT": 50051,
            "CONNECT_RETRIES": 5,
            "CONNECT_BACKOFF": 2.0,
            "MULTI_TENANCY": True,
            "DEFAULT_TENANT": "tenant-default",
        },
        "TEST": {},
    }
}

# Graph store registry (aliases -> connection/config dict).
GRAPH_STORES = {
    "default": {
        "ENGINE": "neo4j",
        "NAME": "neo4j",
        "USER": "neo4j",
        "PASSWORD": "",
        "HOST": "neo4j",
        "PORT": 7687,
        "SCHEME": "bolt",
        "AUTOCOMMIT": True,
        "ATOMIC_REQUESTS": False,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "TIME_ZONE": None,
        "OPTIONS": {},
        "TEST": {},
    }
}

# Cache backend registry (aliases -> cache backend config dict).
# Note: LOCATION is intentionally left empty here because it will be resolved
# from environment variables (REDIS_HOST/REDIS_PORT or REDIS_URL) at runtime.
# See src/storage/cache/__init__.py:_resolve_redis_endpoint for the resolution logic.
CACHES = {
    "default": {
        "BACKEND": "redis",
        "LOCATION": "",
        "TIMEOUT": None,
        "KEY_PREFIX": "",
        "VERSION": 1,
        "OPTIONS": {},
    }
}

# Redis configuration (centralized like Django settings)
REDIS_URL: str = ""  # If set, overrides REDIS_HOST/PORT
REDIS_HOST: str = "localhost"
REDIS_PORT: int = 6379
REDIS_DB: int = 0
REDIS_PASSWORD: str = ""

# Provider adapters registry (aliases -> provider config dict).
PROVIDERS = {
    "default": {
        # Adapter name registered in the provider registry (not an import path).
        "ENGINE": "lmstudio",
        "HOST": "host.containers.internal",
        "PORT": 1234,
        "EXTRA_HOSTS": [],
        "CHAT_MODEL": "",
        "REQUIRE_SERVER": False,
        "OPTIONS": {},
    },
    "anythingllm": {
        "ENGINE": "anythingllm",
        "URL": "",
        "API_KEY": "",
        "OPTIONS": {},
    },
    "ollama": {
        "ENGINE": "ollama",
        "HOST": "localhost",
        "PORT": 11434,
        "OPTIONS": {},
    },
    "huggingface": {
        "ENGINE": "huggingface",
        "API_KEY": "",
        "MODEL": "",
        "OPTIONS": {},
    },
    "litellm": {
        "ENGINE": "litellm",
        "TARGET_PROVIDER": "lmstudio",
        "OPTIONS": {},
    },
}

# App registry (providers are registered by these AppConfig entries).
INSTALLED_APPS = [
    "src.providers.lmstudio.apps.LMStudioProviderAppConfig",
    "src.providers.openai.apps.OpenAIProviderAppConfig",
    "src.providers.huggingface.apps.HuggingFaceProviderAppConfig",
    "src.providers.anythingllm.apps.AnythingLLMProviderAppConfig",
    "src.providers.litellm_gateway.apps.LiteLLMGatewayAppConfig",
]
AUTOLOAD_APP_ENTRYPOINTS = False
APP_ENTRYPOINT_GROUP = "rag_agentic_graphiti.apps"

# Embeddings settings (used by ingestion/pipeline token limits and embedding size).
EMBEDDING_DIM = 768
EMBEDDING_MAX_TOKENS = 512

# ChatMemory settings (conversation snapshot persistence).
CHATMEMORY_TTL_DAYS = 30  # Default TTL for conversation snapshots
CHATMEMORY_VECTORIZER = "none"  # External embeddings (not Weaviate's built-in vectorizer)
SNAPSHOT_TTL_DAYS = 30  # Alias for backward compatibility
SNAPSHOT_ENABLED = False  # Enable automatic snapshot scheduler
SNAPSHOT_INTERVAL_HOURS = 24  # Snapshot creation interval
CLEANUP_ENABLED = False  # Enable automatic cleanup scheduler
CLEANUP_INTERVAL_HOURS = 24  # Cleanup interval for expired snapshots
TEMPORAL_CLEANUP_ENABLED = False  # Enable temporal document cleanup
TEMPORAL_CLEANUP_INTERVAL_HOURS = 24  # Temporal cleanup interval

# LiteLLM gateway setting (used by the LiteLLM adapter).
LITELLM_TARGET_PROVIDER = "lmstudio"

# Ingestion settings (discovery + splitting).
# DOCS_PATHS define the BASE paths to scan.
# To avoid scanning all of /mnt/Documents/Documents (which includes code),
# we only scan the books folder:
DOCS_PATHS = [
    "/mnt/resources/Libros/Aprendizaje",  # Books only, no source code
    # "/mnt/Documents/Documents",  # Commented out: contains too much code
]
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
INGEST_STREAMING = True
DOCS_ENABLED_PATHS = ()
DUPLICATES_DOC_EXCEPTIONS = ("__init__.py",)  # Paths that should NOT be deduplicated
DOCS_EXCLUDE_FILE = ""
DOCS_EXCLUDE_DIRS = ()
# Exclude specific subdirectories that contain code/projects (not knowledge)
DOCS_EXCLUDE_GLOBS = (
    # Exclude all programming projects and code
    "*/Programacion/Aprendiendo_Programacion/*",
    "*/Programacion/Proyectos_Programacion/*",
    "*/Programacion/Deprecated*",

    # Exclude specific heavy folders
    "*/Certificates/*",
    "*/Odoo/*",
    "*/fact_checker*",

    # Keep only /mnt/resources/Libros/Aprendizaje (books)
    # Everything else in /mnt/Documents/Documents will be excluded
)
DOCS_FILE_EXTS = (
    ".pdf",
    ".docx",
    ".doc",
    ".docm",
    ".rtf",
    ".txt",
    ".md",
    ".csv",
    ".xlsx",
    ".xls",
    ".xlsm",
    ".xlsb",
    ".xlt",
    ".ppt",
    ".pptx",
    ".pptm",
    ".pps",
    ".ppsx",
    ".odt",
    ".ods",
    ".odp",
    ".eml",
    ".msg",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rb",
    ".cs",
    ".php",
    ".c",
    ".cpp",
)

# Default cache TTL for application-level caching (seconds).
CACHE_TTL = 3600

# Auto-scan scheduler settings (for periodic ingestion).
AUTO_SCAN_INTERVAL = 300  # Seconds between scans (default: 5 minutes)
AUTO_SCAN_INITIAL = True  # Whether to run initial scan on startup
AUTO_SCAN_INITIAL_WAIT = 30  # Seconds to wait before initial scan
AUTO_SCAN_MAX_FILES = 0  # Max files per scan (0 = unlimited)

# ===== Neo4j Graph Store =====
NEO4J_URI = "bolt://neo4j:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = ""

# ===== API Configuration =====
API_MODE = "openai"  # "openai" or "ollama"
API_PORT = 8001  # Port for API server
SOCKET_PORT = 5555  # Port for RAG socket server
OPENAI_API_BASE = "http://127.0.0.1:1234/v1"
OPENAI_API_KEY = "lm-studio"

# ===== Provider (LM Studio) =====
PROVIDER = "lmstudio"
LMSTUDIO_HOST = "host.containers.internal"
LMSTUDIO_PORT = 1234
LMSTUDIO_EXTRA_HOSTS = []
LMSTUDIO_CHAT_MODEL = ""
LMSTUDIO_EMBED_MODEL = ""
LMSTUDIO_REQUIRE_SERVER = False
LMSTUDIO_KEEPALIVE_CHAT = 60
LMSTUDIO_KEEPALIVE_EMBED = 30
LMSTUDIO_KEEPALIVE_RERANK = 30
LMSTUDIO_API_ROOTS = []

# ===== Embeddings =====
EMBEDDING_MODEL = ""  # Explicit model name (required)

# Dual Embeddings System
ENABLE_DUAL_EMBEDDINGS = False
SMALL_EMBEDDING_MODEL = ""
LARGE_EMBEDDING_MODEL = ""
SMALL_EMBEDDING_DIM = 384
LARGE_EMBEDDING_DIM = 768
DUAL_EMBEDDINGS_SMALL_COLLECTION = "RAGDocument384"
DUAL_EMBEDDINGS_LARGE_COLLECTION = "RAGDocument768"

# ===== RAG Configuration =====
ENABLE_RAG_GATING = True
MIN_RELEVANCE_SCORE = 0.5
ENABLE_RERANKER = False

# RAG Profile System
RAG_PROFILE = "auto"
RAG_PERFORMANCE_PROFILE = "performance"
RESOURCE_MODE = "performance"

# RAG Performance Optimizations
RAG_EMBED_BATCH_SIZE = 16
RAG_EMBED_LOG_EVERY_N_CHUNKS = 20
RAG_PARALLEL_WORKERS = 3
RAG_PIPELINE_WORKERS = 3

# RAG Document Splitting Optimizations
RAG_SPLIT_BATCH_SIZE = 128  # Batch size for document splitting
RAG_SPLIT_LOG_EVERY_SECONDS = 15  # Log splitting progress every N seconds
RAG_MAX_DOCS_PER_FILE = 200000  # Maximum documents per file (prevents pathological loaders)

# RAG Caching
RAG_EMBED_CACHE_ENABLED = True
RAG_EMBED_CACHE_TTL = 21600
RAG_EMBED_CACHE_PREFIX = "embed:"
RAG_EMBED_CACHE_DB = 0
RAG_PDF_CACHE_ENABLED = True
RAG_PDF_CACHE_TTL = 2592000

# ===== Memory System =====
MEMORY_TTL = 172800  # 48 hours
MEMORY_WINDOW_SIZE = 10
CHECKPOINT_NS = "memory"
COMPRESSION_MODEL_ENDPOINT = "http://127.0.0.1:1234/v1/chat/completions"
COMPRESSION_MODEL_NAME = "lfm2-2.6b"
COMPRESSION_MAX_TOKENS = 500
MAX_STATE_SIZE_KB = 100
COMPRESSION_THRESHOLD = 0.8
ARTIFACTS_BASE_DIR = "/tmp/artifacts"
ARTIFACTS_TTL_HOURS = 48
THREAD_SECRET = "change-this-secret-in-production-use-openssl-rand"

# ===== Temporal RAG =====
TEMPORAL_RAG_ENABLED = True
TEMPORAL_TENANT_TTL = 86400  # 24 hours
TEMPORAL_FILE_MAX_SIZE_MB = 50
TEMPORAL_PROMOTION_THRESHOLD = 3
TEMPORAL_PARETO_MIN_QUERIES = 5
TEMPORAL_PARETO_TOP_PERCENT = 20
TEMPORAL_CLEANUP_INTERVAL = 3600

# ===== Web Search (SearXNG) =====
ENABLE_RAG_WEB_SEARCH = False
RAG_WEB_SEARCH_ENGINE = "searxng"
SEARXNG_QUERY_URL = "http://127.0.0.1:19105/search?q=<query>"
SEARXNG_URL = "http://127.0.0.1:19105"
ENABLE_WEB_FALLBACK = False
SEARXNG_TIMEOUT = 10.0
SEARXNG_MAX_RESULTS = 5
SEARXNG_LANGUAGE = "es"

# ===== Processing Tools =====
ENABLE_OFFICE_CONVERSION = True
ENABLE_EXTRACTOR_EXTRACTION = True
ENABLE_OCR = False
ENABLE_GPU_ACCELERATION = False
TOOL_OFFICE_URL = "http://host.containers.internal:9106"
TOOL_FILEEXTRACTOR_URL = "http://host.containers.internal:9101"
TOOL_OCR_URL = "http://host.containers.internal:9106"
TOOL_GPU_URL = "http://host.containers.internal:9104"
TOOL_REQUEST_TIMEOUT = 120
TOOL_OFFICE_TIMEOUT = 60
TOOL_EXTRACTOR_TIMEOUT = 180
TOOL_OCR_TIMEOUT = 120
TOOL_GPU_TIMEOUT = 60
TOOL_IDLE_TIMEOUT_OFFICE = 600
TOOL_IDLE_TIMEOUT_EXTRACTOR = 600
TOOL_IDLE_TIMEOUT_OCR = 600
TOOL_IDLE_TIMEOUT_GPU = 600
TOOL_CONNECT_RETRIES = 10
TOOL_CONNECT_RETRY_DELAY = 0.5
OCR_DEFAULT_LANGUAGE = "eng"
OCR_DEFAULT_PSM = 3
ARCHIVE_MAX_SIZE_MB = 500
ARCHIVE_MAX_FILES = 10000
OFFICE_DEFAULT_OUTPUT_FORMAT = "txt"
PREPROCESSING_WORK_DIR = "/tmp/rag-preprocessing"
EXTERNAL_VOLUMES = "[]"

# ===== Weaviate Vector Store =====
VECTOR_BACKEND = "weaviate"
WEAVIATE_URL = "http://localhost:8080"
WEAVIATE_API_KEY = ""
WEAVIATE_CLASS = "RAGDocument"
WEAVIATE_TIMEOUT = 30
WEAVIATE_GRPC_PORT = 50051
WEAVIATE_CONNECT_RETRIES = 5
WEAVIATE_CONNECT_BACKOFF = 2.0
WEAVIATE_MULTI_TENANCY = True
WEAVIATE_DEFAULT_TENANT = "tenant-default"
WEAVIATE_SKIP_INIT_CHECKS = False

# If provided (via user settings JSON), this list REPLACES _DEFAULT_EXCLUDED_FILES.
# GUI can manage this list to fully control fast-prune directory basenames.
DOCS_EXCLUDE_DIRS_BUILTINS_OVERRIDE = None

# Default excluded basenames for discovery (fast-prune + common junk folders).
_DEFAULT_EXCLUDED_FILES = {
    # VCS / editor / tooling
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".vs",

    # Python / type-checker / test caches
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".hypothesis",
    ".ipynb_checkpoints",

    # Virtual environments / package dirs
    ".venv",
    "venv",
    "env",
    "__pypackages__",
    "site-packages",

    # Node / web build artifacts
    "node_modules",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".parcel-cache",

    # Generic build outputs
    "build",
    "dist",
    "target",
    "out",
    "coverage",

    # Misc common caches
    ".cache",
    ".gradle",
    ".terraform",

    # Metadata/bundles (may be files or directories)
    ".DS_Store",
    "*.egg-info",
    ".eggs",
    ".coverage",

    # Compressed archives
    "__MACOSX",
    "*.zip",
    "*.tar",
    "*.tar.gz",
    "*.rar",
    "*.7z",
    "*.gz",
    "*.tar.xz"
}

# Keys that can be persisted/overridden via the user settings JSON file.
_USER_SETTING_FIELDS = (
    "DOCS_PATHS",
    "DOCS_ENABLED_PATHS",
    "DUPLICATES_DOC_EXCEPTIONS",
    "DOCS_EXCLUDE_FILE",
    "DOCS_EXCLUDE_DIRS",
    "DOCS_EXCLUDE_GLOBS",
    "DOCS_EXCLUDE_DIRS_BUILTINS_OVERRIDE",
    "DOCS_FILE_EXTS",
    "VECTOR_STORES",
    "CACHES",
    "GRAPH_STORES",
    "PROVIDERS",
    "INSTALLED_APPS",
    "AUTOLOAD_APP_ENTRYPOINTS",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "EMBEDDING_MAX_TOKENS",
    "CHATMEMORY_TTL_DAYS",
    "CHATMEMORY_VECTORIZER",
    "SNAPSHOT_TTL_DAYS",
    "SNAPSHOT_ENABLED",
    "SNAPSHOT_INTERVAL_HOURS",
    "CLEANUP_ENABLED",
    "CLEANUP_INTERVAL_HOURS",
    "TEMPORAL_CLEANUP_ENABLED",
    "TEMPORAL_CLEANUP_INTERVAL_HOURS",
)
