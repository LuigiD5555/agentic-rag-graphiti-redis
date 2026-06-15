"""Shared workflow context for passing data across steps."""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class WorkflowContext:
    data: Dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    thread_id: str | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def has(self, key: str) -> bool:
        return key in self.data

    def require(self, key: str) -> Any:
        if key not in self.data:
            raise KeyError(
                f"Missing required context key '{key}'. Available: {list(self.data.keys())}"
            )
        return self.data[key]
