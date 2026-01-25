"""
Mapper Chain for orchestrating error normalization.

This module provides a chain of mappers that process exceptions in order,
converting them to standardized ErrorEvent or PressureEvent objects.
"""

from typing import Any, Dict, List, Optional, Union
from .result import ErrorEvent, PressureEvent, Result
from .mappers import (
    BaseMapper, HttpErrorMapper, WeaviateErrorMapper,
    FilesystemErrorMapper, PythonRuntimeMapper, PressureMapper, FallbackUnknownMapper
)


class MapperChain:
    """
    Chain of mappers that process exceptions in order.
    
    The chain processes exceptions through each mapper in sequence until
    one can handle it. The last mapper is always FallbackUnknownMapper.
    """
    
    def __init__(self, mappers: Optional[List[BaseMapper]] = None):
        """
        Initialize the mapper chain.
        
        Args:
            mappers: List of mappers to use. If None, uses default mappers.
        """
        if mappers is None:
            mappers = [
                HttpErrorMapper(),
                WeaviateErrorMapper(),
                FilesystemErrorMapper(),
                PythonRuntimeMapper(),
                PressureMapper(),
                FallbackUnknownMapper(),  # Always last
            ]
        self.mappers = mappers
    
    def map_exception(
        self, 
        exception: Exception, 
        context: Optional[Dict[str, Any]] = None
    ) -> Union[ErrorEvent, PressureEvent]:
        """
        Map an exception to a standardized event.
        
        Args:
            exception: The exception to map
            context: Additional context about where/when the error occurred
            
        Returns:
            Standardized ErrorEvent or PressureEvent
        """
        context = context or {}
        
        # Try each mapper in order
        for mapper in self.mappers:
            if mapper.can_map(exception, context):
                return mapper.map(exception, context)
        
        # This should never happen since FallbackUnknownMapper always matches
        raise RuntimeError("No mapper could handle the exception")
    
    def map_to_result(
        self,
        exception: Exception,
        context: Optional[Dict[str, Any]] = None
    ) -> 'Result[Any, ErrorEvent]':
        """
        Map an exception to a Result object.
        
        Args:
            exception: The exception to map
            context: Additional context about where/when the error occurred
            
        Returns:
            Result object with ErrorEvent or PressureEvent
        """
        from .result import Result, ErrorEvent as ErrEvent
        
        event = self.map_exception(exception, context)
        
        if isinstance(event, PressureEvent):
            # Pressure events are warnings, not errors
            # Return a successful result with warning
            return Result.ok(None, warnings=[event])
        else:
            # Error events are failures
            return Result.err(event)
    
    def add_mapper(self, mapper: BaseMapper, position: Optional[int] = None) -> None:
        """
        Add a mapper to the chain.
        
        Args:
            mapper: The mapper to add
            position: Position to insert at (0 = first). If None, inserts before fallback.
        """
        if position is None:
            # Insert before the fallback mapper
            position = len(self.mappers) - 1
            if position < 0:
                position = 0
        
        self.mappers.insert(position, mapper)
    
    def remove_mapper(self, mapper_class: type) -> None:
        """
        Remove all mappers of a specific class.
        
        Args:
            mapper_class: The class of mappers to remove
        """
        self.mappers = [m for m in self.mappers if not isinstance(m, mapper_class)]


# Global default mapper chain
_default_mapper_chain: Optional[MapperChain] = None


def get_default_mapper_chain() -> MapperChain:
    """Get the global default mapper chain."""
    global _default_mapper_chain
    if _default_mapper_chain is None:
        _default_mapper_chain = MapperChain()
    return _default_mapper_chain


def set_default_mapper_chain(chain: MapperChain) -> None:
    """Set the global default mapper chain."""
    global _default_mapper_chain
    _default_mapper_chain = chain


# Convenience functions
def map_exception(
    exception: Exception, 
    context: Optional[Dict[str, Any]] = None
) -> Union[ErrorEvent, PressureEvent]:
    """
    Map an exception using the default mapper chain.
    
    Args:
        exception: The exception to map
        context: Additional context about where/when the error occurred
        
    Returns:
        Standardized ErrorEvent or PressureEvent
    """
    return get_default_mapper_chain().map_exception(exception, context)


def map_to_result(
    exception: Exception,
    context: Optional[Dict[str, Any]] = None
) -> 'Result[Any, ErrorEvent]':
    """
    Map an exception to a Result object using the default mapper chain.
    
    Args:
        exception: The exception to map
        context: Additional context about where/when the error occurred
        
    Returns:
        Result object with ErrorEvent or PressureEvent
    """
    return get_default_mapper_chain().map_to_result(exception, context)
