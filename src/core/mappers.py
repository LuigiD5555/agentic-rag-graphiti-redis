"""
Mapper Chain for error normalization.

This module provides mappers that convert exceptions and other error conditions
into standardized ErrorEvent and PressureEvent objects.
"""

import re
import socket
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from http.client import HTTPException
from urllib.error import URLError, HTTPError

from .result import (
    ErrorEvent, ErrorKind, ServiceType, ProcessingStage, Severity,
    PressureEvent, PressureType, PressureTrend, PressureScope, ActionHint
)


class BaseMapper:
    """Base class for all mappers."""
    
    def can_map(self, exception: Exception, context: Dict[str, Any]) -> bool:
        """Check if this mapper can handle the given exception."""
        raise NotImplementedError
    
    def map(self, exception: Exception, context: Dict[str, Any]) -> Union[ErrorEvent, PressureEvent]:
        """Map exception to standardized event."""
        raise NotImplementedError


class HttpErrorMapper(BaseMapper):
    """Maps HTTP-related errors."""
    
    def can_map(self, exception: Exception, context: Dict[str, Any]) -> bool:
        return isinstance(exception, (HTTPException, HTTPError, URLError, ConnectionError, 
                                     TimeoutError, socket.timeout))
    
    def map(self, exception: Exception, context: Dict[str, Any]) -> Union[ErrorEvent, PressureEvent]:
        stage = context.get('stage', ProcessingStage.API)
        service = context.get('service', ServiceType.HTTP_PROVIDER)
        
        # Extract status code if available
        status_code = None
        if isinstance(exception, HTTPError):
            status_code = exception.code
        elif hasattr(exception, 'status_code'):
            status_code = getattr(exception, 'status_code')
        
        # Determine error kind based on status code or exception type
        if status_code == 429:
            kind = ErrorKind.RATE_LIMIT
            retryable = True
            severity = Severity.MEDIUM
            message = f"Rate limit exceeded (HTTP 429): {exception}"
        elif status_code == 408 or status_code == 504:
            kind = ErrorKind.TIMEOUT
            retryable = True
            severity = Severity.MEDIUM
            message = f"Request timeout (HTTP {status_code}): {exception}"
        elif status_code and 500 <= status_code < 600:
            kind = ErrorKind.UPSTREAM_UNAVAILABLE
            retryable = True
            severity = Severity.HIGH
            message = f"Server error (HTTP {status_code}): {exception}"
        elif isinstance(exception, (TimeoutError, socket.timeout)):
            kind = ErrorKind.TIMEOUT
            retryable = True
            severity = Severity.MEDIUM
            message = f"Connection timeout: {exception}"
        elif isinstance(exception, ConnectionError):
            kind = ErrorKind.NETWORK
            retryable = True
            severity = Severity.HIGH
            message = f"Connection error: {exception}"
        else:
            kind = ErrorKind.NETWORK
            retryable = True
            severity = Severity.MEDIUM
            message = f"HTTP error: {exception}"
        
        metadata = {
            'exception_type': type(exception).__name__,
            'exception_message': str(exception),
            'timestamp': time.time(),
        }
        if status_code:
            metadata['http_status_code'] = status_code
        
        return ErrorEvent(
            kind=kind,
            service=service,
            stage=stage,
            retryable=retryable,
            severity=severity,
            message=message,
            metadata=metadata,
            original_exception=exception
        )


