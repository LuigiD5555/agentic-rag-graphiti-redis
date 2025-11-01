from typing import Protocol, List


class EmbeddingInterface(Protocol):
    """
    Interface for embedding generation backends.
    """
    def generate(self, text: str) -> List[float]:
        ...
