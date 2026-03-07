"""Shared request gate for LM Studio HTTP calls.

Serializing requests avoids model-switch contention when ingestion embeddings
and chat generation hit the same LM Studio instance at the same time.
"""

import threading


LMSTUDIO_REQUEST_GATE = threading.RLock()

