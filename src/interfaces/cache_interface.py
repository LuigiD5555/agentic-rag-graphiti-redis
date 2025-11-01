from typing import Optional, Protocol


class CacheServiceProtocol(Protocol):
    """Protocol defining expected cache service behavior."""
    def get(self, key: str) -> Optional[str]:
        ...

    def set(self, key: str, value: object, ttl: int = 3600) -> None:
        ...
