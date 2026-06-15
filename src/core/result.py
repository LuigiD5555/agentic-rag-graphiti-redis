"""
Result pattern implementation for consistent error handling.

This module provides a Result type similar to Rust's Result or functional programming
Either monad, but adapted for Python with domain-specific error and pressure events.

Usage
-----
Simple (domain exception):
    return Result.err(ScanError("/data/docs", cause=exc))

Rich (observability event with kind/service/stage/severity):
    return Result.err(ErrorEvent(kind=ErrorKind.TIMEOUT, service=ServiceType.WEAVIATE, ...))

Both forms are valid — use the simple form inside pipeline code and the rich form
when you need circuit-breaker, retry, or policy decisions.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar, Union

T = TypeVar('T')  # Success value type
E = TypeVar('E')  # Error type


class ErrorKind(Enum):
    """Types of operational errors."""
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    VALIDATION = "validation"
    RATE_LIMIT = "rate_limit"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    DISK_FULL = "disk_full"
    OUT_OF_MEMORY = "oom"
    PERMISSION = "permission"
    UNKNOWN = "unknown"
    NETWORK = "network"
    CONFIGURATION = "configuration"
    RESOURCE_PRESSURE = "resource_pressure"


class ServiceType(Enum):
    """Service or component where error occurred."""
    WEAVIATE = "weaviate"
    OFFICE = "office"
    FILESYSTEM = "filesystem"
    HTTP_PROVIDER = "http_provider"
    EMBEDDINGS = "embeddings"
    DATABASE = "database"
    LLM = "llm"
    OCR = "ocr"
    EXTRACTOR = "extractor"
    MONITORING = "monitoring"
    GRAPH = "graph"
    CACHE = "cache"
    LEDGER = "ledger"
    SCORE_CACHE = "score_cache"
    MEMORY = "memory"
    RETRIEVER = "retriever"
    RERANKER = "reranker"


class ProcessingStage(Enum):
    """Stage in the processing pipeline."""
    SCAN = "scan"
    PREPROCESS = "preprocess"
    SPLIT = "split"
    EMBED = "embed"
    UPSERT = "upsert"
    CLEANUP = "cleanup"
    API = "api"
    DISCOVERY = "discovery"
    IDEMPOTENCY = "idempotency"
    WAVE_PLANNING = "wave_planning"
    RESOURCE_MANAGEMENT = "resource_management"
    LOAD = "load"
    CHUNK = "chunk"
    RETRIEVAL = "retrieval"
    GENERATION = "generation"
    RERANK = "rerank"
    SNAPSHOT = "snapshot"
    PERSISTENCE = "persistence"
    INITIALIZATION = "initialization"


class Severity(Enum):
    """Error severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PressureType(Enum):
    """Types of resource pressure."""
    CPU = "cpu"
    RAM = "ram"
    DISK = "disk"
    IO = "io"
    QUEUE = "queue"
    GPU = "gpu"
    NETWORK = "network"


class PressureTrend(Enum):
    """Trend of pressure metric."""
    RISING = "rising"
    STABLE = "stable"
    FALLING = "falling"


class PressureScope(Enum):
    """Scope of pressure measurement."""
    NODE = "node"
    CONTAINER = "container"
    PIPELINE = "pipeline"
    STAGE = "stage"


class ActionHint(Enum):
    """Suggested actions for pressure events."""
    THROTTLE = "throttle"
    PAUSE = "pause"
    REDUCE_BATCH = "reduce_batch"
    REDUCE_WORKERS = "reduce_workers"
    DEGRADE = "degrade"
    CLEANUP = "cleanup"
    RETRY = "retry"
    SKIP = "skip"


