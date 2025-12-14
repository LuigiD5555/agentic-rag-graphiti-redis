"""Module that implements a hybrid RAG engine using vector and graph stores."""
import copy
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Mapping, Iterable
from src.rag.interfaces.embedding_interface import EmbeddingInterface
from src.rag.interfaces.vector_interface import VectorInterface, ScoredItem
from src.rag.interfaces.graph_interface import GraphInterface
from src.rag.interfaces.cache_interface import CacheServiceProtocol
from src.rag.interfaces.chat_interface import ChatInterface
from src import logger
from src.storage.graph.null_repository import NullGraphRepository
from src.storage.vector.ingestion.excludes import (
    classify_exclude_entries,
    load_excludes_from_files,
    parse_list_env,
    value_as_list,
)


def _build_user_filter(user_id: Optional[str]) -> Dict[str, Any]:
    """
    Backend-agnostic filter description.
    The vector backend will translate this to its own query/filter format.
    Semantics:
      - visibility == 'public' OR
      - owner_id == user_id OR
      - allowed_user_ids contains user_id
    """
    if not user_id:
        return {"visibility": "public"}
    return {
        "user_id": user_id,     # for allowed_user_ids contains
        "owner_id": user_id,    # allow owner docs
        "visibility": "public", # always include public
    }


