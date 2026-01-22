"""
Error Policy Strategy for deciding actions based on error events.

This module implements the Strategy pattern for deciding what action to take
when an error or pressure event occurs.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from .result import (
    Result, ErrorEvent, PressureEvent, ErrorKind, ServiceType, 
    ProcessingStage, Severity, ActionHint
)


class PolicyAction(Enum):
    """Actions that can be decided by the policy."""
    RETRY = "retry"
    SKIP = "skip"
    ABORT = "abort"
    THROTTLE = "throttle"
    PAUSE = "pause"
    DEGRADE = "degrade"
    OPEN_CIRCUIT = "open_circuit"
    CONTINUE = "continue"


@dataclass
class PolicyDecision:
    """Decision made by the error policy."""
    action: PolicyAction
    reason: str
    metadata: Dict[str, Any]
    cooldown_seconds: float = 0.0
    backoff_seconds: float = 0.0
    circuit_state: Optional[str] = None  # "open", "half-open", "closed"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "action": self.action.value,
            "reason": self.reason,
            "metadata": self.metadata,
            "cooldown_seconds": self.cooldown_seconds,
            "backoff_seconds": self.backoff_seconds,
            "circuit_state": self.circuit_state,
            "timestamp": time.time(),
        }


class CircuitBreaker:
    """Circuit breaker pattern implementation."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        half_open_max_attempts: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_max_attempts = half_open_max_attempts
        
        self.state = "closed"  # "closed", "open", "half-open"
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.half_open_attempts = 0
    
    def record_success(self) -> None:
        """Record a successful operation."""
        if self.state == "half-open":
            # Success in half-open state closes the circuit
            self.state = "closed"
            self.failure_count = 0
            self.half_open_attempts = 0
        elif self.state == "closed":
            # Reset failure count on success
            self.failure_count = max(0, self.failure_count - 1)
    
    def record_failure(self) -> None:
        """Record a failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == "closed" and self.failure_count >= self.failure_threshold:
            # Too many failures, open the circuit
            self.state = "open"
        elif self.state == "half-open":
            # Failure in half-open state re-opens the circuit
            self.state = "open"
            self.half_open_attempts += 1
    
    def should_allow(self) -> Tuple[bool, Optional[str]]:
        """Check if the circuit allows an operation."""
        current_time = time.time()
        
        if self.state == "open":
            # Check if reset timeout has passed
            if current_time - self.last_failure_time >= self.reset_timeout:
                # Move to half-open state
                self.state = "half-open"
                return True, "half_open"
            return False, "circuit_open"
        
        elif self.state == "half-open":
            # Allow limited attempts in half-open state
            if self.half_open_attempts < self.half_open_max_attempts:
                return True, "half_open"
            return False, "half_open_max_attempts_exceeded"
        
        # Closed state allows all operations
        return True, None
    
    def get_state(self) -> Dict[str, Any]:
        """Get current circuit state."""
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "half_open_attempts": self.half_open_attempts,
            "failure_threshold": self.failure_threshold,
            "reset_timeout": self.reset_timeout,
        }


class BaseErrorPolicy(ABC):
    """Base class for error policies (Strategy pattern)."""
    
    @abstractmethod
    def decide(
        self,
        result: Result[Any, ErrorEvent],
        context: Dict[str, Any]
    ) -> PolicyDecision:
        """Make a decision based on the error result and context."""
        pass


class DefaultErrorPolicy(BaseErrorPolicy):
    """Default error policy with sensible defaults."""
    
    def __init__(self):
        # Circuit breakers by service
        self.circuit_breakers: Dict[str, CircuitBreaker] = defaultdict(
            lambda: CircuitBreaker()
        )
        
        # Service-specific configurations
        self.service_configs = {
            ServiceType.WEAVIATE: {
                "retryable_errors": {
                    ErrorKind.TIMEOUT: True,
                    ErrorKind.RATE_LIMIT: True,
                    ErrorKind.UPSTREAM_UNAVAILABLE: True,
                    ErrorKind.NETWORK: True,
                },
                "backoff_base": 2.0,
                "max_retries": 3,
            },
            ServiceType.REDIS: {
                "retryable_errors": {
                    ErrorKind.TIMEOUT: True,
                    ErrorKind.RATE_LIMIT: True,
                    ErrorKind.UPSTREAM_UNAVAILABLE: True,
                    ErrorKind.NETWORK: True,
                },
                "backoff_base": 1.5,
                "max_retries": 5,
            },
            ServiceType.HTTP_PROVIDER: {
                "retryable_errors": {
                    ErrorKind.TIMEOUT: True,
                    ErrorKind.RATE_LIMIT: True,
                    ErrorKind.UPSTREAM_UNAVAILABLE: True,
                    ErrorKind.NETWORK: True,
                },
                "backoff_base": 2.0,
                "max_retries": 3,
            },
            ServiceType.FILESYSTEM: {
                "retryable_errors": {
                    ErrorKind.PERMISSION: False,  # Cannot retry permission errors
                    ErrorKind.NOT_FOUND: False,   # Cannot retry missing files
                    ErrorKind.DISK_FULL: False,   # Need cleanup first
                },
                "backoff_base": 1.0,
                "max_retries": 1,
            },
        }
        
        # Stage-specific configurations
        self.stage_configs = {
            ProcessingStage.DISCOVERY: {
                "critical": False,  # Discovery failures are usually not critical
                "can_skip": True,
            },
            ProcessingStage.PREPROCESS: {
                "critical": False,
                "can_skip": True,
            },
            ProcessingStage.EMBED: {
                "critical": True,  # Embedding failures may be critical
                "can_skip": False,
            },
            ProcessingStage.UPSERT: {
                "critical": True,
                "can_skip": False,
            },
        }
        
        # Metrics
        self.decision_count = 0
        self.retry_count = 0
        self.skip_count = 0
        self.abort_count = 0
    
    def decide(
        self,
        result: Result[Any, ErrorEvent],
        context: Dict[str, Any]
    ) -> PolicyDecision:
        """Make a decision based on the error result and context."""
        self.decision_count += 1
        
        if result.is_ok:
            # Successful result with possible warnings
            return self._handle_ok_result(result, context)
        else:
            # Error result
            return self._handle_error_result(result, context)
    
    def _handle_ok_result(
        self,
        result: Result[Any, ErrorEvent],
        context: Dict[str, Any]
    ) -> PolicyDecision:
        """Handle successful results (check for pressure warnings)."""
        # Check for pressure warnings
        pressure_actions = []
        for warning in result.warnings:
            if isinstance(warning, PressureEvent):
                action = self._pressure_to_action(warning)
                pressure_actions.append(action)
        
        # If there are pressure warnings, use the most severe one
        if pressure_actions:
            # Find the most severe action
            action_priority = {
                PolicyAction.PAUSE: 5,
                PolicyAction.THROTTLE: 4,
                PolicyAction.DEGRADE: 3,
                PolicyAction.RETRY: 2,
                PolicyAction.CONTINUE: 1,
            }
            
            most_severe = max(
                pressure_actions,
                key=lambda a: action_priority.get(a.action, 0)
            )
            
            # Update circuit breaker on success
            service = context.get('service')
            if service and isinstance(service, ServiceType):
                circuit = self.circuit_breakers[service.value]
                circuit.record_success()
            
            return most_severe
        
        # No pressure warnings, continue normally
        return PolicyDecision(
            action=PolicyAction.CONTINUE,
            reason="successful_operation",
            metadata={"warnings_count": len(result.warnings)},
        )
    
    def _handle_error_result(
        self,
        result: Result[Any, ErrorEvent],
        context: Dict[str, Any]
    ) -> PolicyDecision:
        """Handle error results."""
        error = result.error
        service = error.service
        stage = error.stage
        
        # Check circuit breaker
        circuit = self.circuit_breakers[service.value]
        allowed, circuit_reason = circuit.should_allow()
        
        if not allowed:
            # Circuit is open, don't allow the operation
            circuit.record_failure()
            return PolicyDecision(
                action=PolicyAction.OPEN_CIRCUIT,
                reason=f"circuit_open_{circuit_reason}",
                metadata={
                    "service": service.value,
                    "circuit_state": circuit.get_state(),
                    "error_kind": error.kind.value,
                },
                cooldown_seconds=circuit.reset_timeout,
                circuit_state="open",
            )
        
        # Get service and stage configurations
        service_config = self.service_configs.get(service, {})
        stage_config = self.stage_configs.get(stage, {})
        
        # Check if error is retryable
        retryable_errors = service_config.get("retryable_errors", {})
        is_retryable = error.retryable and retryable_errors.get(error.kind, True)
        
        # Check if stage allows skipping
        can_skip = stage_config.get("can_skip", False)
        is_critical = stage_config.get("critical", True)
        
        # Determine action based on error characteristics
        if error.kind == ErrorKind.DISK_FULL:
            # Disk full requires cleanup, not retry
            self.abort_count += 1
            return PolicyDecision(
                action=PolicyAction.ABORT,
                reason="disk_full_requires_cleanup",
                metadata={
                    "service": service.value,
                    "stage": stage.value,
                    "error_kind": error.kind.value,
                    "severity": error.severity.value,
                },
                cooldown_seconds=300.0,  # 5 minutes for cleanup
            )
        
        elif error.kind == ErrorKind.OUT_OF_MEMORY:
            # Memory pressure requires throttling
            self.retry_count += 1
            return PolicyDecision(
                action=PolicyAction.THROTTLE,
                reason="memory_pressure",
                metadata={
                    "service": service.value,
                    "stage": stage.value,
                    "error_kind": error.kind.value,
                },
                cooldown_seconds=120.0,  # 2 minutes
                backoff_seconds=30.0,
            )
        
        elif error.severity == Severity.CRITICAL and is_critical:
            # Critical errors in critical stages should abort
            self.abort_count += 1
            circuit.record_failure()
            return PolicyDecision(
                action=PolicyAction.ABORT,
                reason="critical_error",
                metadata={
                    "service": service.value,
                    "stage": stage.value,
                    "error_kind": error.kind.value,
                    "severity": error.severity.value,
                },
            )
        
        elif is_retryable:
            # Retryable error
            self.retry_count += 1
            
            # Calculate backoff with jitter
            backoff_base = service_config.get("backoff_base", 2.0)
            attempt = context.get('attempt', 0)
            max_retries = service_config.get("max_retries", 3)
            
            if attempt >= max_retries:
                # Too many retries
                circuit.record_failure()
                if can_skip:
                    self.skip_count += 1
                    return PolicyDecision(
                        action=PolicyAction.SKIP,
                        reason="max_retries_exceeded_can_skip",
                        metadata={
                            "service": service.value,
                            "stage": stage.value,
                            "error_kind": error.kind.value,
                            "attempt": attempt,
                            "max_retries": max_retries,
                        },
                    )
                else:
                    self.abort_count += 1
                    return PolicyDecision(
                        action=PolicyAction.ABORT,
                        reason="max_retries_exceeded_cannot_skip",
                        metadata={
                            "service": service.value,
                            "stage": stage.value,
                            "error_kind": error.kind.value,
                            "attempt": attempt,
                            "max_retries": max_retries,
                        },
                    )
            
            # Calculate exponential backoff with jitter
            backoff = min(backoff_base ** attempt, 60.0)  # Cap at 60 seconds
            jitter = backoff * 0.1  # 10% jitter
            
            circuit.record_failure()  # Record failure for circuit breaker
            
            return PolicyDecision(
                action=PolicyAction.RETRY,
                reason="retryable_error",
                metadata={
                    "service": service.value,
                    "stage": stage.value,
                    "error_kind": error.kind.value,
                    "attempt": attempt,
                    "max_retries": max_retries,
                    "retryable": True,
                },
                backoff_seconds=backoff + jitter,
            )
        
        elif can_skip:
            # Non-retryable but skippable error
            self.skip_count += 1
            return PolicyDecision(
                action=PolicyAction.SKIP,
                reason="non_retryable_but_skippable",
                metadata={
                    "service": service.value,
                    "stage": stage.value,
                    "error_kind": error.kind.value,
                    "retryable": False,
                    "can_skip": True,
                },
            )
        
        else:
            # Non-retryable, non-skippable error
            self.abort_count += 1
            circuit.record_failure()
            return PolicyDecision(
                action=PolicyAction.ABORT,
                reason="non_retryable_non_skippable",
                metadata={
                    "service": service.value,
                    "stage": stage.value,
                    "error_kind": error.kind.value,
                    "retryable": False,
                    "can_skip": False,
                },
            )
    
    def _pressure_to_action(self, pressure: PressureEvent) -> PolicyDecision:
        """Convert pressure event to policy action."""
        # Map action hints to policy actions
        hint_to_action = {
            ActionHint.THROTTLE: PolicyAction.THROTTLE,
            ActionHint.PAUSE: PolicyAction.PAUSE,
            ActionHint.REDUCE_BATCH: PolicyAction.DEGRADE,
            ActionHint.REDUCE_WORKERS: PolicyAction.DEGRADE,
            ActionHint.DEGRADE: PolicyAction.DEGRADE,
            ActionHint.CLEANUP: PolicyAction.PAUSE,  # Pause for cleanup
            ActionHint.RETRY: PolicyAction.RETRY,
            ActionHint.SKIP: PolicyAction.SKIP,
        }
        
        action = hint_to_action.get(
            pressure.action_hint,
            PolicyAction.THROTTLE  # Default
        )
        
        return PolicyDecision(
            action=action,
            reason=f"pressure_{pressure.pressure_type.value}",
            metadata=pressure.to_dict(),
            cooldown_seconds=pressure.cooldown_s,
        )
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get policy metrics."""
        circuit_states = {}
        for service, circuit in self.circuit_breakers.items():
            circuit_states[service] = circuit.get_state()
        
        return {
            "decision_count": self.decision_count,
            "retry_count": self.retry_count,
            "skip_count": self.skip_count,
            "abort_count": self.abort_count,
            "circuit_states": circuit_states,
        }


# Global default policy
_default_policy: Optional[DefaultErrorPolicy] = None


def get_default_policy() -> DefaultErrorPolicy:
    """Get the global default error policy."""
    global _default_policy
    if _default_policy is None:
        _default_policy = DefaultErrorPolicy()
    return _default_policy


def set_default_policy(policy: DefaultErrorPolicy) -> None:
    """Set the global default error policy."""
    global _default_policy
    _default_policy = policy


# Convenience function
def decide_action(
    result: Result[Any, ErrorEvent],
    context: Dict[str, Any]
) -> PolicyDecision:
    """Make a decision using the default policy."""
    return get_default_policy().decide(result, context)