@dataclass
class ErrorEvent:
    """Represents an operational error event with full observability metadata.

    Use this when you need circuit-breaker, retry-policy, or severity routing.
    For simple domain errors within the pipeline, prefer raising a RagError
    subclass and wrapping it with Result.err(exc).
    """
    kind: ErrorKind
    service: ServiceType
    stage: ProcessingStage
    retryable: bool = True
    severity: Severity = Severity.MEDIUM
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message: Optional[str] = None
    original_exception: Optional[Exception] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "kind": self.kind.value,
            "service": self.service.value,
            "stage": self.stage.value,
            "retryable": self.retryable,
            "severity": self.severity.value,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
        }
        if self.original_exception:
            result["original_exception_type"] = type(self.original_exception).__name__
            result["original_exception_str"] = str(self.original_exception)
        return result

    def __str__(self) -> str:
        msg = self.message or ""
        return f"{self.kind.value} at {self.service.value}.{self.stage.value}: {msg}"


@dataclass
class PressureEvent:
    """Represents resource pressure telemetry."""
    pressure_type: PressureType
    current: float
    threshold: float
    trend: PressureTrend
    scope: PressureScope
    stage: ProcessingStage
    action_hint: ActionHint
    cooldown_s: int = 60
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "pressure_type": self.pressure_type.value,
            "current": self.current,
            "threshold": self.threshold,
            "trend": self.trend.value,
            "scope": self.scope.value,
            "stage": self.stage.value,
            "action_hint": self.action_hint.value,
            "cooldown_s": self.cooldown_s,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }

    def __str__(self) -> str:
        percent = (self.current / self.threshold * 100) if self.threshold > 0 else 0
        return (
            f"{self.pressure_type.value} pressure: {self.current:.1f}/{self.threshold:.1f} "
            f"({percent:.1f}%) at {self.scope.value}.{self.stage.value}"
        )


# Type alias for the error value accepted by Result.err().
# Accepts either a rich ErrorEvent (for observability/policy) or any Exception
# (for simple domain errors).  The union is intentionally broad so that all
# existing RagError subclasses and plain Python exceptions work without
# wrapping.
AnyError = Union[ErrorEvent, Exception]


