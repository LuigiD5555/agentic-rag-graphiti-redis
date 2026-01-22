"""
Result pattern implementation for consistent error handling.

This module provides a Result type similar to Rust's Result or functional programming
Either monad, but adapted for Python with domain-specific error and pressure events.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Callable

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
    REDIS = "redis"
    OFFICE = "office"
    FILESYSTEM = "filesystem"
    HTTP_PROVIDER = "http_provider"
    EMBEDDINGS = "embeddings"
    DATABASE = "database"
    LLM = "llm"
    OCR = "ocr"
    EXTRACTOR = "extractor"
    MONITORING = "monitoring"


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
    """Represents an operational error event."""
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
        return (f"{self.pressure_type.value} pressure: {self.current:.1f}/{self.threshold:.1f} "
                f"({percent:.1f}%) at {self.scope.value}.{self.stage.value}")


class Result(Generic[T, E]):
    """
    A Result type that can be either Ok (success) or Err (error).
    
    This is a simplified implementation that follows the plan's recommendation
    for zero dependencies and gradual migration.
    """
    
    def __init__(self, is_ok: bool, value: Optional[T] = None, error: Optional[E] = None, 
                 warnings: Optional[List[PressureEvent]] = None):
        self._is_ok = is_ok
        self._value = value
        self._error = error
        self._warnings = warnings or []
        
        # Validate state
        if is_ok and error is not None:
            raise ValueError("Ok result cannot have an error")
        if not is_ok and value is not None:
            raise ValueError("Err result cannot have a value")
    
    @classmethod
    def ok(cls, value: T, warnings: Optional[List[PressureEvent]] = None) -> 'Result[T, E]':
        """Create a successful result."""
        return cls(is_ok=True, value=value, warnings=warnings)
    
    @classmethod
    def err(cls, error: E, warnings: Optional[List[PressureEvent]] = None) -> 'Result[T, E]':
        """Create an error result."""
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
        return self._value
    
    @property
    def error(self) -> E:
        """Get the error value. Raises if result is success."""
        if self._is_ok:
            raise ValueError("Cannot get error from Ok result")
        return self._error
    
    @property
    def warnings(self) -> List[PressureEvent]:
        """Get pressure warnings."""
        return self._warnings.copy()
    
    def unwrap(self) -> T:
        """Get the success value or raise the error."""
        if self._is_ok:
            return self._value
        if isinstance(self._error, Exception):
            raise self._error
        raise ValueError(f"Result is Err: {self._error}")
    
    def unwrap_or(self, default: T) -> T:
        """Get the success value or return default."""
        return self._value if self._is_ok else default
    
    def unwrap_or_else(self, f: Callable[[E], T]) -> T:
        """Get the success value or compute from error."""
        return self._value if self._is_ok else f(self._error)
    
    def map(self, f: Callable[[T], Any]) -> 'Result[Any, E]':
        """Apply function to success value."""
        if self._is_ok:
            return Result.ok(f(self._value), self._warnings)
        return Result.err(self._error, self._warnings)
    
    def map_err(self, f: Callable[[E], Any]) -> 'Result[T, Any]':
        """Apply function to error value."""
        if self._is_ok:
            return Result.ok(self._value, self._warnings)
        return Result.err(f(self._error), self._warnings)
    
    def and_then(self, f: Callable[[T], 'Result[Any, E]']) -> 'Result[Any, E]':
        """Chain operations that return Results."""
        if self._is_ok:
            result = f(self._value)
            # Combine warnings
            combined_warnings = self._warnings + result.warnings
            if result.is_ok:
                return Result.ok(result.value, combined_warnings)
            return Result.err(result.error, combined_warnings)
        return Result.err(self._error, self._warnings)
    
    def or_else(self, f: Callable[[E], 'Result[T, Any]']) -> 'Result[T, Any]':
        """Handle error by trying alternative."""
        if self._is_ok:
            return Result.ok(self._value, self._warnings)
        result = f(self._error)
        # Combine warnings
        combined_warnings = self._warnings + result.warnings
        if result.is_ok:
            return Result.ok(result.value, combined_warnings)
        return Result.err(result.error, combined_warnings)
    
    def add_warning(self, warning: PressureEvent) -> 'Result[T, E]':
        """Add a pressure warning to the result."""
        new_warnings = self._warnings + [warning]
        if self._is_ok:
            return Result.ok(self._value, new_warnings)
        return Result.err(self._error, new_warnings)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization."""
        if self._is_ok:
            value_dict = self._value.to_dict() if hasattr(self._value, 'to_dict') else self._value
            return {
                "is_ok": True,
                "value": value_dict,
                "warnings": [w.to_dict() for w in self._warnings]
            }
        else:
            error_dict = self._error.to_dict() if hasattr(self._error, 'to_dict') else str(self._error)
            return {
                "is_ok": False,
                "error": error_dict,
                "warnings": [w.to_dict() for w in self._warnings]
            }
    
    def __str__(self) -> str:
        if self._is_ok:
            warnings_str = f" with {len(self._warnings)} warnings" if self._warnings else ""
            return f"Ok({self._value}){warnings_str}"
        return f"Err({self._error})"
    
    def __repr__(self) -> str:
        return str(self)


# Type aliases for common use cases
ResultT = Result[Any, ErrorEvent]
ResultAny = Result[Any, Any]
