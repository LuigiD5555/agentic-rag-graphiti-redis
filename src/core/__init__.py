"""
Core modules for Result pattern implementation.

This package provides the foundation for the Result pattern implementation
as described in the plan: Template Method (Adapters) + Error Policy Strategy + 
Mapper Chain + Metadata (Errores + Señales de presión).
"""

from .result import (
    Result,
    ErrorEvent,
    PressureEvent,
    ErrorKind,
    ServiceType,
    ProcessingStage,
    Severity,
    PressureType,
    PressureTrend,
    PressureScope,
    ActionHint,
    ResultT,
    ResultAny,
)

from .mappers import (
    BaseMapper,
    HttpErrorMapper,
    WeaviateErrorMapper,
    FilesystemErrorMapper,
    PythonRuntimeMapper,
    PressureMapper,
    FallbackUnknownMapper,
)

from .mapper_chain import (
    MapperChain,
    get_default_mapper_chain,
    set_default_mapper_chain,
    map_exception,
    map_to_result,
)

from .adapters import (
    AdapterBase,
    adapter_method,
    WeaviateAdapter,
    FilesystemAdapter,
)

from .policy import (
    PolicyAction,
    PolicyDecision,
    CircuitBreaker,
    BaseErrorPolicy,
    DefaultErrorPolicy,
    get_default_policy,
    set_default_policy,
    decide_action,
)

from .resource_governor import (
    GovernorState,
    ResourceAdjustment,
    ResourceGovernor,
    get_default_governor,
    set_default_governor,
    process_with_governor,
)

__all__ = [
    # Result types
    'Result',
    'ErrorEvent',
    'PressureEvent',
    'ErrorKind',
    'ServiceType',
    'ProcessingStage',
    'Severity',
    'PressureType',
    'PressureTrend',
    'PressureScope',
    'ActionHint',
    'ResultT',
    'ResultAny',
    
    # Mappers
    'BaseMapper',
    'HttpErrorMapper',
    'WeaviateErrorMapper',
    'FilesystemErrorMapper',
    'PythonRuntimeMapper',
    'PressureMapper',
    'FallbackUnknownMapper',
    
    # Mapper Chain
    'MapperChain',
    'get_default_mapper_chain',
    'set_default_mapper_chain',
    'map_exception',
    'map_to_result',
    
    # Adapters
    'AdapterBase',
    'adapter_method',
    'WeaviateAdapter',
    'FilesystemAdapter',
    
    # Policy
    'PolicyAction',
    'PolicyDecision',
    'CircuitBreaker',
    'BaseErrorPolicy',
    'DefaultErrorPolicy',
    'get_default_policy',
    'set_default_policy',
    'decide_action',
    
    # Resource Governor
    'GovernorState',
    'ResourceAdjustment',
    'ResourceGovernor',
    'get_default_governor',
    'set_default_governor',
    'process_with_governor',
]
