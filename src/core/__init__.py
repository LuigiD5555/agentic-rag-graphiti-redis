"""
Core modules for Result pattern implementation.

This package provides the foundation for the Result pattern implementation
as described in the plan: Template Method (Adapters) + Error Policy Strategy +
Mapper Chain + Metadata (Errors + Pressure Signals).

Quick-start
-----------
Simple domain error (preferred inside pipeline code):

    from src.core import Result
    from src.core.errors import ScanError

    def scan(path: str) -> Result[list[str], ScanError]:
        try:
            ...
        except OSError as exc:
            return Result.err(ScanError(path, cause=exc))
        return Result.ok(files)

Rich observability error (when circuit-breaker / policy routing is needed):

    from src.core import Result, ErrorEvent, ErrorKind, ServiceType, ProcessingStage

    return Result.err(ErrorEvent(
        kind=ErrorKind.TIMEOUT,
        service=ServiceType.WEAVIATE,
        stage=ProcessingStage.UPSERT,
    ))
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
    AnyError,
    ResultT,
    ResultAny,
)

from .errors import (
    RagError,
    # Ingestion
    IngestionError,
    ScanError,
    LoaderError,
    LoaderFileNotFoundError,
    LoaderDependencyError,
    LoaderInvalidFormatError,
    LoaderUnreadableTextError,
    ChunkError,
    EmbeddingError,
    LedgerError,
    ScoreCacheError,
    # Storage
    StorageError,
    VectorStoreError,
    VectorDimensionMismatchError,
    GraphError,
    CacheError,
    # Query
    QueryError,
    RetrievalError,
    RetrievalTimeoutError,
    RetrievalConnectionError,
    GenerationError,
    # Memory
    MemoryError,
    SnapshotError,
    ChatPersistenceError,
    # Config
    ConfigError,
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
    'AnyError',
    'ResultT',
    'ResultAny',
    # Result enums / events
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
    # Domain exceptions — base
    'RagError',
    # Domain exceptions — ingestion
    'IngestionError',
    'ScanError',
    'LoaderError',
    'LoaderFileNotFoundError',
    'LoaderDependencyError',
    'LoaderInvalidFormatError',
    'LoaderUnreadableTextError',
    'ChunkError',
    'EmbeddingError',
    'LedgerError',
    'ScoreCacheError',
    # Domain exceptions — storage
    'StorageError',
    'VectorStoreError',
    'VectorDimensionMismatchError',
    'GraphError',
    'CacheError',
    # Domain exceptions — query
    'QueryError',
    'RetrievalError',
    'RetrievalTimeoutError',
    'RetrievalConnectionError',
    'GenerationError',
    # Domain exceptions — memory
    'MemoryError',
    'SnapshotError',
    'ChatPersistenceError',
    # Domain exceptions — config
    'ConfigError',
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
