from dataclasses import dataclass
from typing import Protocol, List, Any, Dict, Iterator, Optional, runtime_checkable


@dataclass
class ScoredItem:
    """
    Minimal, backend-agnostic search hit.
    """
    id: Optional[str]
    score: Optional[float]
    payload: Dict[str, Any]


class VectorInterface(Protocol):
    """
    Interface for vector databases (single-item upsert; implementations may batch internally).
    """

    def upsert(
        self,
        key: Optional[str],
        vector: List[float],
        metadata: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> None:
        """
        Insert or update a single vector record.
        - key: stable identifier (hash/external_id). Implementations may enforce UUIDs internally.
        - vector: embedding vector.
        - metadata: arbitrary payload (e.g., content, visibility, owner_id, allowed_user_ids).
        - tenant_id: optional tenant/namespace.
        """

    def search(
        self,
        vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[ScoredItem]:
        """
        Perform a similarity search. Implementations will translate 'filters' to their native query.
        """

    def iter_payloads(self, batch_size: int = 256, tenant_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        """
        Iterate stored payloads in batches, backend-agnostic.
        """


@runtime_checkable
class SupportsExists(Protocol):
    """Optional protocol for vector repositories that support checking if a point exists."""
    def exists(self, point_id: str, tenant_id: Optional[str] = None) -> bool:
        ...