class WeaviateErrorMapper(BaseMapper):
    """Maps Weaviate-related errors."""
    
    def can_map(self, exception: Exception, context: Dict[str, Any]) -> bool:
        exception_type = type(exception).__name__
        exception_str = str(exception).lower()
        
        return 'weaviate' in exception_str or \
               'weaviate' in exception_type.lower() or \
               hasattr(exception, 'status_code')  # Weaviate exceptions often have status_code
    
    def map(self, exception: Exception, context: Dict[str, Any]) -> Union[ErrorEvent, PressureEvent]:
        stage = context.get('stage', ProcessingStage.UPSERT)
        exception_str = str(exception).lower()
        
        # Extract status code if available
        status_code = None
        if hasattr(exception, 'status_code'):
            status_code = getattr(exception, 'status_code')
        
        # Check for vector dimension mismatch
        if 'vector dimensions do not match' in exception_str:
            kind = ErrorKind.VALIDATION
            message = f"Weaviate vector dimension mismatch: {exception}"
            retryable = False  # Cannot retry with different dimension
            severity = Severity.HIGH
            
            # Extract dimensions from error message
            import re
            match = re.search(r'length (\d+)\.\s*existing nodes have vectors with length (\d+)', exception_str)
            if match:
                new_dim, existing_dim = match.groups()
                metadata = {
                    'new_dimension': int(new_dim),
                    'existing_dimension': int(existing_dim),
                    'exception_type': type(exception).__name__,
                    'exception_message': str(exception),
                    'timestamp': time.time(),
                }
            else:
                metadata = {
                    'exception_type': type(exception).__name__,
                    'exception_message': str(exception),
                    'timestamp': time.time(),
                }
        elif status_code == 422:
            kind = ErrorKind.VALIDATION
            message = f"Weaviate validation error: {exception}"
            retryable = False
            severity = Severity.MEDIUM
            metadata = {
                'exception_type': type(exception).__name__,
                'exception_message': str(exception),
                'timestamp': time.time(),
                'http_status_code': status_code,
            }
        elif status_code == 429:
            kind = ErrorKind.RATE_LIMIT
            message = f"Weaviate rate limit: {exception}"
            retryable = True
            severity = Severity.MEDIUM
            metadata = {
                'exception_type': type(exception).__name__,
                'exception_message': str(exception),
                'timestamp': time.time(),
                'http_status_code': status_code,
            }
        elif status_code and 500 <= status_code < 600:
            kind = ErrorKind.UPSTREAM_UNAVAILABLE
            message = f"Weaviate server error: {exception}"
            retryable = True
            severity = Severity.HIGH
            metadata = {
                'exception_type': type(exception).__name__,
                'exception_message': str(exception),
                'timestamp': time.time(),
                'http_status_code': status_code,
            }
        else:
            kind = ErrorKind.UNKNOWN
            message = f"Weaviate error: {exception}"
            retryable = True
            severity = Severity.MEDIUM
            metadata = {
                'exception_type': type(exception).__name__,
                'exception_message': str(exception),
                'timestamp': time.time(),
            }
            if status_code:
                metadata['http_status_code'] = status_code
        
        return ErrorEvent(
            kind=kind,
            service=ServiceType.WEAVIATE,
            stage=stage,
            retryable=retryable,
            severity=severity,
            message=message,
            metadata=metadata,
            original_exception=exception
        )


class FilesystemErrorMapper(BaseMapper):
    """Maps filesystem-related errors."""
    
    def can_map(self, exception: Exception, context: Dict[str, Any]) -> bool:
        exception_type = type(exception).__name__
        
        filesystem_exceptions = [
            'FileNotFoundError', 'PermissionError', 'IsADirectoryError',
            'NotADirectoryError', 'OSError', 'IOError'
        ]
        
        return exception_type in filesystem_exceptions or \
               isinstance(exception, (OSError, IOError))
    
    def map(self, exception: Exception, context: Dict[str, Any]) -> Union[ErrorEvent, PressureEvent]:
        stage = context.get('stage', ProcessingStage.PREPROCESS)
        exception_str = str(exception).lower()
        
        # Check for disk full error
        if 'no space left' in exception_str or 'disk full' in exception_str:
            return PressureEvent(
                pressure_type=PressureType.DISK,
                current=100.0,  # Assume disk is full
                threshold=90.0,  # Threshold for cleanup
                trend=PressureTrend.RISING,
                scope=PressureScope.CONTAINER,
                stage=stage,
                action_hint=ActionHint.CLEANUP,
                cooldown_s=60,
                metadata={
                    'exception_type': type(exception).__name__,
                    'exception_message': str(exception),
                    'timestamp': time.time(),
                    'filesystem_error': 'no_space_left'
                }
            )
        
        # Determine error kind
        if isinstance(exception, FileNotFoundError):
            kind = ErrorKind.NOT_FOUND
            message = f"File not found: {exception}"
            retryable = False
            severity = Severity.LOW
        elif isinstance(exception, PermissionError):
            kind = ErrorKind.PERMISSION
            message = f"Permission denied: {exception}"
            retryable = False
            severity = Severity.MEDIUM
        else:
            kind = ErrorKind.UNKNOWN
            message = f"Filesystem error: {exception}"
            retryable = True
            severity = Severity.MEDIUM
        
        metadata = {
            'exception_type': type(exception).__name__,
            'exception_message': str(exception),
            'timestamp': time.time(),
        }
        
        return ErrorEvent(
            kind=kind,
            service=ServiceType.FILESYSTEM,
            stage=stage,
            retryable=retryable,
            severity=severity,
            message=message,
            metadata=metadata,
            original_exception=exception
        )


