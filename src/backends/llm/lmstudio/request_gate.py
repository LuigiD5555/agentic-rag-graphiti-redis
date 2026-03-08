"""Shared request gate for LM Studio HTTP calls.

Bounded concurrency avoids model-switch contention while still allowing
parallel work (for example, embedding + chat) on LM Studio.
"""

import os
import threading


def _max_concurrent_requests() -> int:
    raw = (os.getenv("LMSTUDIO_MAX_CONCURRENT_REQUESTS", "2") or "2").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


LMSTUDIO_REQUEST_GATE = threading.BoundedSemaphore(_max_concurrent_requests())
