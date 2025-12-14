"""Helpers to track global embedding progress and format log lines."""
from dataclasses import dataclass, field
from math import ceil
from typing import Dict

from src.ingestion.utils.progress import progress_ratio, render_bar


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

    def advance(
        self,
        *,
        file_index: int,
        file_total: int,
        source: str,
        base_url: str,
    ) -> str:
        # (x/y) + bar: embedding progress
        self.done += 1
        embedding_total = self._overall_total()
        embedding_ratio = progress_ratio(self.done, embedding_total)
        bar = render_bar(
            ratio=embedding_ratio,
            length=self.bar_length,
            fill_char=self.fill_char,
            empty_char=self.empty_char,
        )

        # Percent: file progress (preferred when available)
        if file_total and file_total > 0:
            pct_ratio = progress_ratio(file_index, file_total)
            overall_pct = pct_ratio * 100.0
        else:
            overall_pct = embedding_ratio * 100.0

        url = base_url.rstrip("/") if base_url else "/v1/objects"
        return (
            f"({self.done}/{embedding_total}) {bar} HTTP Request: POST {url}"
            f' "HTTP/1.1 200 OK" - {overall_pct:.2f}% - {source}'
        )


__all__ = ["EmbeddingProgress"]
