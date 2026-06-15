from typing import Protocol, Optional, List


class GraphInterface(Protocol):
    """
    Interface for graph databases.
    """
    def add_entity(
        self, name: str,
        entity_type: str = "Entity",
        properties: Optional[dict] = None
    ) -> None:
        ...

    def add_relation(self, src: str, rel: str, dst: str, properties: Optional[dict] = None) -> None:
        ...

    def search(self, query: str) -> List[str]:
        ...
