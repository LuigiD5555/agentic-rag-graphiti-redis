"""
Declarative defaults for app settings.

This module keeps settings as plain module constants.
"""

# Path for user-editable settings persisted by the app (JSON).
USER_SETTINGS_FILE = "data/settings.json"

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
CACHES = {
    "default": {
        "BACKEND": "redis",
        "LOCATION": "redis://redis:6379/0",
        "TIMEOUT": None,
        "KEY_PREFIX": "",
        "VERSION": 1,
        "OPTIONS": {},
    }
}

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
DOCS_PATHS = [
    "/mnt/Documents/Documents",
    "/mnt/resources/Libros/Aprendizaje",
]
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
DOCS_EXCLUDE_FILE = ""
DOCS_EXCLUDE_DIRS = ()
DOCS_EXCLUDE_GLOBS = ()
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

# Default excluded basenames for discovery (fast-prune + common junk folders).
_DEFAULT_EXCLUDED_FILES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
}

# Keys that can be persisted/overridden via the user settings JSON file.
_USER_SETTING_FIELDS = (
    "DOCS_PATHS",
    "DOCS_EXCLUDE_FILE",
    "DOCS_EXCLUDE_DIRS",
    "DOCS_EXCLUDE_GLOBS",
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
