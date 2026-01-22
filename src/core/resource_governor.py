"""
Resource Governor for implementing policy decisions.

This module provides a control loop that applies policy decisions to adjust
system behavior based on errors and pressure events.
"""

import time
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from collections import deque

from .result import Result, ErrorEvent, PressureEvent, ProcessingStage, ActionHint
from .policy import PolicyDecision, PolicyAction, get_default_policy


class GovernorState(Enum):
    """State of the resource governor."""
    NORMAL = "normal"
    THROTTLED = "throttled"
    PAUSED = "paused"
    DEGRADED = "degraded"
    RECOVERING = "recovering"


@dataclass
class ResourceAdjustment:
    """Resource adjustment to apply."""
    workers: Optional[int] = None
    batch_size: Optional[int] = None
    wave_size: Optional[int] = None
    cooldown_until: Optional[float] = None
    disabled_components: Optional[Set[str]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {}
        if self.workers is not None:
            result['workers'] = self.workers
        if self.batch_size is not None:
            result['batch_size'] = self.batch_size
        if self.wave_size is not None:
            result['wave_size'] = self.wave_size
        if self.cooldown_until is not None:
            result['cooldown_until'] = self.cooldown_until
        if self.disabled_components is not None:
            result['disabled_components'] = list(self.disabled_components)
        return result


class ResourceGovernor:
    """
    Resource governor that applies policy decisions to adjust system behavior.
    
    This implements a control loop that:
    1. Receives policy decisions
    2. Applies adjustments to resource pools, wave planner, etc.
    3. Maintains cooldown periods to prevent oscillation
    4. Provides hysteresis for stable operation
    """
    
    def __init__(
        self,
        policy=None,
        hysteresis_factor: float = 0.2,
        min_cooldown_seconds: float = 30.0,
        max_cooldown_seconds: float = 300.0
    ):
        """
        Initialize the resource governor.
        
        Args:
            policy: Error policy to use (uses default if None)
            hysteresis_factor: Hysteresis factor to prevent oscillation (0.0-1.0)
            min_cooldown_seconds: Minimum cooldown time
            max_cooldown_seconds: Maximum cooldown time
        """
        self.policy = policy or get_default_policy()
        self.hysteresis_factor = hysteresis_factor
        self.min_cooldown = min_cooldown_seconds
        self.max_cooldown = max_cooldown_seconds
        
        # Current state
        self.state = GovernorState.NORMAL
        self.current_adjustment = ResourceAdjustment()
        self.cooldown_until = 0.0
        self.last_decision_time = 0.0
        
        # History for hysteresis
        self.decision_history = deque(maxlen=10)
        self.adjustment_history = deque(maxlen=5)
        
        # Connected components
        self.resource_pools = None
        self.wave_planner = None
        self.watermark_cleanup = None
        
        # Metrics
        self.decision_count = 0
        self.adjustment_count = 0
        self.recovery_count = 0
        
        # Thread safety
        self._lock = threading.Lock()
    
    def connect_resource_pools(self, resource_pools) -> None:
        """Connect resource pools component."""
        self.resource_pools = resource_pools
    
    def connect_wave_planner(self, wave_planner) -> None:
        """Connect wave planner component."""
        self.wave_planner = wave_planner
    
    def connect_watermark_cleanup(self, watermark_cleanup) -> None:
        """Connect watermark cleanup component."""
        self.watermark_cleanup = watermark_cleanup
    
    def process_result(
        self,
        result: Result[Any, ErrorEvent],
        context: Dict[str, Any]
    ) -> PolicyDecision:
        """
        Process a result and apply policy decisions.
        
        This is the main entry point for the control loop.
        
        Args:
            result: Result to process
            context: Context for decision making
            
        Returns:
            Policy decision that was made
        """
        with self._lock:
            self.decision_count += 1
            
            # Check if we're in cooldown
            current_time = time.time()
            if current_time < self.cooldown_until:
                # Still in cooldown, return current state
                return PolicyDecision(
                    action=PolicyAction.CONTINUE,
                    reason="cooldown_active",
                    metadata={
                        "cooldown_remaining": self.cooldown_until - current_time,
                        "current_state": self.state.value,
                    },
                    cooldown_seconds=self.cooldown_until - current_time,
                )
            
            # Get policy decision
            decision = self.policy.decide(result, context)
            self.last_decision_time = current_time
            
            # Store in history
            self.decision_history.append({
                "timestamp": current_time,
                "decision": decision.to_dict(),
                "result_ok": result.is_ok,
                "context": context,
            })
            
            # Apply the decision
            adjustment = self._apply_decision(decision, context)
            
            if adjustment:
                self.adjustment_count += 1
                self.adjustment_history.append({
                    "timestamp": current_time,
                    "adjustment": adjustment.to_dict(),
                    "decision": decision.to_dict(),
                })
            
            return decision
    
    def _apply_decision(
        self,
        decision: PolicyDecision,
        context: Dict[str, Any]
    ) -> Optional[ResourceAdjustment]:
        """Apply a policy decision to system components."""
        current_time = time.time()
        
        # Calculate cooldown with hysteresis
        base_cooldown = decision.cooldown_seconds or 0.0
        hysteresis_cooldown = self._calculate_hysteresis_cooldown(base_cooldown)
        final_cooldown = min(max(hysteresis_cooldown, self.min_cooldown), self.max_cooldown)
        
        self.cooldown_until = current_time + final_cooldown
        
        # Apply action-specific adjustments
        adjustment = ResourceAdjustment()
        
        if decision.action == PolicyAction.THROTTLE:
            self.state = GovernorState.THROTTLED
            adjustment = self._apply_throttle(decision, context)
            
        elif decision.action == PolicyAction.PAUSE:
            self.state = GovernorState.PAUSED
            adjustment = self._apply_pause(decision, context)
            
        elif decision.action == PolicyAction.DEGRADE:
            self.state = GovernorState.DEGRADED
            adjustment = self._apply_degrade(decision, context)
            
        elif decision.action == PolicyAction.RETRY:
            # Retry doesn't change state, just applies backoff
            adjustment.cooldown_until = current_time + (decision.backoff_seconds or 0.0)
            
        elif decision.action == PolicyAction.OPEN_CIRCUIT:
            self.state = GovernorState.PAUSED
            adjustment = self._apply_circuit_open(decision, context)
            
        elif decision.action == PolicyAction.ABORT:
            self.state = GovernorState.PAUSED
            adjustment = self._apply_abort(decision, context)
            
        elif decision.action == PolicyAction.SKIP:
            # Skip doesn't change state
            pass
            
        elif decision.action == PolicyAction.CONTINUE:
            # Check if we should recover from a degraded state
            if self.state != GovernorState.NORMAL:
                adjustment = self._apply_recovery(decision, context)
        
        # Apply the adjustment to connected components
        if adjustment:
            self._apply_adjustment(adjustment)
            self.current_adjustment = adjustment
        
        return adjustment
    
    def _apply_throttle(
        self,
        decision: PolicyDecision,
        context: Dict[str, Any]
    ) -> ResourceAdjustment:
        """Apply throttling adjustments."""
        adjustment = ResourceAdjustment()
        
        # Reduce workers by 50%
        if self.resource_pools:
            current_workers = self._get_current_workers()
            new_workers = max(1, int(current_workers * 0.5))
            adjustment.workers = new_workers
        
        # Reduce batch size by 50%
        adjustment.batch_size = 50  # Default reduced batch size
        
        # Reduce wave size if connected
        if self.wave_planner:
            adjustment.wave_size = 10  # Default reduced wave size
        
        return adjustment
    
    def _apply_pause(
        self,
        decision: PolicyDecision,
        context: Dict[str, Any]
    ) -> ResourceAdjustment:
        """Apply pause adjustments."""
        adjustment = ResourceAdjustment()
        
        # Set workers to 0 (pause)
        adjustment.workers = 0
        
        # Set batch size to 0
        adjustment.batch_size = 0
        
        # Set wave size to 0
        adjustment.wave_size = 0
        
        # Trigger cleanup if needed
        if self.watermark_cleanup and 'disk_full' in decision.reason:
            self._trigger_cleanup(aggressive=True)
        
        return adjustment
    
    def _apply_degrade(
        self,
        decision: PolicyDecision,
        context: Dict[str, Any]
    ) -> ResourceAdjustment:
        """Apply degradation adjustments."""
        adjustment = ResourceAdjustment()
        
        # Disable non-essential components
        adjustment.disabled_components = {
            'ocr',  # Disable OCR processing
            'rerank',  # Disable reranking
            'semantic_search',  # Disable semantic search (use keyword only)
        }
        
        # Reduce workers by 30%
        if self.resource_pools:
            current_workers = self._get_current_workers()
            new_workers = max(1, int(current_workers * 0.7))
            adjustment.workers = new_workers
        
        # Reduce batch size by 30%
        adjustment.batch_size = 70  # Default degraded batch size
        
        return adjustment
    
    def _apply_circuit_open(
        self,
        decision: PolicyDecision,
        context: Dict[str, Any]
    ) -> ResourceAdjustment:
        """Apply circuit open adjustments."""
        adjustment = ResourceAdjustment()
        
        # Similar to pause but for specific service
        service = decision.metadata.get('service', 'unknown')
        
        # Set workers to 0 for affected service
        adjustment.workers = 0
        
        # Mark which service circuit is open
        adjustment.disabled_components = {f"circuit_open_{service}"}
        
        return adjustment
    
    def _apply_abort(
        self,
        decision: PolicyDecision,
        context: Dict[str, Any]
    ) -> ResourceAdjustment:
        """Apply abort adjustments."""
        adjustment = ResourceAdjustment()
        
        # Complete shutdown
        adjustment.workers = 0
        adjustment.batch_size = 0
        adjustment.wave_size = 0
        adjustment.disabled_components = {'all'}
        
        return adjustment
    
    def _apply_recovery(
        self,
        decision: PolicyDecision,
        context: Dict[str, Any]
    ) -> ResourceAdjustment:
        """Apply recovery adjustments."""
        self.recovery_count += 1
        
        # Gradual recovery
        if self.state == GovernorState.PAUSED:
            # From paused to throttled
            self.state = GovernorState.THROTTLED
            return self._apply_throttle(decision, context)
        
        elif self.state == GovernorState.THROTTLED:
            # From throttled to degraded
            self.state = GovernorState.DEGRADED
            return self._apply_degrade(decision, context)
        
        elif self.state == GovernorState.DEGRADED:
            # From degraded to normal
            self.state = GovernorState.NORMAL
            
            adjustment = ResourceAdjustment()
            
            # Restore normal settings
            if self.resource_pools:
                adjustment.workers = self._get_default_workers()
            
            adjustment.batch_size = 100  # Default normal batch size
            adjustment.wave_size = 20  # Default normal wave size
            adjustment.disabled_components = set()  # Enable all components
            
            return adjustment
        
        return None
    
    def _apply_adjustment(self, adjustment: ResourceAdjustment) -> None:
        """Apply adjustment to connected components."""
        # Apply to resource pools
        if self.resource_pools and adjustment.workers is not None:
            self._set_workers(adjustment.workers)
        
        # Apply to wave planner
        if self.wave_planner and adjustment.wave_size is not None:
            self._set_wave_size(adjustment.wave_size)
        
        # Note: Batch size would be applied to the pipeline
        # Disabled components would be communicated to affected services
    
    def _calculate_hysteresis_cooldown(self, base_cooldown: float) -> float:
        """Calculate cooldown with hysteresis to prevent oscillation."""
        if not self.adjustment_history:
            return base_cooldown
        
        # Check recent history for similar adjustments
        recent_adjustments = list(self.adjustment_history)
        similar_count = 0
        
        for hist in recent_adjustments[-3:]:  # Last 3 adjustments
            # Simple similarity check
            if abs(hist['adjustment'].get('workers', 0) - 
                   self.current_adjustment.workers or 0) < 2:
                similar_count += 1
        
        # Apply hysteresis: longer cooldown if similar recent adjustments
        hysteresis_multiplier = 1.0 + (self.hysteresis_factor * similar_count)
        return base_cooldown * hysteresis_multiplier
    
    def _get_current_workers(self) -> int:
        """Get current worker count from resource pools."""
        # This would query the actual resource pools
        # For now, return a default
        return 4
    
    def _get_default_workers(self) -> int:
        """Get default worker count."""
        return 4
    
    def _set_workers(self, count: int) -> None:
        """Set worker count in resource pools."""
        # This would update the actual resource pools
        pass
    
    def _set_wave_size(self, size: int) -> None:
        """Set wave size in wave planner."""
        # This would update the actual wave planner
        pass
    
    def _trigger_cleanup(self, aggressive: bool = False) -> None:
        """Trigger watermark cleanup."""
        if self.watermark_cleanup:
            # This would call the cleanup component
            pass
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get governor metrics."""
        with self._lock:
            return {
                "state": self.state.value,
                "decision_count": self.decision_count,
                "adjustment_count": self.adjustment_count,
                "recovery_count": self.recovery_count,
                "cooldown_until": self.cooldown_until,
                "cooldown_remaining": max(0, self.cooldown_until - time.time()),
                "current_adjustment": self.current_adjustment.to_dict(),
                "decision_history_size": len(self.decision_history),
                "adjustment_history_size": len(self.adjustment_history),
            }
    
    def get_state(self) -> Dict[str, Any]:
        """Get current governor state."""
        with self._lock:
            return {
                "state": self.state.value,
                "current_adjustment": self.current_adjustment.to_dict(),
                "cooldown_until": self.cooldown_until,
                "cooldown_remaining": max(0, self.cooldown_until - time.time()),
            }


# Global default governor
_default_governor: Optional[ResourceGovernor] = None


def get_default_governor() -> ResourceGovernor:
    """Get the global default resource governor."""
    global _default_governor
    if _default_governor is None:
        _default_governor = ResourceGovernor()
    return _default_governor


def set_default_governor(governor: ResourceGovernor) -> None:
    """Set the global default resource governor."""
    global _default_governor
    _default_governor = governor


# Convenience function
def process_with_governor(
    result: Result[Any, ErrorEvent],
    context: Dict[str, Any]
) -> PolicyDecision:
    """Process a result using the default governor."""
    return get_default_governor().process_result(result, context)