class Result(Generic[T, E]):
    """A Result type that can be either Ok (success) or Err (error).

    The error value ``E`` defaults to ``AnyError``, which accepts both an
    ``ErrorEvent`` (rich observability) and any ``Exception`` subclass
    (simple domain error).  This allows gradual migration: pipeline internals
    use ``Result.err(ScanError(...))`` while observability-aware layers use
    ``Result.err(ErrorEvent(...))``.
    """

    def __init__(
        self,
        is_ok: bool,
        value: Optional[T] = None,
        error: Optional[E] = None,
        warnings: Optional[List[PressureEvent]] = None,
    ) -> None:
        self._is_ok = is_ok
        self._value = value
        self._error = error
        self._warnings: List[PressureEvent] = warnings or []

        if is_ok and error is not None:
            raise ValueError("Ok result cannot have an error")
        if not is_ok and value is not None:
            raise ValueError("Err result cannot have a value")

    @classmethod
    def ok(cls, value: T, warnings: Optional[List[PressureEvent]] = None) -> "Result[T, Any]":
        """Create a successful result."""
        return cls(is_ok=True, value=value, warnings=warnings)

    @classmethod
    def err(cls, error: E, warnings: Optional[List[PressureEvent]] = None) -> "Result[Any, E]":
        """Create an error result.

        ``error`` may be an ``ErrorEvent`` for rich observability or any
        ``Exception`` subclass (e.g. ``ScanError``, ``VectorStoreError``) for
        simple domain errors.
        """
        return cls(is_ok=False, error=error, warnings=warnings)

    @property
    def is_ok(self) -> bool:
        """Check if result is successful."""
        return self._is_ok

    @property
    def is_err(self) -> bool:
        """Check if result is an error."""
        return not self._is_ok

    @property
    def value(self) -> T:
        """Get the success value. Raises if result is error."""
        if not self._is_ok:
            raise ValueError("Cannot get value from Err result")
        return self._value  # type: ignore[return-value]

    @property
    def error(self) -> E:
        """Get the error value. Raises if result is success."""
        if self._is_ok:
            raise ValueError("Cannot get error from Ok result")
        return self._error  # type: ignore[return-value]

    @property
    def warnings(self) -> List[PressureEvent]:
        """Get pressure warnings (copy to prevent mutation)."""
        return list(self._warnings)

    def unwrap(self) -> T:
        """Return the success value or raise the error.

        If the error is an ``Exception`` it is raised directly.
        If it is an ``ErrorEvent`` a ``RuntimeError`` is raised with its str.
        """
        if self._is_ok:
            return self._value  # type: ignore[return-value]
        if isinstance(self._error, Exception):
            raise self._error
        raise RuntimeError(f"Result is Err: {self._error}")

    def unwrap_or(self, default: T) -> T:
        """Return the success value or ``default``."""
        return self._value if self._is_ok else default  # type: ignore[return-value]

    def unwrap_or_else(self, fallback: Callable[[E], T]) -> T:
        """Return the success value or compute it from the error."""
        return self._value if self._is_ok else fallback(self._error)  # type: ignore[arg-type]

    def map(self, transform: Callable[[T], Any]) -> "Result[Any, E]":
        """Apply ``transform`` to the success value, leaving errors unchanged."""
        if self._is_ok:
            return Result.ok(transform(self._value), self._warnings)  # type: ignore[arg-type]
        return Result.err(self._error, self._warnings)  # type: ignore[arg-type]

    def map_err(self, transform: Callable[[E], Any]) -> "Result[T, Any]":
        """Apply ``transform`` to the error value, leaving successes unchanged."""
        if self._is_ok:
            return Result.ok(self._value, self._warnings)  # type: ignore[arg-type]
        return Result.err(transform(self._error), self._warnings)  # type: ignore[arg-type]

    def and_then(self, next_step: Callable[[T], "Result[Any, E]"]) -> "Result[Any, E]":
        """Chain a function that returns a Result (railway-oriented programming)."""
        if self._is_ok:
            chained = next_step(self._value)  # type: ignore[arg-type]
            combined_warnings = self._warnings + chained.warnings
            if chained.is_ok:
                return Result.ok(chained.value, combined_warnings)
            return Result.err(chained.error, combined_warnings)
        return Result.err(self._error, self._warnings)  # type: ignore[arg-type]

    def or_else(self, recover: Callable[[E], "Result[T, Any]"]) -> "Result[T, Any]":
        """Handle an error by trying an alternative Result-returning function."""
        if self._is_ok:
            return Result.ok(self._value, self._warnings)  # type: ignore[arg-type]
        recovered = recover(self._error)  # type: ignore[arg-type]
        combined_warnings = self._warnings + recovered.warnings
        if recovered.is_ok:
            return Result.ok(recovered.value, combined_warnings)
        return Result.err(recovered.error, combined_warnings)

    def add_warning(self, warning: PressureEvent) -> "Result[T, E]":
        """Return a new Result with an additional pressure warning attached."""
        new_warnings = self._warnings + [warning]
        if self._is_ok:
            return Result.ok(self._value, new_warnings)  # type: ignore[arg-type]
        return Result.err(self._error, new_warnings)  # type: ignore[arg-type]

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization."""
        if self._is_ok:
            value_repr = self._value.to_dict() if hasattr(self._value, 'to_dict') else self._value
            return {
                "is_ok": True,
                "value": value_repr,
                "warnings": [w.to_dict() for w in self._warnings],
            }
        error_repr: Any
        if hasattr(self._error, 'to_dict'):
            error_repr = self._error.to_dict()  # type: ignore[union-attr]
        elif isinstance(self._error, Exception):
            error_repr = {
                "type": type(self._error).__name__,
                "message": str(self._error),
            }
        else:
            error_repr = str(self._error)
        return {
            "is_ok": False,
            "error": error_repr,
            "warnings": [w.to_dict() for w in self._warnings],
        }

    def __str__(self) -> str:
        if self._is_ok:
            warnings_str = f" with {len(self._warnings)} warnings" if self._warnings else ""
            return f"Ok({self._value}){warnings_str}"
        return f"Err({self._error})"

    def __repr__(self) -> str:
        return str(self)


# ---------------------------------------------------------------------------
# Convenience type aliases
# ---------------------------------------------------------------------------

# Result carrying any value with a rich ErrorEvent (observability path).
ResultT = Result[Any, ErrorEvent]

# Result carrying any value with any error type (general use).
ResultAny = Result[Any, Any]
