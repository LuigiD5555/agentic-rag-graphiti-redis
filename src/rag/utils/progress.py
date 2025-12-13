"""Lightweight, reusable terminal progress bar."""
from __future__ import annotations

import sys
from typing import Iterable, Iterator, TextIO, TypeVar

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
        print(file=self.stream, flush=True)
        self._finished = True

    def _render(self, message: str | None = None) -> None:
        ratio = self.current / self.total
        filled = int(self.length * ratio)
        bar = f"[{self.fill_char * filled}{self.empty_char * (self.length - filled)}]"
        percent = f"{ratio * 100:6.2f}%"
        parts = [self.prefix, bar, percent, f"({self.current}/{self.total})", self.suffix]
        if message:
            parts.append(message)
        line = " ".join(part for part in parts if part)
        padded = line.ljust(self._last_line_length)
        self._last_line_length = len(line)
        print(f"\r{padded}", end="", file=self.stream, flush=True)
