"""Contracts that describe backend interfaces."""

from dataclasses import dataclass
from typing import Any, Dict, Iterator, Protocol


@dataclass
class Message:
    role: str
    content: str


@dataclass
class ChatResponse:
    content: str
    model: str
    usage: Dict[str, int] | None = None
    finish_reason: str | None = None


@dataclass
class EmbeddingResult:
    embedding: list[float]
    model: str
    usage: Dict[str, int] | None = None


class LLMProvider(Protocol):
    def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        ...

    def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        ...

    def embed_query(self, text: str, model: str | None = None) -> list[float]:
        ...

    def get_dimension(self, model: str | None = None) -> int:
        ...


@dataclass
class VectorDocument:
    id: str
    content: str
    vector: list[float]
    metadata: Dict[str, Any]


@dataclass
class SearchResult:
    id: str
    content: str
    score: float
    metadata: Dict[str, Any]


class VectorStore(Protocol):
    def upsert(
        self,
        documents: list[VectorDocument],
        *,
        collection: str | None = None,
    ) -> None:
        ...

    def search(
        self,
        query_vector: list[float],
        *,
        limit: int = 10,
        collection: str | None = None,
        filters: Dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        ...

    def delete(self, ids: list[str], *, collection: str | None = None) -> None:
        ...
