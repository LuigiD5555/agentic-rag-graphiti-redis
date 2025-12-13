from __future__ import annotations


def clamp_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(int(value), maximum))


def progress_ratio(current: int, total: int) -> float:
    total_int = int(total)
    if total_int <= 0:
        return 0.0
    current_int = clamp_int(int(current), minimum=0, maximum=total_int)
    return current_int / total_int


def progress_percent(current: int, total: int) -> float:
    return progress_ratio(current, total) * 100.0


def render_bar(
    *,
    ratio: float,
    length: int,
    fill_char: str = "▮",
    empty_char: str = "·",
) -> str:
    safe_length = max(1, int(length))
    safe_ratio = max(0.0, min(float(ratio), 1.0))
    filled = int(safe_length * safe_ratio)
    return f"[{fill_char * filled}{empty_char * (safe_length - filled)}]"

