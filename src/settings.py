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
)