def _extract_settings_defaults(source: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract ALL-CAPS and private constants from a settings module mapping."""
    defaults: Dict[str, Any] = {}
    for key, value in source.items():
        if key.startswith("__"):
            continue
        if key.isupper() or (key.startswith("_") and not key.startswith("__")):
            if callable(value):
                continue
            defaults[key] = value
    return defaults


def _load_env_file(path: Path) -> Dict[str, str]:
    env_values: Dict[str, str] = {}
    if not path.is_file():
        return env_values
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return env_values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        env_values[key.strip()] = raw_value.strip().strip('"').strip("'")
    return env_values


def _coerce_env_value(raw_value: str, default_value: Any) -> Any:
    if isinstance(default_value, bool):
        return str(raw_value).lower() in ("1", "true", "yes", "on")
    if isinstance(default_value, int) and not isinstance(default_value, bool):
        try:
            return int(raw_value)
        except ValueError:
            return default_value
    if isinstance(default_value, float):
        try:
            return float(raw_value)
        except ValueError:
            return default_value
    if isinstance(default_value, (list, tuple)):
        return parse_list_env(raw_value)
    if isinstance(default_value, dict):
        try:
            parsed = json.loads(raw_value)
            return parsed if isinstance(parsed, dict) else default_value
        except json.JSONDecodeError:
            return default_value
    return raw_value


class ConfigLogic:
    """
    Logic helpers for Config: normalization, excludes, and derived URLs.

    Kept here to separate behavior from the declarative settings layout in
    src/settings.py, per the Django-like expectations.
    """

    def normalize(self) -> None:
        # Apply user settings (GUI-editable) unless overridden by environment variables
        fields_set = set(getattr(self, "_fields_set", set()) or set())
        env_fields = set(getattr(self, "_env_fields", set()) or set())
        override_fields = set(getattr(self, "_override_fields", set()) or set())
        user_settings_path = Path(getattr(self, "USER_SETTINGS_FILE", "data/settings.json"))
        user_settings = self._load_user_settings(user_settings_path)

        for key in getattr(self, "_USER_SETTING_FIELDS", ()):
            if key in override_fields:
                # Explicit overrides stay highest priority.
                continue
            if key in user_settings:
                # User JSON wins over env/defaults for allowed fields.
                setattr(self, key, user_settings[key])
                fields_set.add(key)
                continue
            if key in env_fields:
                # Keep env value applied earlier.
                continue

        self._hydrate_backend_settings(fields_set)

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
            ext_values = parse_list_env(raw_exts)
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

    def _hydrate_backend_settings(self, fields_set: set[str]) -> None:
        """
        Populate derived per-backend attributes from Django-like registries.

        Canonical config lives in:
        - VECTOR_STORES (weaviate)
        - GRAPH_STORES (neo4j)
        - CACHES (redis)

        We expose derived attributes (WEAVIATE_*, NEO4J_*, REDIS_*) for convenience.
        """

        def _set_if_unset(key: str, value: Any) -> None:
            if key in fields_set:
                return
            if hasattr(self, key):
                current = getattr(self, key)
                if current not in (None, ""):
                    return
            setattr(self, key, value)

        # -------------------------
        # Vector store (Weaviate)
        # -------------------------
        vector_stores = getattr(self, "VECTOR_STORES", None) or {}
        default_vector = vector_stores.get("default") if isinstance(vector_stores, dict) else None
        if isinstance(default_vector, dict):
            engine = default_vector.get("ENGINE") or default_vector.get("BACKEND") or "weaviate"
            if str(engine).lower() == "weaviate":
                _set_if_unset("VECTOR_BACKEND", "weaviate")
                options = default_vector.get("OPTIONS") if isinstance(default_vector.get("OPTIONS"), dict) else {}

                host = default_vector.get("HOST") or "localhost"
                port = default_vector.get("PORT") or 8080
                scheme = default_vector.get("SCHEME") or "http"
                path = default_vector.get("PATH") or ""
                url = default_vector.get("URL")
                if not url:
                    base = f"{scheme}://{host}:{port}"
                    url = f"{base}/{str(path).lstrip('/')}" if path else base

                _set_if_unset("WEAVIATE_URL", os.getenv("WEAVIATE_URL") or url)
                _set_if_unset("WEAVIATE_API_KEY", os.getenv("WEAVIATE_API_KEY") or default_vector.get("API_KEY") or "")
                _set_if_unset("WEAVIATE_CLASS", os.getenv("WEAVIATE_CLASS") or default_vector.get("CLASS") or default_vector.get("NAME") or "RAGDocument")
                _set_if_unset("WEAVIATE_TIMEOUT", int(os.getenv("WEAVIATE_TIMEOUT") or default_vector.get("TIMEOUT") or 30))
                _set_if_unset(
                    "WEAVIATE_GRPC_PORT",
                    int(os.getenv("WEAVIATE_GRPC_PORT") or default_vector.get("GRPC_PORT") or options.get("GRPC_PORT") or 50051),
                )
                _set_if_unset(
                    "WEAVIATE_CONNECT_RETRIES",
                    int(os.getenv("WEAVIATE_CONNECT_RETRIES") or default_vector.get("CONNECT_RETRIES") or options.get("CONNECT_RETRIES") or 5),
                )
                _set_if_unset(
                    "WEAVIATE_CONNECT_BACKOFF",
                    float(os.getenv("WEAVIATE_CONNECT_BACKOFF") or default_vector.get("CONNECT_BACKOFF") or options.get("CONNECT_BACKOFF") or 2.0),
                )
                multitenancy_raw = os.getenv("WEAVIATE_MULTI_TENANCY")
                if multitenancy_raw is not None:
                    multitenancy = str(multitenancy_raw).lower() in ("1", "true", "yes", "on")
                else:
                    multitenancy = default_vector.get("MULTI_TENANCY")
                    if multitenancy is None:
                        multitenancy = options.get("MULTI_TENANCY")
                    if multitenancy is None:
                        multitenancy = True
                _set_if_unset("WEAVIATE_MULTI_TENANCY", multitenancy)
                _set_if_unset(
                    "WEAVIATE_DEFAULT_TENANT",
                    os.getenv("WEAVIATE_DEFAULT_TENANT")
                    or default_vector.get("DEFAULT_TENANT")
                    or options.get("DEFAULT_TENANT")
                    or "tenant-default",
                )

        # -------------------------
        # Graph store (Neo4j)
        # -------------------------
        graph_stores = getattr(self, "GRAPH_STORES", None) or {}
        default_graph = graph_stores.get("default") if isinstance(graph_stores, dict) else None
        if isinstance(default_graph, dict):
            engine = default_graph.get("ENGINE") or default_graph.get("BACKEND") or "neo4j"
            if str(engine).lower() == "neo4j":
                host = default_graph.get("HOST") or "neo4j"
                port = default_graph.get("PORT") or 7687
                scheme = default_graph.get("SCHEME") or "bolt"
                uri = default_graph.get("URI") or default_graph.get("URL") or f"{scheme}://{host}:{port}"

                _set_if_unset("NEO4J_URI", os.getenv("NEO4J_URI") or uri)
                _set_if_unset("NEO4J_USER", os.getenv("NEO4J_USER") or default_graph.get("USER") or "neo4j")
                _set_if_unset("NEO4J_PASSWORD", os.getenv("NEO4J_PASSWORD") or default_graph.get("PASSWORD") or "")

        # -------------------------
        # Cache (Redis)
        # -------------------------
        caches = getattr(self, "CACHES", None) or {}
        default_cache = caches.get("default") if isinstance(caches, dict) else None
        if isinstance(default_cache, dict):
            backend = default_cache.get("BACKEND") or default_cache.get("ENGINE") or "redis"
            if str(backend).lower() == "redis":
                host = default_cache.get("HOST")
                port = default_cache.get("PORT")
                if not host or not port:
                    loc = str(default_cache.get("LOCATION") or "").strip()
                    if loc.startswith("redis://"):
                        try:
                            host_port = loc.split("://", 1)[1].split("/", 1)[0]
                            host, port_str = host_port.split(":", 1)
                            port = int(port_str)
                        except Exception:
                            host = host or "redis"
                            port = port or 6379
                _set_if_unset("REDIS_HOST", os.getenv("REDIS_HOST") or host or "redis")
                raw_port = os.getenv("REDIS_PORT")
                _set_if_unset("REDIS_PORT", int(raw_port) if raw_port is not None else int(port or 6379))

        # -------------------------
        # Providers (LM Studio et al.)
        # -------------------------
        providers = getattr(self, "PROVIDERS", None) or {}
        provider_cfg = None
        selected_alias = (os.getenv("PROVIDER_ALIAS") or os.getenv("PROVIDER") or "").strip()
        if isinstance(providers, dict):
            if selected_alias and selected_alias in providers:
                provider_cfg = providers.get(selected_alias)
            elif selected_alias:
                # Interpret PROVIDER as an engine name and find the first matching entry.
                for candidate in providers.values():
                    if not isinstance(candidate, dict):
                        continue
                    engine = (candidate.get("ENGINE") or candidate.get("BACKEND") or "").strip().lower()
                    if engine and engine == selected_alias.lower():
                        provider_cfg = candidate
                        break
            if provider_cfg is None:
                provider_cfg = providers.get("default")

        if isinstance(provider_cfg, dict):
            engine = (provider_cfg.get("ENGINE") or provider_cfg.get("BACKEND") or "lmstudio").strip().lower()
            _set_if_unset("PROVIDER", engine)

            if engine == "lmstudio":
                host = os.getenv("LMSTUDIO_HOST") or provider_cfg.get("HOST") or "host.containers.internal"
                port = int(os.getenv("LMSTUDIO_PORT") or provider_cfg.get("PORT") or 1234)
                extra_hosts = provider_cfg.get("EXTRA_HOSTS") or []
                if isinstance(extra_hosts, str):
                    extra_hosts = [h.strip() for h in extra_hosts.split(",") if h.strip()]
                chat_model = os.getenv("LMSTUDIO_CHAT_MODEL") or provider_cfg.get("CHAT_MODEL") or ""
                require_server_env = os.getenv("LMSTUDIO_REQUIRE_SERVER")
                if require_server_env is not None:
                    require_server = str(require_server_env).lower() in ("1", "true", "yes", "on")
                else:
                    require_server = bool(provider_cfg.get("REQUIRE_SERVER"))

                _set_if_unset("LMSTUDIO_HOST", host)
                _set_if_unset("LMSTUDIO_PORT", port)
                _set_if_unset("LMSTUDIO_EXTRA_HOSTS", extra_hosts)
                _set_if_unset("LMSTUDIO_CHAT_MODEL", chat_model)
                _set_if_unset("LMSTUDIO_REQUIRE_SERVER", require_server)

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
        raw_entries = list(getattr(self, "_DEFAULT_EXCLUDED_FILES", set()))
        raw_entries.extend(value_as_list(self.DOCS_EXCLUDE_DIRS))
        raw_entries.extend(parse_list_env(os.getenv("DOCS_EXCLUDE_DIRS", "")))
        raw_entries.extend(parse_list_env(os.getenv("DOCS_EXCLUDE_PATTERNS", "")))
        raw_entries.extend(value_as_list(self.DOCS_EXCLUDE_GLOBS))
        raw_entries.extend(load_excludes_from_files(self.DOCS_EXCLUDE_FILE))

        dirnames, globs = classify_exclude_entries(raw_entries)
        return dirnames, globs

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
        for key in getattr(self, "_USER_SETTING_FIELDS", ()):
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

    def copy(self, update: Mapping[str, Any] | None = None) -> "ConfigLogic":
        """Clone the current config, applying optional updates and re-normalizing."""
        data = {k: copy.deepcopy(v) for k, v in self.__dict__.items()}
        new_obj = ConfigLogic()
        for key, value in data.items():
            setattr(new_obj, key, value)
        fields_set = set(getattr(self, "_fields_set", set()) or set())
        if update:
            for key, value in update.items():
                setattr(new_obj, key, value)
            fields_set.update(update.keys())
        new_obj._fields_set = fields_set
        new_obj.normalize()
        return new_obj


class ConfigFactory:
    """Callable factory that produces ConfigLogic instances from declarative defaults."""

    def __init__(self, defaults: Mapping[str, Any], env_path: str | Path | None = None) -> None:
        self._defaults = _extract_settings_defaults(defaults)
        # Prefer explicit env_path, else settings.ENV_FILE, else ".env"
        chosen_env = env_path or self._defaults.get("ENV_FILE") or ".env"
        self._env_path = self._resolve_env_path(chosen_env)

    @staticmethod
    def _resolve_env_path(env_path: str | Path) -> Path:
        """Return an absolute path to the .env file, resilient to CWD changes."""
        candidate = Path(env_path)
        if candidate.is_absolute():
            return candidate
        # Try repo root (two parents up from src/rag/)
        repo_root = Path(__file__).resolve().parents[2]
        repo_candidate = repo_root / candidate
        if repo_candidate.is_file():
            return repo_candidate
        # Fallback to current working directory
        return candidate

    def __call__(self, **overrides: Any) -> "ConfigLogic":
        values = copy.deepcopy(dict(self._defaults))
        fields_set: set[str] = set()
        env_fields: set[str] = set()
        override_fields: set[str] = set()

        env_file_values = _load_env_file(Path(self._env_path))
        env_values = {**env_file_values, **os.environ}
        for key, default_value in list(values.items()):
            if key.startswith("_"):
                continue
            raw_env = env_values.get(key)
            if raw_env is None:
                continue
            values[key] = _coerce_env_value(str(raw_env), default_value)
            fields_set.add(key)
            env_fields.add(key)

        for key, value in overrides.items():
            values[key] = value
            fields_set.add(key)
            override_fields.add(key)

        cfg = ConfigLogic()
        for key, value in values.items():
            setattr(cfg, key, copy.deepcopy(value))
        cfg._fields_set = fields_set
        cfg._env_fields = env_fields
        cfg._override_fields = override_fields
        cfg.normalize()
        return cfg


class RAGEngine:
    """
    Hybrid RAG engine combining vector search and graph search,
    with optional caching for improved performance.
    """

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
        """Retrieve context from vector store (backend-agnostic)."""
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
        """Retrieve context from graph store (Neo4j)."""
        logger.info("Retrieving graph context for query: %s", query)
        results = self.graph.search(query)
        return "\n".join(results)

    def _build_prompt(self, query: str, vector_context: str, graph_context: str) -> str:
        """Construct the final prompt for the LLM using both contexts."""
        context = f"Vector DB:\n{vector_context}\n\nGraph:\n{graph_context}"
        return f"Context:\n{context}\n\nQuestion: {query}\nAnswer in detail:"

    def answer(self, query: str, user_id: Optional[str] = None, tenant_id: Optional[str] = None) -> str:
        """
        Generate an answer by combining vector + graph context with caching support.
        """
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
