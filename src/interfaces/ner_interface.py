from typing import Protocol, Optional, Dict, Any


class NERRepository(Protocol):
    """
    Abstraction for storing NER outputs (entities and relations)
    regardless of the underlying technology (graph DB, SQL, NoSQL).
    """
    def add_entity(self, name: str, entity_type: str = "Entity", properties: Optional[Dict[str, Any]] = None) -> None:
        ...

    def add_relation(self, src: str, rel: str, dst: str, properties: Optional[Dict[str, Any]] = None) -> None:
        ...
