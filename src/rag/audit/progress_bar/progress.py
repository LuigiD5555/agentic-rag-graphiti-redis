"""Lightweight, reusable terminal progress bar."""
from __future__ import annotations

import sys
import time
from typing import Iterable, Iterator, TextIO, TypeVar

from src.ingestion.utils.progress import progress_ratio, render_bar

T = TypeVar("T")


class ProgressBar:
    """Render a progress bar to stdout/stderr for long-running processes."""

    def __init__(
        self,
        total: int,
        length: int = 30,
        stream: TextIO = sys.stdout,
        prefix: str = "",
        suffix: str = "",
        fill_char: str = "▮",
        empty_char: str = "·",
        rewrite: bool | None = None,
        min_interval_seconds: float = 0.0,
    ) -> None:
        if total <= 0:
            raise ValueError("total must be greater than zero")
        self.total = total
        self.length = max(10, length)
        self.stream = stream
        self.prefix = prefix
        self.suffix = suffix
        self.fill_char = fill_char
        self.empty_char = empty_char
        self.current = 0
        self._finished = False
        self._last_line_length = 0
        self._min_interval_seconds = max(0.0, float(min_interval_seconds or 0.0))
        self._last_render_ts = 0.0
        # Auto-disable single-line rewrite when the stream is not a TTY (e.g., docker logs).
        self._rewrite = stream.isatty() if rewrite is None else bool(rewrite)
        self._render()

    def update(self, current: int, message: str | None = None) -> None:
        """Update the bar with an absolute position."""
        self.current = max(0, min(current, self.total))
        self._render(message)

    def advance(self, step: int = 1, message: str | None = None) -> None:
        """Advance the bar by the given step."""
        self.update(self.current + step, message)

    def track(self, iterable: Iterable[T]) -> Iterator[T]:
        """Wrap an iterable and advance the bar for each item."""
        for item in iterable:
            yield item
            self.advance()
        self.finish()

    def finish(self, message: str | None = None) -> None:
        """Mark the bar as complete and move to a new line."""
        if self._finished:
            return
        self.current = self.total
        self._render(message)
        if self._rewrite:
            print(file=self.stream, flush=True)
        self._finished = True

    def _render(self, message: str | None = None) -> None:
        now = time.monotonic()
        if not self._rewrite and self._min_interval_seconds:
            if self.current < self.total and (now - self._last_render_ts) < self._min_interval_seconds:
                return
            self._last_render_ts = now

        ratio = progress_ratio(self.current, self.total)
        bar = render_bar(
            ratio=ratio,
            length=self.length,
            fill_char=self.fill_char,
            empty_char=self.empty_char,
        )
        percent_value = ratio * 100
        percent = f"{percent_value:6.2f}%"

        parts = [self.prefix, bar, percent, f"({self.current}/{self.total})", self.suffix]
        if message:
            parts.append(message)
        line = " ".join(part for part in parts if part)
        if self._rewrite:
            padded = line.ljust(self._last_line_length)
            self._last_line_length = len(line)
            print(f"\r{padded}", end="", file=self.stream, flush=True)
        else:
            print(line, file=self.stream, flush=True)
