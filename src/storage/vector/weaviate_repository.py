from __future__ import annotations
import re
import time
from typing import Any, Dict, List, Optional, Iterator, Callable, TypeVar
from urllib.parse import urlparse

import weaviate
from weaviate.classes.init import AdditionalConfig, Timeout
from weaviate.classes.config import Configure, Property, DataType, Tokenization
from weaviate.classes.query import Filter

from src.config.settings import Config
from src.interfaces.vector_interface import VectorInterface, ScoredItem
from src import logger

T = TypeVar("T")


class WeaviateRepository(VectorInterface):
    """
    Weaviate adapter that conforms to VectorInterface:
      - upsert(key, vector, metadata, tenant_id=None)
      - search(vector, top_k=5, filters=None, tenant_id=None) -> List[ScoredItem]
      - iter_payloads(batch_size=256, tenant_id=None) -> Iterator[dict]
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        cfg = config or Config()
        self._class = cfg.WEAVIATE_CLASS
        self._mt = bool(cfg.WEAVIATE_MULTI_TENANCY)
        self._timeout = int(cfg.WEAVIATE_TIMEOUT)
        self._grpc_port = int(getattr(cfg, "WEAVIATE_GRPC_PORT", 50051))
        self._connect_retries = max(1, int(getattr(cfg, "WEAVIATE_CONNECT_RETRIES", 5)))
        self._connect_backoff = max(0.1, float(getattr(cfg, "WEAVIATE_CONNECT_BACKOFF", 2.0)))

        additional = self._build_additional_config()
        self.client = self._retry("connect", lambda: self._init_client(cfg, additional))
        self._retry("ensure schema", lambda: self._ensure_class(cfg))

    def _retry(self, name: str, func: Callable[[], T]) -> T:
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

    def _build_additional_config(self):
        try:
            return AdditionalConfig(timeout=Timeout(init=self._timeout, query=self._timeout))
        except Exception:
            # Older/newer client versions may not support the AdditionalConfig helper.
            return None

    def _init_client(self, cfg: Config, additional: Optional[AdditionalConfig]):
        client = self._init_client_v3(cfg, additional)
        if client is not None:
            return client
        return self._init_client_v4(cfg, additional)

    def _init_client_v3(self, cfg: Config, additional: Optional[AdditionalConfig]):
        """
        Attempt to initialise the legacy v3-style client (url + auth_client_secret).
        Returns the client when successful, otherwise None.
        """
        if not hasattr(weaviate, "WeaviateClient"):
            return None

        kwargs: Dict[str, Any] = {}
        if additional is not None:
            kwargs["additional_config"] = additional
        auth_obj = None
        if getattr(cfg, "WEAVIATE_API_KEY", "") and hasattr(weaviate, "auth"):
            auth_cls = getattr(weaviate.auth, "AuthApiKey", None)
            if auth_cls:
                auth_obj = auth_cls(api_key=cfg.WEAVIATE_API_KEY)
                kwargs["auth_client_secret"] = auth_obj

        try:
            return weaviate.WeaviateClient(url=cfg.WEAVIATE_URL, **kwargs)
        except TypeError:
            # Signature mismatch (likely v4 client); fall back.
            return None

    def _init_client_v4(self, cfg: Config, additional: Optional[AdditionalConfig]):
        """
        Initialise the modern v4 client by trying the official helper constructors.
        """
        parsed = urlparse(cfg.WEAVIATE_URL)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or cfg.WEAVIATE_URL
        http_port = parsed.port or (443 if scheme == "https" else 80)
        grpc_port = self._grpc_port or 50051
        secure = scheme == "https"

        auth_credentials = None
        if getattr(cfg, "WEAVIATE_API_KEY", "") and hasattr(weaviate, "auth"):
            auth_cls = getattr(weaviate.auth, "AuthApiKey", None)
            if auth_cls:
                auth_credentials = auth_cls(api_key=cfg.WEAVIATE_API_KEY)

        additional_kwargs = {}
        if additional is not None:
            additional_kwargs["additional_config"] = additional

        connect_errors: list[Exception] = []

        if hasattr(weaviate, "connect_to_custom"):
            kwargs = {
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
            kwargs.update(additional_kwargs)
            try:
                return self._call_with_kwarg_fallback(weaviate.connect_to_custom, kwargs)
            except Exception as exc:  # pragma: no cover - can't easily emulate in tests
                connect_errors.append(exc)

        if hasattr(weaviate, "connect_to_local"):
            kwargs = {
                "host": host,
                "port": http_port,
                "grpc_port": grpc_port,
                "skip_init_checks": True,
            }
            if secure:
                kwargs["http_secure"] = True
                kwargs["grpc_secure"] = True
            if auth_credentials is not None:
                kwargs["auth_credentials"] = auth_credentials
            kwargs.update(additional_kwargs)
            try:
                return self._call_with_kwarg_fallback(weaviate.connect_to_local, kwargs)
            except Exception as exc:  # pragma: no cover
                connect_errors.append(exc)

        if connect_errors:
            raise RuntimeError(
                "Unable to initialise Weaviate client with the installed weaviate-client package."
            ) from connect_errors[-1]
        raise RuntimeError(
            "Installed weaviate-client package does not expose a supported connection helper."
        )

    @staticmethod
    def _call_with_kwarg_fallback(func, kwargs):
        """
        Call a weaviate helper, progressively removing unsupported keyword arguments.
        This allows compatibility across client releases with slightly different signatures.
        """
        current_kwargs = dict(kwargs)
        while True:
            try:
                return func(**current_kwargs)
            except TypeError as exc:
                match = re.search(r"unexpected keyword argument '([^']+)'", str(exc))
                if not match:
                    raise
                bad_arg = match.group(1)
                if bad_arg not in current_kwargs:
                    raise
                current_kwargs.pop(bad_arg)
                continue

    # ----- schema -----
    def _ensure_class(self, cfg: Config) -> None:
        schema = self.client.collections
        names = [c.name for c in schema.list_all()]  # type: ignore
        if self._class in names:
            return

        # You can swap the vectorizer for a local one if needed.
        vec_cfg = Configure.NamedVectors.text2vec_openai()
        coll_cfg = Configure.collection(
            vectorizer_config=vec_cfg,
            properties=[
                Property(name="external_id", dataType=DataType.TEXT, tokenization=Tokenization.WORD),
                Property(name="content", dataType=DataType.TEXT, tokenization=Tokenization.WORD),
                Property(name="structure_summary", dataType=DataType.TEXT),
                Property(name="visibility", dataType=DataType.TEXT),
                Property(name="owner_id", dataType=DataType.TEXT),
                Property(name="allowed_user_ids", dataType=DataType.TEXT_ARRAY),
                Property(name="hash", dataType=DataType.TEXT),
                Property(name="source", dataType=DataType.TEXT),
            ],
            multi_tenancy=Configure.multi_tenancy(enabled=cfg.WEAVIATE_MULTI_TENANCY),
        )
        schema.create(self._class, coll_cfg)  # type: ignore
        logger.info("Created Weaviate class '%s' (multitenant=%s)", self._class, cfg.WEAVIATE_MULTI_TENANCY)

    def _coll(self, tenant_id: Optional[str]):
        if self._mt:
            return self.client.collections.get(self._class, tenant=tenant_id)
        return self.client.collections.get(self._class)

    # ----- VectorInterface -----
    def upsert(
        self,
        key: Optional[str],
        vector: List[float],
        metadata: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> None:
        coll = self._coll(tenant_id)
        # Use a stable UUID key if possible (external_id / hash)
        obj_id = key or metadata.get("hash") or metadata.get("external_id")
        if not obj_id:
            raise ValueError("upsert requires a stable key/external_id/hash")

        props = dict(metadata)
        text = props.pop("content", None) or props.get("structure_summary") or ""
        props["external_id"] = key or metadata.get("external_id") or metadata.get("hash") or obj_id

        # Insert; if already exists, update
        # Weaviate v4 has no direct "upsert" concept; we can try update and fall back to insert on not-found.
        try:
            coll.data.update(
                uuid=str(obj_id),
                properties=props | {"content": text},
                vector=vector,  # optional: only with named vectors; else omit
            )
        except Exception:
            coll.data.insert(
                properties=props | {"content": text},
                uuid=str(obj_id),
                vector=vector,
            )

    def _build_where(self, filters: Optional[Dict[str, Any]]) -> Optional[Filter]:
        if not filters:
            return None
        shoulds: List[Filter] = []
        # always allow public
        if filters.get("visibility") == "public":
            shoulds.append(Filter.by_property("visibility").equal("public"))
        else:
            # Default OR: public OR owner OR allowed_user_ids contains user
            shoulds.append(Filter.by_property("visibility").equal("public"))

        owner = filters.get("owner_id")
        if owner:
            shoulds.append(Filter.by_property("owner_id").equal(owner))

        user = filters.get("user_id")
        if user:
            shoulds.append(Filter.by_property("allowed_user_ids").contains_any([user]))
            shoulds.append(Filter.by_property("owner_id").equal(user))

        if not shoulds:
            return None
        out = shoulds[0]
        for s in shoulds[1:]:
            out = out | s
        return out

    def search(
        self,
        vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[ScoredItem]:
        coll = self._coll(tenant_id)
        where = self._build_where(filters)
        res = coll.query.near_vector(vector=vector, limit=top_k, where=where)
        out: List[ScoredItem] = []
        for obj in getattr(res, "objects", []) or []:  # type: ignore
            meta = getattr(obj, "metadata", None)
            distance = getattr(meta, "distance", None)
            score = None if distance is None else float(distance)
            props = getattr(obj, "properties", {}) or {}
            out.append(ScoredItem(id=str(obj.uuid), score=score, payload=props))
        return out

    def iter_payloads(self, batch_size: int = 256, tenant_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        coll = self._coll(tenant_id)
        cursor = None
        while True:
            res = coll.query.fetch_objects(limit=batch_size, cursor=cursor)
            objs = getattr(res, "objects", []) or []  # type: ignore
            if not objs:
                break
            for obj in objs:
                yield getattr(obj, "properties", {}) or {}
            page = getattr(res, "page_info", None)
            cursor = getattr(page, "end_cursor", None)
            if not getattr(page, "has_next_page", False):
                break
