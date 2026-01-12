"""Helpers to track global embedding progress and format log lines."""

from dataclasses import dataclass, field
from math import ceil
from typing import Dict

from src.utils.progress import progress_ratio, render_bar


@dataclass
class EmbeddingProgress:
    """Track global embedding progress and format log lines with a bar.

    The class maintains:
    - an estimated total (based on file sizes) for files not yet split
    - an actual total chunk count for files already split
    - a done counter incremented on each successful upsert

    This is designed for log-friendly output (Docker/Podman), not TTY-only UIs.
    """

    bar_length: int = 25
    fill_char: str = "#"
    empty_char: str = "."
    chunk_tokens: int = 500

    total_estimated: int = 0
    total_actual: int = 0
    done: int = 0
    _file_estimates: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Reset all counters for a new run."""
        self.total_estimated = 0
        self.total_actual = 0
        self.done = 0
        self._file_estimates = {}

    def set_chunk_tokens(self, chunk_tokens: int) -> None:
        """Set the chunk token size used for rough per-file estimates."""
        if chunk_tokens <= 0:
            raise ValueError("chunk_tokens must be a positive integer")
        self.chunk_tokens = int(chunk_tokens)

    def get_file_estimate(self, source: str) -> int | None:
        """Return the current estimated embeddings for a file source, if known."""
        if not source:
            return None
        return self._file_estimates.get(source)

    def _set_file_estimate(self, source: str, estimate: int) -> None:
        """Set/replace an estimate for a given source and update totals."""
        if not source:
            raise ValueError("source must be a non-empty string")
        estimate = max(1, int(estimate))
        previous = self._file_estimates.get(source)
        if previous is not None:
            self.total_estimated -= previous
        self._file_estimates[source] = estimate
        self.total_estimated += estimate

    def register_file(self, source: str, file_size_bytes: int | None) -> None:
        """Register a file and attach a rough estimate based on file size."""
        if not source:
            raise ValueError("source must be a non-empty string")
        estimate = self.estimate_embeddings(file_size_bytes, chunk_tokens=self.chunk_tokens)
        self._set_file_estimate(source, estimate)

    def add_total(self, count: int, *, source: str) -> None:
        """Add an actual chunk count and drop any estimate for the source."""
        if not source:
            raise ValueError("source must be a non-empty string")
        count = max(0, int(count))

        previous = self._file_estimates.pop(source, None)
        if previous is not None:
            self.total_estimated -= previous

        if count > 0:
            self.total_actual += count

    def estimate_embeddings(self, file_size_bytes: int | None, *, chunk_tokens: int) -> int:
        """Estimate how many embeddings a file will require based on file size.

        Assumes ~4 bytes per token and at least one embedding per file.
        """
        if chunk_tokens <= 0:
            raise ValueError("chunk_tokens must be a positive integer")
        if not file_size_bytes or file_size_bytes <= 0:
            return 1

        tokens_per_chunk = int(chunk_tokens)
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
        """Advance global progress by one and return a formatted log line."""
        if file_index <= 0:
            raise ValueError("file_index must be a positive integer")
        if file_total <= 0:
            raise ValueError("file_total must be a positive integer")

        self.done += 1
        embedding_total = self._overall_total()
        embedding_ratio = progress_ratio(self.done, embedding_total)
        bar = render_bar(
            ratio=embedding_ratio,
            length=self.bar_length,
            fill_char=self.fill_char,
            empty_char=self.empty_char,
        )

        pct_ratio = progress_ratio(file_index, file_total)
        overall_pct = pct_ratio * 100.0

        url = base_url.rstrip("/") if base_url else "/v1/objects"
        return (
            f"({self.done}/{embedding_total}) {bar} HTTP Request: POST {url}"
            f' "HTTP/1.1 200 OK" - {overall_pct:.2f}% - {source}'
        )


__all__ = ["EmbeddingProgress"]
