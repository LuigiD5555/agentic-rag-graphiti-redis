import json
import os
import time
from typing import Any, Dict

LOG_PATH = os.environ.get("RAG_AUDIT_LOG", "/mnt/data/rag_audit.log")


def audit(event: str, details: Dict[str, Any]) -> None:
    """Append a JSONL audit record to the audit log file."""
    rec = {"ts": time.time(), "event": event, **details}
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
