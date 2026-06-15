#!/usr/bin/env python3
"""
Test script to demonstrate the Result pattern implementation.

This script shows how to use the new Result pattern classes
to replace try/except blocks with a more structured error handling approach.
"""

import sys
import time
from pathlib import Path
from typing import Dict, Any

# Ensure repo root is on sys.path for direct script execution
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from src.core import (
    Result, ErrorEvent, PressureEvent, ErrorKind, ServiceType, 
    ProcessingStage, Severity, PressureType, PressureTrend, 
    PressureScope, ActionHint, map_exception, map_to_result,
    decide_action, process_with_governor
)


def demonstrate_basic_result() -> None:
    """Demonstrate basic Result usage."""
    print("=== Basic Result Usage ===")
    
    # Create a successful result
    success_result = Result.ok("Operation completed successfully")
    print(f"Success result: {success_result}")
    print(f"Is OK: {success_result.is_ok}")
    print(f"Value: {success_result.value}")
    
    # Create an error result
    error_event = ErrorEvent(
        kind=ErrorKind.TIMEOUT,
        service=ServiceType.WEAVIATE,
        stage=ProcessingStage.UPSERT,
        retryable=True,
        severity=Severity.MEDIUM,
        message="Weaviate timeout after 30 seconds"
    )
    error_result = Result.err(error_event)
    print(f"\nError result: {error_result}")
    print(f"Is error: {error_result.is_err}")
    print(f"Error: {error_result.error}")
    
    # Demonstrate unwrap methods
    print(f"\nUnwrap or default: {error_result.unwrap_or('fallback value')}")
    
    # Demonstrate map
    mapped_result = success_result.map(lambda x: f"Mapped: {x.upper()}")
    print(f"Mapped result: {mapped_result}")


def demonstrate_exception_mapping() -> None:
    """Demonstrate exception mapping."""
    print("\n=== Exception Mapping ===")
    
    # Simulate different types of exceptions
    exceptions = [
        ConnectionError("Connection refused"),
        FileNotFoundError("File not found: /path/to/file.txt"),
        MemoryError("Out of memory"),
        ValueError("Invalid value provided"),
    ]
    
    for exc in exceptions:
        print(f"\nOriginal exception: {type(exc).__name__}: {exc}")
        
        # Map exception to standardized event
        context = {
            'service': ServiceType.FILESYSTEM,
            'stage': ProcessingStage.PREPROCESS,
            'operation': 'read_file'
        }
        
        event = map_exception(exc, context)
        print(f"Mapped to: {type(event).__name__}: {event}")
        
        # Map to Result
        result = map_to_result(exc, context)
        print(f"Result: {result}")


def demonstrate_policy_decisions() -> None:
    """Demonstrate policy decisions."""
    print("\n=== Policy Decisions ===")
    
    # Create different error scenarios
    scenarios = [
        (
            "Retryable timeout",
            ErrorEvent(
                kind=ErrorKind.TIMEOUT,
                service=ServiceType.WEAVIATE,
                stage=ProcessingStage.UPSERT,
                retryable=True,
                severity=Severity.MEDIUM,
                message="Request timeout"
            ),
            {'attempt': 1}
        ),
        (
            "Non-retryable permission error",
            ErrorEvent(
                kind=ErrorKind.PERMISSION,
                service=ServiceType.FILESYSTEM,
                stage=ProcessingStage.PREPROCESS,
                retryable=False,
                severity=Severity.MEDIUM,
                message="Permission denied"
            ),
            {'attempt': 0}
        ),
        (
            "Critical disk full error",
            ErrorEvent(
                kind=ErrorKind.DISK_FULL,
                service=ServiceType.FILESYSTEM,
                stage=ProcessingStage.PREPROCESS,
                retryable=False,
                severity=Severity.CRITICAL,
                message="No space left on device"
            ),
            {'attempt': 0}
        ),
    ]
    
    for name, error, context in scenarios:
        print(f"\nScenario: {name}")
        print(f"Error: {error}")
        
        result = Result.err(error)
        decision = decide_action(result, context)
        
        print(f"Decision: {decision.action.value}")
        print(f"Reason: {decision.reason}")
        if decision.backoff_seconds:
            print(f"Backoff: {decision.backoff_seconds:.1f}s")
        if decision.cooldown_seconds:
            print(f"Cooldown: {decision.cooldown_seconds:.1f}s")


