from __future__ import annotations

from typing import Any

from src.settings import Config
from src.rag.interfaces.storage_plugin_interface import StoragePluginInterface
from src.rag.interfaces.vector_interface import VectorInterface
from .repository import WeaviateRepository


class WeaviateVectorPlugin(StoragePluginInterface):
    """
    Storage plugin that wraps WeaviateRepository and exposes it as a vector backend.

    This allows configuring the engine via a dotted path.
    """

    def __init__(self, config: Config | None = None, **_: Any) -> None:
        # Allow passing a Config instance explicitly, or construct a default one.
        self._config = config or Config()
        self._repo: VectorInterface = WeaviateRepository(self._config)

    def get_client(self) -> VectorInterface:
        """
        Return the underlying VectorInterface implementation.

        This expose a connection/wrapper, while keeping callers decoupled from the
        concrete repository class.
        """
        return self._repo

    # The original interface was vector-collection centric; for this plugin
    # we delegate to the underlying repository which already manages collections
    # based on Config (WEAVIATE_CLASS, etc.).

    def name(self) -> str:
        return "weaviate"

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:  # type: ignore[override]
        # WeaviateRepository/SchemaManager already ensure the main class exists on init.
        # 'collection_name' and 'vector_size' are not used here, but the method
        # is kept for compatibility with the base interface.
        _ = (collection_name, vector_size)
        return

    def upsert(  # type: ignore[override]
        self,
        collection_name: str,
        vector: list[float],
        payload: dict[str, Any],
        doc_id: str | None = None,
    ) -> str:
        _ = collection_name  # current WeaviateRepository uses a single collection from config
        self._repo.upsert(key=doc_id, vector=vector, metadata=payload)
        # WeaviateRepository normalizes UUIDs internally; we don't have a direct id here,
        # so we fall back to hash/external_id in payload if present.
        return doc_id or str(payload.get("hash") or payload.get("external_id") or "")

    def search(  # type: ignore[override]
        self,
        collection_name: str,
        vector: list[float],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        _ = collection_name
        results = self._repo.search(vector=vector, top_k=top_k)
        out: list[dict[str, Any]] = []
        for hit in results or []:
            out.append(
                {
                    "id": hit.id,
                    "score": hit.score,
                    "payload": hit.payload,
                }
            )
        return out

    def close(self) -> None:  # type: ignore[override]
        # Weaviate client does not require explicit close in this context.
        return