class PythonRuntimeMapper(BaseMapper):
    """Maps Python runtime errors."""
    
    def can_map(self, exception: Exception, context: Dict[str, Any]) -> bool:
        exception_type = type(exception).__name__
        
        runtime_exceptions = [
            'MemoryError', 'RecursionError', 'KeyboardInterrupt',
            'SystemExit', 'GeneratorExit', 'RuntimeError'
        ]
        
        return exception_type in runtime_exceptions or \
               isinstance(exception, MemoryError)
    
    def map(self, exception: Exception, context: Dict[str, Any]) -> Union[ErrorEvent, PressureEvent]:
        stage = context.get('stage', ProcessingStage.EMBED)
        
        if isinstance(exception, MemoryError):
            # Memory error is a pressure event
            return PressureEvent(
                pressure_type=PressureType.RAM,
                current=100.0,  # Assume OOM
                threshold=90.0,  # Threshold for cleanup
                trend=PressureTrend.RISING,
                scope=PressureScope.CONTAINER,
                stage=stage,
                action_hint=ActionHint.REDUCE_BATCH,
                cooldown_s=120,
                metadata={
                    'exception_type': type(exception).__name__,
                    'exception_message': str(exception),
                    'timestamp': time.time(),
                    'runtime_error': 'memory_error'
                }
            )
        elif isinstance(exception, KeyboardInterrupt):
            kind = ErrorKind.UNKNOWN
            message = "Operation interrupted by user"
            retryable = False
            severity = Severity.LOW
        elif isinstance(exception, RuntimeError):
            exception_str = str(exception).lower()
            if 'cancelled' in exception_str:
                kind = ErrorKind.UNKNOWN
                message = f"Operation cancelled: {exception}"
                retryable = True
                severity = Severity.LOW
            else:
                kind = ErrorKind.UNKNOWN
                message = f"Runtime error: {exception}"
                retryable = True
                severity = Severity.MEDIUM
        else:
            kind = ErrorKind.UNKNOWN
            message = f"Runtime error: {exception}"
            retryable = True
            severity = Severity.MEDIUM
        
        metadata = {
            'exception_type': type(exception).__name__,
            'exception_message': str(exception),
            'timestamp': time.time(),
        }
        
        return ErrorEvent(
            kind=kind,
            service=ServiceType.LLM,  # Default to LLM for runtime errors
            stage=stage,
            retryable=retryable,
            severity=severity,
            message=message,
            metadata=metadata,
            original_exception=exception
        )


class PressureMapper(BaseMapper):
    """Maps certain patterns to PressureEvents."""
    
    def can_map(self, exception: Exception, context: Dict[str, Any]) -> bool:
        # This mapper looks for pressure indicators in the context
        # rather than specific exceptions
        pressure_indicators = context.get('pressure_indicators', {})
        return bool(pressure_indicators)
    
    def map(self, exception: Exception, context: Dict[str, Any]) -> Union[ErrorEvent, PressureEvent]:
        pressure_indicators = context.get('pressure_indicators', {})
        stage = context.get('stage', ProcessingStage.RESOURCE_MANAGEMENT)
        
        # Determine the highest pressure
        max_pressure = 0.0
        pressure_type = PressureType.CPU
        for p_type, value in pressure_indicators.items():
            if value > max_pressure:
                max_pressure = value
                try:
                    pressure_type = PressureType(p_type)
                except ValueError:
                    pressure_type = PressureType.CPU
        
        # Determine trend (simplified)
        trend = PressureTrend.RISING if max_pressure > 70 else PressureTrend.STABLE
        
        # Determine action hint based on pressure level
        if max_pressure > 90:
            action_hint = ActionHint.PAUSE
            cooldown_s = 300  # 5 minutes
        elif max_pressure > 80:
            action_hint = ActionHint.THROTTLE
            cooldown_s = 120  # 2 minutes
        elif max_pressure > 70:
            action_hint = ActionHint.REDUCE_BATCH
            cooldown_s = 60  # 1 minute
        else:
            action_hint = ActionHint.RETRY
            cooldown_s = 30
        
        return PressureEvent(
            pressure_type=pressure_type,
            current=max_pressure,
            threshold=70.0,  # Default threshold
            trend=trend,
            scope=PressureScope.CONTAINER,
            stage=stage,
            action_hint=action_hint,
            cooldown_s=cooldown_s,
            metadata={
                'pressure_indicators': pressure_indicators,
                'timestamp': time.time(),
                'context': {
                    context_key: context_value
                    for context_key, context_value in context.items()
                    if context_key != 'pressure_indicators'
                }
            }
        )


class FallbackUnknownMapper(BaseMapper):
    """Fallback mapper for unknown exceptions."""
    
    def can_map(self, exception: Exception, context: Dict[str, Any]) -> bool:
        return True  # Always matches as fallback
    
    def map(self, exception: Exception, context: Dict[str, Any]) -> Union[ErrorEvent, PressureEvent]:
        stage = context.get('stage', ProcessingStage.API)
        service = context.get('service', ServiceType.LLM)
        
        metadata = {
            'exception_type': type(exception).__name__,
            'exception_message': str(exception),
            'timestamp': time.time(),
            'context': context
        }
        
        return ErrorEvent(
            kind=ErrorKind.UNKNOWN,
            service=service,
            stage=stage,
            retryable=True,
            severity=Severity.MEDIUM,
            message=f"Unknown error: {exception}",
            metadata=metadata,
            original_exception=exception
        )
