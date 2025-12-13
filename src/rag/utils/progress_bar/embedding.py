"""Helpers to track global embedding progress and format log lines."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Dict


@dataclass
class EmbeddingProgress:
    """Track global embedding progress and format log lines with a bar."""

    bar_length: int = 25
    fill_char: str = "▮"
    empty_char: str = "·"
    chunk_tokens: int = 500

    total_estimated: int = 0
    total_actual: int = 0
    done: int = 0
    _file_estimates: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.total_estimated = 0
        self.total_actual = 0
        self.done = 0
        self._file_estimates = {}

    def set_chunk_tokens(self, chunk_tokens: int | None) -> None:
        if chunk_tokens and chunk_tokens > 0:
            self.chunk_tokens = int(chunk_tokens)

    def add_estimate(self, source: str, estimate: int) -> None:
        if not source:
            return
        estimate = max(1, estimate)
        previous = self._file_estimates.get(source)
        if previous:
            self.total_estimated -= previous
        self._file_estimates[source] = estimate
        self.total_estimated += estimate

    def add_total(self, count: int, *, source: str | None = None) -> None:
        count = max(0, count)
        if source:
            previous = self._file_estimates.pop(source, None)
            if previous:
                self.total_estimated -= previous
        if count > 0:
            self.total_actual += count

    def set_total(self, count: int) -> None:
        """Retained for backwards compatibility; prefer add_total."""
        if count > 0:
            self.total_actual = count

    def register_file(self, source: str, file_size_bytes: int | None) -> None:
        if not source:
            return
        estimate = self.estimate_embeddings(file_size_bytes)
        self.add_estimate(source, estimate)

    def estimate_embeddings(self, file_size_bytes: int | None, *, chunk_tokens: int | None = None) -> int:
        """
        Roughly estimate how many embeddings a file will require based on size.

        Assumes ~4 bytes per token and at least one embedding per file.
        """
        if not file_size_bytes or file_size_bytes <= 0:
            return 1
        tokens_per_chunk = max(1, int(chunk_tokens or self.chunk_tokens or 500))
        estimated_tokens = max(1, int(file_size_bytes / 4))
        return max(1, ceil(estimated_tokens / tokens_per_chunk))

    def _overall_total(self) -> int:
        total = self.total_actual + self.total_estimated
        return total or max(self.done, 1)

    def _bar(self, pct: float) -> str:
        filled = int(self.bar_length * (pct / 100.0))
        return f"[{self.fill_char * filled}{self.empty_char * (self.bar_length - filled)}]"

    def advance(
        self,
        *,
        file_index: int,
        file_total: int,
        source: str,
        base_url: str,
    ) -> str:
        self.done += 1
        overall_total = self._overall_total()
        overall_pct = (self.done / overall_total) * 100
        bar = self._bar(overall_pct)
        url = base_url.rstrip("/") if base_url else "/v1/objects"
        return (
            f"({self.done}/{overall_total}) {bar} HTTP Request: POST {url}"
            f' "HTTP/1.1 200 OK" - {overall_pct:.2f}% - {source}'
        )


__all__ = ["EmbeddingProgress"]
