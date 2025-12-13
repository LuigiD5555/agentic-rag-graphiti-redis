import json
import os
import re
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """
    Centralized runtime configuration using Pydantic BaseSettings.

    Notes:
    - Loads environment variables and optional .env file.
    - Maintains the same env var names to avoid breaking existing setups/tests.
    """

    # Pydantic settings
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    USER_SETTINGS_FILE: str = "data/settings.json"

    # ----- Vector DB backend selection -----
    VECTOR_BACKEND: str = "weaviate"

    # ----- Weaviate configuration -----
    WEAVIATE_URL: str = "http://localhost:8080"
    WEAVIATE_API_KEY: str = ""
    WEAVIATE_CLASS: str = "RAGDocument"
    WEAVIATE_MULTI_TENANCY: bool = True
    WEAVIATE_DEFAULT_TENANT: str = "tenant-default"
    WEAVIATE_TIMEOUT: int = 30
    WEAVIATE_GRPC_PORT: int = 50051
    WEAVIATE_CONNECT_RETRIES: int = 5
    WEAVIATE_CONNECT_BACKOFF: float = 2.0

    # ----- Embeddings -----
    EMBEDDING_DIM: int = 768
    EMBEDDING_MAX_TOKENS: int = 512

    # ----- Redis -----
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    # ----- Neo4j -----
    NEO4J_URI: str = "bolt://neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # ----- LM Studio host & port -----
    LMSTUDIO_HOST: str = "host.containers.internal"
    LMSTUDIO_PORT: int = 1234
    # Comma-separated list in env; we normalize to list in model_post_init
    LMSTUDIO_EXTRA_HOSTS: list[str] = []
    LMSTUDIO_CHAT_MODEL: str = ""
    LMSTUDIO_REQUIRE_SERVER: bool = False

    # ----- Document ingestion -----
    DOCS_PATH: str = "/mnt/Documents/Documents"
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    DOCS_EXCLUDE_FILE: str = ""
    # Computed in model_post_init
    DOCS_EXCLUDE_DIRS: tuple[str, ...] | str = ()
    DOCS_EXCLUDE_GLOBS: tuple[str, ...] | str = ()
    # Default allowed extensions mirror all registered loaders (text + code).
    DOCS_FILE_EXTS: tuple[str, ...] | list[str] = (
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

    # ----- Cache TTL -----
    CACHE_TTL: int = 3600

    # Defaults for exclude directories
    _DEFAULT_EXCLUDED_DIRS = {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "env",
        ".idea",
        ".vscode",
    }
    _USER_SETTING_FIELDS = (
        "DOCS_PATH",
        "DOCS_EXCLUDE_FILE",
        "DOCS_EXCLUDE_DIRS",
        "DOCS_EXCLUDE_GLOBS",
        "DOCS_FILE_EXTS",
        "CHUNK_SIZE",
        "CHUNK_OVERLAP",
        "EMBEDDING_MAX_TOKENS",
    )

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        # Apply user settings (GUI-editable) unless overridden by environment variables
        fields_set = set(getattr(self, "model_fields_set", set()) or set())
        user_settings_path = Path(getattr(self, "USER_SETTINGS_FILE", "data/settings.json"))
        user_settings = self._load_user_settings(user_settings_path)

        for key in self._USER_SETTING_FIELDS:
            if os.getenv(key) is not None:
                continue
            if key in fields_set:
                continue
            if key in user_settings:
                setattr(self, key, user_settings[key])

        # Normalize booleans/strings that might come in as env strings
        if isinstance(self.WEAVIATE_MULTI_TENANCY, str):
            self.WEAVIATE_MULTI_TENANCY = str(self.WEAVIATE_MULTI_TENANCY).lower() in ("1", "true", "yes")

        # Default tenant handling depends on multitenancy
        raw_tenant = (self.WEAVIATE_DEFAULT_TENANT or "").strip()
        if self.WEAVIATE_MULTI_TENANCY:
            self.WEAVIATE_DEFAULT_TENANT = raw_tenant or "tenant-default"
        else:
            self.WEAVIATE_DEFAULT_TENANT = raw_tenant or ""

        # Normalize extra hosts from env if supplied as comma-separated string
        if isinstance(self.LMSTUDIO_EXTRA_HOSTS, str):
            tokens = [h.strip() for h in self.LMSTUDIO_EXTRA_HOSTS.split(",") if h.strip()]
            self.LMSTUDIO_EXTRA_HOSTS = tokens

        # Build exclude configuration
        dirs, globs = self._build_exclude_configuration()
        self.DOCS_EXCLUDE_DIRS = tuple(sorted(dirs))
        self.DOCS_EXCLUDE_GLOBS = tuple(sorted(globs))

        # Normalize file extensions (accept list/tuple/str env inputs)
        ext_values: list[str]
        raw_exts = self.DOCS_FILE_EXTS
        if isinstance(raw_exts, str):
            ext_values = self._parse_list_env(raw_exts)
        elif isinstance(raw_exts, tuple):
            ext_values = list(raw_exts)
        else:
            ext_values = list(raw_exts)

        def _normalize_ext(value: str) -> str:
            cleaned = str(value or "").strip().lower()
            if not cleaned:
                return ""
            return cleaned if cleaned.startswith(".") else f".{cleaned}"

        normalized_set: set[str] = set()
        for ext in ext_values:
            norm = _normalize_ext(ext)
            if norm:
                normalized_set.add(norm)

        self.DOCS_FILE_EXTS = tuple(sorted(normalized_set))

        # Persist user settings file with normalized values (without overriding env overrides)
        self._persist_user_settings(user_settings_path)

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

    # ------------------------------------------------------------------ #
    # Private helpers for exclude configuration
    # ------------------------------------------------------------------ #

    def _build_exclude_configuration(self):
        raw_entries = list(self._DEFAULT_EXCLUDED_DIRS)
        raw_entries.extend(self._value_as_list(self.DOCS_EXCLUDE_DIRS))
        raw_entries.extend(self._parse_list_env(os.getenv("DOCS_EXCLUDE_DIRS", "")))
        raw_entries.extend(self._parse_list_env(os.getenv("DOCS_EXCLUDE_PATTERNS", "")))
        raw_entries.extend(self._value_as_list(self.DOCS_EXCLUDE_GLOBS))
        raw_entries.extend(self._load_excludes_from_files())

        dirnames, globs = self._classify_exclude_entries(raw_entries)
        return dirnames, globs

    @staticmethod
    def _parse_list_env(raw_value: str | None):
        if not raw_value:
            return []

        value = raw_value.strip()
        if not value:
            return []

        if value.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = []
            else:
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
                if isinstance(parsed, dict):
                    collected = []
                    for key in ("directories", "patterns", "paths"):
                        items = parsed.get(key, [])
                        if isinstance(items, list):
                            collected.extend(str(item).strip() for item in items if str(item).strip())
                    return collected
                return []

        tokens = [token.strip() for token in re.split(r"[,\n]", value) if token.strip()]
        return tokens

    @staticmethod
    def _value_as_list(value: tuple[str, ...] | list[str] | str | None):
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return Config._parse_list_env(value)
        return []

    def _load_excludes_from_files(self):
        entries = []

        requested = self.DOCS_EXCLUDE_FILE
        candidates = [requested] if requested else []
        if not candidates:
            candidates.extend([".ragignore", ".rag-ingest-ignore", "rag-ingest-ignore.txt"])

        seen = set()
        for candidate in candidates:
            if not candidate:
                continue
            candidate_path = Path(candidate).expanduser()
            if not candidate_path.is_absolute():
                candidate_path = Path(os.getcwd()) / candidate_path
            try_path = candidate_path.resolve()
            if try_path in seen or not try_path.is_file():
                continue
            seen.add(try_path)
            entries.extend(self._read_exclude_file(try_path))

        return entries

    def _load_user_settings(self, path: Path) -> dict:
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _persist_user_settings(self, path: Path) -> None:
        desired = {}
        for key in self._USER_SETTING_FIELDS:
            value = getattr(self, key, None)
            if isinstance(value, tuple):
                value = list(value)
            desired[key] = value

        try:
            current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        except (OSError, json.JSONDecodeError):
            current = None

        if current == desired:
            return

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(desired, indent=2), encoding="utf-8")
        except OSError:
            # Silent failure; do not block app startup on settings persistence
            return

    @staticmethod
    def _read_exclude_file(path: Path):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []

        if path.suffix.lower() == ".json":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            if isinstance(parsed, dict):
                collected = []
                for key in ("directories", "patterns", "paths"):
                    items = parsed.get(key, [])
                    if isinstance(items, list):
                        collected.extend(str(item).strip() for item in items if str(item).strip())
                return collected
            # Fall through to treat JSON text as newline separated if unexpected structure.

        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lines.append(stripped)
        return lines

    @staticmethod
    def _classify_exclude_entries(entries):
        dirnames = set()
        globs = set()

        for entry in entries:
            candidate = str(entry).strip()
            if not candidate:
                continue
            normalized = candidate.replace("\\", "/").strip()
            normalized = normalized.rstrip("/")
            if not normalized:
                continue
            if Config._is_glob_like(normalized) or "/" in normalized:
                globs.add(normalized)
            else:
                dirnames.add(normalized)

        return dirnames, globs

    @staticmethod
    def _is_glob_like(entry: str):
        return any(char in entry for char in "*?[]")
