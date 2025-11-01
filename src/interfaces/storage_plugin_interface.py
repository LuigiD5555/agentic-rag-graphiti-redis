from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class StoragePluginInterface(ABC):
    """
    Plugin interface for vector storages. Multiple plugins can be active at once.
    """

    @abstractmethod
    def name(self) -> str:
        """Unique plugin name."""
        raise NotImplementedError

    @abstractmethod
    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        """Ensure collection exists with correct vector size."""
        raise NotImplementedError

    @abstractmethod
    def upsert(
        self,
        collection_name: str,
        vector: List[float],
        payload: Dict[str, Any],
        doc_id: Optional[str] = None
    ) -> str:
        """Insert or update; return final id."""
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        collection_name: str,
        vector: List[float],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Return list of matches with scores and payloads."""
        raise NotImplementedError

    def close(self) -> None:
        """Optional cleanup."""
        return
