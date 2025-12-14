"""Null object implementation for GraphInterface."""
from typing import Optional, List


class NullGraphRepository:
    """GraphInterface no-op implementation when graph features are disabled."""

    def add_entity(
        self,
        name: str,
        entity_type: str = "Entity",
        properties: Optional[dict] = None,
    ) -> None:
        return None

    def add_relation(
        self,
        src: str,
        rel: str,
        dst: str,
        properties: Optional[dict] = None,
    ) -> None:
        return None

    def search(self, query: str) -> List[str]:
        return []
