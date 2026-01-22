"""
Template Method pattern for Adapters.

This module provides a base Adapter class that implements the Template Method
pattern for consistent error handling and Result pattern integration.
"""

import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic
from functools import wraps

from .result import Result, ErrorEvent, PressureEvent, ProcessingStage, ServiceType
from .mapper_chain import get_default_mapper_chain, map_to_result

T = TypeVar('T')  # Return type
E = TypeVar('E')  # Error type (usually ErrorEvent)


class AdapterBase(ABC, Generic[T, E]):
    """
    Base class for all adapters implementing the Template Method pattern.
    
    This class provides a consistent framework for:
    1. Executing operations
    2. Capturing exceptions
    3. Mapping exceptions to standardized events
    4. Returning Result objects
    5. Reporting events for observability
    """
    
    def __init__(
        self,
        service_type: ServiceType,
        default_stage: ProcessingStage,
        mapper_chain=None
    ):
        """
        Initialize the adapter.
        
        Args:
            service_type: The type of service this adapter handles
            default_stage: Default processing stage for errors
            mapper_chain: Mapper chain for error normalization (uses default if None)
        """
        self.service_type = service_type
        self.default_stage = default_stage
        self.mapper_chain = mapper_chain or get_default_mapper_chain()
        
        # Metrics and observability
        self._operation_count = 0
        self._error_count = 0
        self._pressure_warning_count = 0
    
    def execute(
        self,
        operation: Callable[..., T],
        operation_name: str,
        stage: Optional[ProcessingStage] = None,
        context: Optional[Dict[str, Any]] = None,
        *args,
        **kwargs
    ) -> Result[T, ErrorEvent]:
        """
        Execute an operation with consistent error handling (Template Method).
        
        This is the main template method that defines the algorithm:
        1. Prepare context
        2. Execute operation
        3. Capture any exceptions
        4. Map exceptions to events
        5. Return Result
        6. Report for observability
        
        Args:
            operation: The function to execute
            operation_name: Name of the operation for logging/context
            stage: Processing stage (uses default if None)
            context: Additional context for error mapping
            *args: Arguments to pass to operation
            **kwargs: Keyword arguments to pass to operation
            
        Returns:
            Result containing either the operation result or an ErrorEvent
        """
        self._operation_count += 1
        
        # Prepare context
        exec_stage = stage or self.default_stage
        exec_context = {
            'service': self.service_type,
            'stage': exec_stage,
            'operation': operation_name,
            'adapter': self.__class__.__name__,
            'timestamp': time.time(),
        }
        if context:
            exec_context.update(context)
        
        try:
            # Execute the operation (variable part of template)
            result = self._execute_operation(operation, *args, **kwargs)
            
            # Check for pressure indicators
            pressure_warnings = self._check_pressure_indicators(exec_context)
            
            # Return successful result with any warnings
            return Result.ok(result, warnings=pressure_warnings)
            
        except Exception as e:
            self._error_count += 1
            
            # Map exception to standardized event
            error_result = self.mapper_chain.map_to_result(e, exec_context)
            
            # Report the error for observability
            self._report_error(error_result, exec_context)
            
            return error_result
    
    @abstractmethod
    def _execute_operation(self, operation: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute the actual operation (to be implemented by subclasses).
        
        This is the variable part of the Template Method that subclasses
        must implement. It can add service-specific logic around the operation.
        
        Args:
            operation: The function to execute
            *args: Arguments to pass to operation
            **kwargs: Keyword arguments to pass to operation
            
        Returns:
            The result of the operation
        """
        pass
    
    def _check_pressure_indicators(self, context: Dict[str, Any]) -> List[PressureEvent]:
        """
        Check for resource pressure indicators.
        
        Subclasses can override this to add service-specific pressure detection.
        
        Args:
            context: Execution context
            
        Returns:
            List of PressureEvent warnings, if any
        """
        # Base implementation returns empty list
        # Subclasses can check service-specific metrics
        return []
    
    def _report_error(self, result: Result[Any, ErrorEvent], context: Dict[str, Any]) -> None:
        """
        Report an error for observability.
        
        Subclasses can override this to add service-specific reporting.
        
        Args:
            result: The error result
            context: Execution context
        """
        # Base implementation does nothing
        # Subclasses can log, send to monitoring, update metrics, etc.
        pass
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get adapter metrics."""
        return {
            'operation_count': self._operation_count,
            'error_count': self._error_count,
            'pressure_warning_count': self._pressure_warning_count,
            'error_rate': self._error_count / self._operation_count if self._operation_count > 0 else 0.0,
            'service_type': self.service_type.value,
            'default_stage': self.default_stage.value,
        }


def adapter_method(
    operation_name: Optional[str] = None,
    stage: Optional[ProcessingStage] = None
):
    """
    Decorator for adapter methods that automatically uses the execute template.
    
    Usage:
        @adapter_method(operation_name="upsert", stage=ProcessingStage.UPSERT)
        def upsert(self, key: str, vector: List[float], metadata: Dict[str, Any]) -> Result[None, ErrorEvent]:
            def _operation(key, vector, metadata):
                # Actual implementation
                self._client.upsert(key, vector, metadata)
            
            return self.execute(_operation, "upsert", self.default_stage, 
                               {"key": key, "vector_len": len(vector)})
    """
    def decorator(method):
        @wraps(method)
        def wrapper(self, *args, **kwargs):
            # If the method already returns a Result, use it directly
            result = method(self, *args, **kwargs)
            if isinstance(result, Result):
                return result
            
            # Otherwise, wrap the method call in execute
            op_name = operation_name or method.__name__
            op_stage = stage or getattr(self, 'default_stage', None)
            
            def _operation(*args, **kwargs):
                return method(self, *args, **kwargs)
            
            return self.execute(_operation, op_name, op_stage)
        return wrapper
    return decorator


# Example adapter implementations

class WeaviateAdapter(AdapterBase):
    """Adapter for Weaviate operations."""
    
    def __init__(self, client, mapper_chain=None):
        super().__init__(
            service_type=ServiceType.WEAVIATE,
            default_stage=ProcessingStage.UPSERT,
            mapper_chain=mapper_chain
        )
        self.client = client
    
    def _execute_operation(self, operation: Callable[..., T], *args, **kwargs) -> T:
        """Execute Weaviate operation with retry logic."""
        # Add Weaviate-specific logic here (retries, timeouts, etc.)
        return operation(*args, **kwargs)
    
    @adapter_method(operation_name="batch_upsert", stage=ProcessingStage.UPSERT)
    def batch_upsert(self, records: List[Dict[str, Any]]) -> Result[None, ErrorEvent]:
        """Batch upsert records to Weaviate."""
        def _operation(records):
            return self.client.batch_upsert(records)
        
        context = {
            'record_count': len(records),
            'operation': 'batch_upsert'
        }
        
        return self.execute(_operation, "batch_upsert", ProcessingStage.UPSERT, context, records)


class RedisAdapter(AdapterBase):
    """Adapter for Redis operations."""
    
    def __init__(self, client, mapper_chain=None):
        super().__init__(
            service_type=ServiceType.REDIS,
            default_stage=ProcessingStage.IDEMPOTENCY,
            mapper_chain=mapper_chain
        )
        self.client = client
    
    def _execute_operation(self, operation: Callable[..., T], *args, **kwargs) -> T:
        """Execute Redis operation with connection handling."""
        # Add Redis-specific logic here (connection pooling, etc.)
        return operation(*args, **kwargs)


class FilesystemAdapter(AdapterBase):
    """Adapter for filesystem operations."""
    
    def __init__(self, mapper_chain=None):
        super().__init__(
            service_type=ServiceType.FILESYSTEM,
            default_stage=ProcessingStage.PREPROCESS,
            mapper_chain=mapper_chain
        )
    
    def _execute_operation(self, operation: Callable[..., T], *args, **kwargs) -> T:
        """Execute filesystem operation with path validation."""
        # Add filesystem-specific logic here (path validation, etc.)
        return operation(*args, **kwargs)
