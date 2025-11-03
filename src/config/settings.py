import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv


class Config:
    """
    Centralized runtime configuration.

    Notes:
    - Vector DB backend is selected via VECTOR_BACKEND; default is "weaviate".
    """

    def __init__(self):
        load_dotenv()

        self._DEFAULT_EXCLUDED_DIRS = {
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            "env",
            ".idea",
            ".vscode",
        }

        # ----- Vector DB backend selection -----
        # Current supported value: "weaviate"
        self.VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "weaviate").lower()

        # ----- Weaviate configuration -----
        self.WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://localhost:8080")
        self.WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY", "")
        self.WEAVIATE_CLASS = os.getenv("WEAVIATE_CLASS", "RAGDocument")
        # If running native multitenancy, keep True; else you can emulate with prefixes in the repository.
        self.WEAVIATE_MULTI_TENANCY = os.getenv("WEAVIATE_MULTI_TENANCY", "true").lower() in ("1", "true", "yes")
        raw_default_tenant = os.getenv("WEAVIATE_DEFAULT_TENANT", "").strip()
        if self.WEAVIATE_MULTI_TENANCY:
            self.WEAVIATE_DEFAULT_TENANT = raw_default_tenant or "tenant-default"
        else:
            self.WEAVIATE_DEFAULT_TENANT = raw_default_tenant or ""
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
        self.DOCS_EXCLUDE_FILE = os.getenv("DOCS_EXCLUDE_FILE", "").strip()
        (
            self.DOCS_EXCLUDE_DIRS,
            self.DOCS_EXCLUDE_GLOBS,
        ) = self._build_exclude_configuration()

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

    # ------------------------------------------------------------------ #
    # Private helpers for exclude configuration
    # ------------------------------------------------------------------ #

    def _build_exclude_configuration(self):
        raw_entries = list(self._DEFAULT_EXCLUDED_DIRS)
        raw_entries.extend(self._parse_list_env(os.getenv("DOCS_EXCLUDE_DIRS", "")))
        raw_entries.extend(self._parse_list_env(os.getenv("DOCS_EXCLUDE_PATTERNS", "")))
        raw_entries.extend(self._load_excludes_from_files())

        dirnames, globs = self._classify_exclude_entries(raw_entries)

        return tuple(sorted(dirnames)), tuple(sorted(globs))

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
