# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Iterator, Callable, TypeVar
from urllib.parse import urlparse

import requests
import weaviate
from weaviate import WeaviateClient, connect_to_custom
from weaviate.classes.init import Auth
from weaviate.config import AdditionalConfig, Timeout
from weaviate.classes.config import Configure, Property, DataType, Tokenization
from weaviate.classes.query import Filter

from src.config.settings import Config
from src.interfaces.vector_interface import VectorInterface, ScoredItem
from src import logger

T = TypeVar("T")


class WeaviateRepository(VectorInterface):
    """
    Weaviate adapter that conforms to VectorInterface (Python client v4 only).

    Public methods:
        - upsert(key, vector, metadata, tenant_id=None) -> None
        - search(vector, top_k=5, filters=None, tenant_id=None) -> List[ScoredItem]
        - iter_payloads(batch_size=256, tenant_id=None) -> Iterator[dict]
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        """
        Initialize repository and ensure Weaviate connectivity and schema.

        Notes:
            - Uses Weaviate Python client v4 exclusively.
            - Removes any v3 fallback logic.
        """
        cfg = config or Config()
        self._class = cfg.WEAVIATE_CLASS
        self._mt = bool(cfg.WEAVIATE_MULTI_TENANCY)
        raw_default_tenant = getattr(cfg, "WEAVIATE_DEFAULT_TENANT", "") or ""
        self._default_tenant = str(raw_default_tenant).strip() or None
        self._timeout = int(cfg.WEAVIATE_TIMEOUT)
        self._grpc_port = int(getattr(cfg, "WEAVIATE_GRPC_PORT", 50051))
        self._connect_retries = max(1, int(getattr(cfg, "WEAVIATE_CONNECT_RETRIES", 5)))
        self._connect_backoff = max(0.1, float(getattr(cfg, "WEAVIATE_CONNECT_BACKOFF", 2.0)))

        additional = self._build_additional_config()
        self.client = self._retry("connect", lambda: self._init_client_v4(cfg, additional))
        self._retry("wait for readiness", lambda: self._wait_for_cluster_ready(cfg))
        self._retry("ensure schema", lambda: self._ensure_class(cfg))

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _retry(self, name: str, func: Callable[[], T]) -> T:
        """
        Retry helper with backoff for transient failures.

        Args:
            name: Human-readable operation name for logging.
            func: Callable to execute.

        Returns:
            The callable's return value.

        Raises:
            The last captured exception if all attempts fail.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._connect_retries + 1):
            try:
                return func()
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Weaviate %s attempt %s/%s failed: %s",
                    name,
                    attempt,
                    self._connect_retries,
                    exc,
                )
                if attempt < self._connect_retries:
                    time.sleep(self._connect_backoff)
        assert last_exc is not None
        raise last_exc

    def _build_additional_config(self) -> Optional[AdditionalConfig]:
        """
        Build AdditionalConfig with Timeout settings if supported by the installed client.

        Returns:
            AdditionalConfig instance or None if construction fails.
        """
        try:
            # v4 supports granular timeouts: init/query/insert
            return AdditionalConfig(
                timeout=Timeout(init=self._timeout, query=self._timeout, insert=self._timeout)
            )
        except Exception:
            # Fail-soft in case of unexpected client variation
            return None

    def _nodes_payload_has_leader(self, payload: Any) -> bool:
        """
        Best-effort check to detect a Raft leader in /v1/nodes payload.
        Weaviate payloads can vary across versions; this method tolerates several shapes.
        """
        try:
            nodes = payload if isinstance(payload, list) else payload.get("nodes")
        except Exception:
            nodes = None
        if not nodes:
            return False
        for node in nodes:
            if not isinstance(node, dict):
                continue
            low = {str(k).lower(): v for k, v in node.items()}
            role = str(low.get("role", "")).lower()
            if role == "leader":
                return True
            if str(low.get("is_leader", "")).lower() in ("true", "1"):
                return True
            raft = low.get("raft") or low.get("raft_info") or {}
            if isinstance(raft, dict):
                rlow = {str(k).lower(): v for k, v in raft.items()}
                rstate = str(rlow.get("state", "")).lower()
                if rstate == "leader":
                    return True
            if "leader" in str(node).lower():
                return True
        return False

    def _wait_for_cluster_ready(self, cfg: Config) -> None:
        """
        Poll Weaviate health endpoints until the node reports readiness and a Raft leader is elected.

        This method tolerates temporary 403/5xx responses that may appear while Raft elects a leader.

        Raises:
            TimeoutError if readiness is not achieved within the configured time.
        """
        base_url = cfg.WEAVIATE_URL.rstrip("/")
        probe_paths = ["/.well-known/ready", "/v1/.well-known/ready", "/v1/nodes"]
        deadline = time.time() + max(float(self._timeout) * 6.0, 60.0)
        last_error: Optional[Exception] = None

        while time.time() < deadline:
            for path in probe_paths:
                url = f"{base_url}{path}"
                try:
                    resp = requests.get(url, timeout=self._timeout)
                except requests.RequestException as exc:
                    last_error = exc
                    continue

                if resp.status_code in (200, 204):
                    if path.endswith("/nodes"):
                        try:
                            payload = resp.json()
                        except ValueError as exc:
                            last_error = RuntimeError(f"Invalid JSON from {url}: {exc}")
                            continue
                        nodes = payload if isinstance(payload, list) else payload.get("nodes")
                        if not nodes:
                            last_error = RuntimeError("Weaviate /v1/nodes returned empty nodes list")
                            continue
                        all_ready = True
                        for node in nodes:
                            if not isinstance(node, dict):
                                continue
                            status = str(node.get("status", "")).lower()
                            if status not in ("ready", "healthy"):
                                all_ready = False
                                break
                        if len(nodes) == 1:
                            n0 = nodes[0] if isinstance(nodes[0], dict) else {}
                            if str(n0.get("status", "")).lower() in ("ready", "healthy"):
                                return
                        if all_ready and self._nodes_payload_has_leader(payload):
                            return
                        last_error = RuntimeError(f"Weaviate nodes not ready or leader missing: {payload}")
                        continue
                    return

                if resp.status_code in (401, 403, 500, 503):
                    text = resp.text.strip() if isinstance(resp.text, str) else str(resp.text)
                    if resp.status_code == 403 and "leader not found" in text.lower():
                        last_error = RuntimeError(
                            f"Weaviate readiness: {url} => 403 (leader not found) – waiting for election"
                        )
                    else:
                        last_error = RuntimeError(
                            f"Weaviate readiness probe {url} returned {resp.status_code}: {text}"
                        )
                    continue

                try:
                    resp.raise_for_status()
                except requests.RequestException as exc:
                    last_error = exc
            time.sleep(self._connect_backoff)

        if last_error:
            raise last_error
        raise TimeoutError("Timed out waiting for Weaviate readiness")

    def _init_client_v4(self, cfg: Config, additional: Optional[AdditionalConfig]) -> WeaviateClient:
        """
        Initialize a Weaviate v4 client using `connect_to_custom`.

        Args:
            cfg: Application configuration instance.
            additional: Optional AdditionalConfig.

        Returns:
            An initialized WeaviateClient.

        Raises:
            RuntimeError if the client cannot be created.
        """
        parsed = urlparse(cfg.WEAVIATE_URL)
        scheme = (parsed.scheme or "http").lower()
        host = parsed.hostname or cfg.WEAVIATE_URL
        http_port = parsed.port or (443 if scheme == "https" else 8080)
        grpc_port = self._grpc_port or 50051
        secure = scheme == "https"

        auth_credentials = None
        api_key = getattr(cfg, "WEAVIATE_API_KEY", "") or None
        if api_key:
            auth_credentials = Auth.api_key(api_key)

        kwargs: Dict[str, Any] = {
            "http_host": host,
            "http_port": http_port,
            "grpc_host": host,
            "grpc_port": grpc_port,
            "http_secure": secure,
            "grpc_secure": secure,
            "skip_init_checks": True,
        }
        if auth_credentials is not None:
            kwargs["auth_credentials"] = auth_credentials
        if additional is not None:
            kwargs["additional_config"] = additional

        client = connect_to_custom(**kwargs)
        if not client:
            raise RuntimeError("Failed to initialize Weaviate v4 client")
        return client

    # -------------------------------------------------------------------------
    # Schema management
    # -------------------------------------------------------------------------

    def _ensure_class(self, cfg: Config) -> None:
        """
        Ensure the target collection exists; create it if missing.

        Notes:
            - Uses v4 `collections` API.
            - Vectorizer is set to `none` by default (explicit vectors required).
        """
        schema = self.client.collections
        existing_classes = schema.list_all()
        names = [
            c.name if hasattr(c, "name") else str(c)
            for c in existing_classes
        ]
        if self._class not in names:
            # IMPORTANT: use `data_type=` (snake_case) to satisfy Pydantic validation.
            schema.create(
                self._class,
                vectorizer_config=Configure.Vectorizer.none(),  # v4 expects vectorizer_config for these helpers
                properties=[
                    Property(name="external_id", data_type=DataType.TEXT, tokenization=Tokenization.WORD),
                    Property(name="content", data_type=DataType.TEXT, tokenization=Tokenization.WORD),
                    Property(name="structure_summary", data_type=DataType.TEXT),
                    Property(name="visibility", data_type=DataType.TEXT),
                    Property(name="owner_id", data_type=DataType.TEXT),
                    Property(name="allowed_user_ids", data_type=DataType.TEXT_ARRAY),
                    Property(name="hash", data_type=DataType.TEXT),
                    Property(name="source", data_type=DataType.TEXT),
                ],
                multi_tenancy_config=Configure.multi_tenancy(enabled=bool(cfg.WEAVIATE_MULTI_TENANCY)),
            )

            logger.info(
                "Created Weaviate class '%s' (multitenant=%s)",
                self._class,
                cfg.WEAVIATE_MULTI_TENANCY,
            )

        if self._mt and self._default_tenant:
            self._ensure_default_tenant()

    def _ensure_default_tenant(self) -> None:
        """
        Create the configured default tenant if missing (Weaviate multi-tenancy).
        """
        if not self._mt or not self._default_tenant:
            return

        collection = self.client.collections.get(self._class)
        tenants_api = getattr(collection, "tenants", None)
        if tenants_api is None:
            logger.warning(
                "Weaviate client does not expose tenants API while multitenancy is enabled."
            )
            return

        existing: set[str] = set()
        try:
            listed = tenants_api.list() if hasattr(tenants_api, "list") else tenants_api.get()  # type: ignore[attr-defined]
        except Exception:
            listed = []

        for tenant in listed or []:
            name = getattr(tenant, "name", None)
            if not name and isinstance(tenant, dict):
                name = tenant.get("name") or tenant.get("id")
            if not name:
                name = str(tenant)
            existing.add(str(name))

        if self._default_tenant in existing:
            return

        try:
            tenants_api.create([self._default_tenant])
            return
        except TypeError:
            try:
                tenants_api.create(self._default_tenant)
                return
            except TypeError:
                try:
                    from weaviate.classes.tenants import Tenant  # type: ignore

                    tenants_api.create(Tenant(name=self._default_tenant))  # type: ignore[call-arg]
                    return
                except Exception as exc:
                    if "already exist" not in str(exc).lower():
                        raise
            except Exception as exc:
                if "already exist" not in str(exc).lower():
                    raise
        except Exception as exc:
            if "already exist" not in str(exc).lower():
                raise

    def _coll(self, tenant_id: Optional[str]):
        """
        Get the collection handle, optionally bound to a tenant.

        Args:
            tenant_id: Tenant name if multi-tenancy is enabled.

        Returns:
            Collection handle.
        """
        coll = self.client.collections.get(self._class)
        if not self._mt:
            return coll

        effective_tenant = (tenant_id or self._default_tenant)
        if not effective_tenant:
            raise RuntimeError(
                "Weaviate multi-tenancy is enabled but no tenant_id was provided. "
                "Set WEAVIATE_DEFAULT_TENANT or pass tenant_id explicitly."
            )
        return coll.with_tenant(str(effective_tenant))

    # -------------------------------------------------------------------------
    # VectorInterface implementation
    # -------------------------------------------------------------------------

    def upsert(
        self,
        key: Optional[str],
        vector: List[float],
        metadata: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> None:
        """
        Insert or update an object using a stable identifier.

        Args:
            key: Preferred unique id to use as UUID.
            vector: Vector to store (required if using vectorizer 'none' or named vectors).
            metadata: Object properties. 'content' is treated as the primary text field.
            tenant_id: Optional tenant name.

        Raises:
            ValueError: If a stable id cannot be determined.
        """
        coll = self._coll(tenant_id)

        raw_id = key or metadata.get("hash") or metadata.get("external_id")
        if not raw_id:
            raise ValueError("upsert requires a stable key/external_id/hash")
        uuid_id = self._normalize_uuid(raw_id)

        properties = dict(metadata)
        text_content = properties.pop("content", None) or properties.get("structure_summary") or ""
        properties["external_id"] = key or metadata.get("external_id") or metadata.get("hash") or raw_id

        try:
            coll.data.update(
                uuid=uuid_id,
                properties={**properties, "content": text_content},
                vector=vector,
            )
        except Exception:
            coll.data.insert(
                properties={**properties, "content": text_content},
                uuid=uuid_id,
                vector=vector,
            )

    def _build_where(self, filters: Optional[Dict[str, Any]]) -> Optional[Filter]:
        """
        Build a boolean filter according to visibility and user ownership.

        Args:
            filters: Dictionary with visibility/owner_id/user_id conditions.

        Returns:
            A Filter instance or None if no conditions are required.
        """
        if not filters:
            return None

        shoulds: List[Filter] = []

        if filters.get("visibility") == "public":
            shoulds.append(Filter.by_property("visibility").equal("public"))
        else:
            shoulds.append(Filter.by_property("visibility").equal("public"))

        owner_id = filters.get("owner_id")
        if owner_id:
            shoulds.append(Filter.by_property("owner_id").equal(owner_id))

        user_id = filters.get("user_id")
        if user_id:
            shoulds.append(Filter.by_property("allowed_user_ids").contains_any([user_id]))
            shoulds.append(Filter.by_property("owner_id").equal(user_id))

        if not shoulds:
            return None

        combined = shoulds[0]
        for s in shoulds[1:]:
            combined = combined | s
        return combined

    @staticmethod
    def _normalize_uuid(value: Any) -> str:
        """
        Convert arbitrary stable ids into UUID strings accepted by Weaviate.
        """
        import uuid

        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            return str(uuid.uuid5(uuid.NAMESPACE_URL, str(value)))

    def search(
        self,
        vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[ScoredItem]:
        """
        Vector search using near_vector.

        Args:
            vector: Query vector.
            top_k: Maximum number of results.
            filters: Optional visibility/ownership filter dict.
            tenant_id: Optional tenant name.

        Returns:
            List of ScoredItem with id, score (distance), and payload (properties).
        """
        coll = self._coll(tenant_id)
        where = self._build_where(filters)

        result = coll.query.near_vector(vector=vector, limit=top_k, filters=where)

        output: List[ScoredItem] = []
        for obj in getattr(result, "objects", []) or []:  # type: ignore[attr-defined]
            meta = getattr(obj, "metadata", None)
            distance = getattr(meta, "distance", None)
            score = None if distance is None else float(distance)
            props = getattr(obj, "properties", {}) or {}
            output.append(ScoredItem(id=str(obj.uuid), score=score, payload=props))
        return output

    def iter_payloads(
        self,
        batch_size: int = 256,
        tenant_id: Optional[str] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        Iterate all stored object properties in pages.

        Args:
            batch_size: Page size.
            tenant_id: Optional tenant name.

        Yields:
            Object properties for each stored document.
        """
        coll = self._coll(tenant_id)
        cursor: Optional[str] = None

        while True:
            result = coll.query.fetch_objects(limit=batch_size, cursor=cursor)
            objects = getattr(result, "objects", []) or []  # type: ignore[attr-defined]
            if not objects:
                break

            for obj in objects:
                yield getattr(obj, "properties", {}) or {}

            page_info = getattr(result, "page_info", None)
            cursor = getattr(page_info, "end_cursor", None)
            if not getattr(page_info, "has_next_page", False):
                break

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    def __del__(self) -> None:
        """
        Ensure client close on GC if available.
        """
        try:
            if hasattr(self, "client") and isinstance(self.client, weaviate.WeaviateClient):
                self.client.close()
        except Exception:
            pass