def demonstrate_pressure_events() -> None:
    """Demonstrate pressure events and warnings."""
    print("\n=== Pressure Events ===")
    
    # Create a successful result with pressure warnings
    pressure_warning = PressureEvent(
        pressure_type=PressureType.RAM,
        current=85.0,
        threshold=80.0,
        trend=PressureTrend.RISING,
        scope=PressureScope.CONTAINER,
        stage=ProcessingStage.EMBED,
        action_hint=ActionHint.THROTTLE,
        cooldown_s=60,
        metadata={'process': 'embedding_service'}
    )
    
    success_with_warnings = Result.ok(
        "Operation completed with high RAM usage",
        warnings=[pressure_warning]
    )
    
    print(f"Result with warnings: {success_with_warnings}")
    print(f"Warning count: {len(success_with_warnings.warnings)}")
    
    for i, warning in enumerate(success_with_warnings.warnings, 1):
        print(f"  Warning {i}: {warning}")
    
    # Process through governor
    context = {'service': ServiceType.EMBEDDINGS, 'stage': ProcessingStage.EMBED}
    decision = process_with_governor(success_with_warnings, context)
    
    print(f"\nGovernor decision: {decision.action.value}")
    print(f"Reason: {decision.reason}")


def demonstrate_adapter_pattern() -> None:
    """Demonstrate adapter pattern usage."""
    print("\n=== Adapter Pattern ===")
    
    # Simulate a Weaviate adapter
    class MockWeaviateClient:
        def batch_upsert(self, records):
            # Simulate success
            return f"Upserted {len(records)} records"
        
        def batch_upsert_with_error(self, records):
            # Simulate error
            raise ConnectionError("Weaviate connection failed")
    
    # Simple adapter implementation
    from src.core.adapters import AdapterBase, ServiceType, ProcessingStage
    
    class SimpleWeaviateAdapter(AdapterBase):
        def __init__(self, client):
            super().__init__(
                service_type=ServiceType.WEAVIATE,
                default_stage=ProcessingStage.UPSERT
            )
            self.client = client
        
        def _execute_operation(self, operation, *args, **kwargs):
            # Add Weaviate-specific logic here
            return operation(*args, **kwargs)
        
        def upsert_records(self, records):
            def _operation(records):
                return self.client.batch_upsert(records)
            
            return self.execute(
                _operation,
                "batch_upsert",
                ProcessingStage.UPSERT,
                {'record_count': len(records)},
                records
            )
        
        def upsert_records_with_error(self, records):
            def _operation(records):
                return self.client.batch_upsert_with_error(records)
            
            return self.execute(
                _operation,
                "batch_upsert",
                ProcessingStage.UPSERT,
                {'record_count': len(records)},
                records
            )
    
    # Test the adapter
    client = MockWeaviateClient()
    adapter = SimpleWeaviateAdapter(client)
    
    # Successful operation
    print("Testing successful operation...")
    records = [{"id": i, "content": f"Document {i}"} for i in range(5)]
    result = adapter.upsert_records(records)
    
    if result.is_ok:
        print(f"Success: {result.value}")
    else:
        print(f"Error: {result.error}")
    
    # Error operation
    print("\nTesting error operation...")
    result = adapter.upsert_records_with_error(records)
    
    if result.is_ok:
        print(f"Success: {result.value}")
    else:
        print(f"Error: {result.error}")
        print(f"Error type: {result.error.kind.value}")
        print(f"Retryable: {result.error.retryable}")
    
    # Show metrics
    print(f"\nAdapter metrics: {adapter.get_metrics()}")


def main() -> None:
    """Run all demonstrations."""
    print("Result Pattern Implementation Demo")
    print("=" * 50)
    
    try:
        demonstrate_basic_result()
        demonstrate_exception_mapping()
        demonstrate_policy_decisions()
        demonstrate_pressure_events()
        demonstrate_adapter_pattern()
        
        print("\n" + "=" * 50)
        print("Demo completed successfully!")
        print("\nKey benefits demonstrated:")
        print("1. Structured error handling with Result type")
        print("2. Exception normalization with mapper chain")
        print("3. Policy-based decision making")
        print("4. Pressure event detection and warnings")
        print("5. Adapter pattern for consistent error handling")
        print("6. Resource governor for auto-throttling")
        
    except Exception as e:
        print(f"\nError during demo: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
