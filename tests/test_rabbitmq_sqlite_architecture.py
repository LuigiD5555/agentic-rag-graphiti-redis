"""Test suite for validating RabbitMQ + SQLite architecture migration.

This test validates that:
1. RedisOperations has been renamed to SQLiteOperations
2. IngestQueue references have been removed
3. RabbitMQ planner is properly configured
4. SQLite control-plane works for idempotence
"""

import pytest
import os
import sys
import inspect
from unittest.mock import Mock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_redis_operations_renamed_to_sqlite_operations():
    """Test that RedisOperations has been renamed to SQLiteOperations."""
    # Check that redis_operations.py doesn't exist or doesn't have RedisOperations class
    redis_ops_path = "src/backends/storage/cache/ingestion/redis_operations.py"
    
    if os.path.exists(redis_ops_path):
        # If file exists, check if it contains RedisOperations class
        with open(redis_ops_path, 'r') as f:
            content = f.read()
            if "class RedisOperations" in content:
                pytest.fail("RedisOperations class still exists in redis_operations.py")
    
    # Try to import SQLiteOperations (should succeed)
    try:
        from src.backends.storage.cache.ingestion.sqlite_operations import SQLiteOperations
        assert SQLiteOperations is not None
        print("✓ SQLiteOperations import successful")
    except ImportError as e:
        pytest.fail(f"SQLiteOperations import failed: {e}")


def test_ingestqueue_references_removed():
    """Test that IngestQueue references have been removed from pipeline."""
    from src.workflows.ingestion.pipeline.pipeline import IngestionPipeline
    
    # Check that ingest_queue parameter is not in __init__
    import inspect
    init_signature = inspect.signature(IngestionPipeline.__init__)
    init_params = list(init_signature.parameters.keys())
    
    assert 'ingest_queue' not in init_params, "IngestQueue parameter should be removed from __init__"
    assert 'chunk_registry' not in init_params, "chunk_registry parameter should be removed from __init__"
    
    # Check that from_options doesn't have ingest_queue parameter
    from_options_signature = inspect.signature(IngestionPipeline.from_options)
    from_options_params = list(from_options_signature.parameters.keys())
    
    assert 'ingest_queue' not in from_options_params, "IngestQueue parameter should be removed from from_options"
    assert 'chunk_registry' not in from_options_params, "chunk_registry parameter should be removed from from_options"
    
    print("✓ IngestQueue references removed from pipeline")


def test_planner_attribute_exists():
    """Test that planner attribute exists in IngestionPipeline."""
    from src.workflows.ingestion.pipeline.pipeline import IngestionPipeline
    
    # Check that planner is defined in the class (either in __init__ or as class attribute)
    # The planner is defined in __init__ as self.planner: Optional[IngestionPlanner]
    # Check the source code for the planner attribute definition
    import inspect
    source = inspect.getsource(IngestionPipeline.__init__)
    
    # Check that planner is mentioned in __init__
    assert 'self.planner' in source, "Pipeline __init__ should define self.planner"
    assert 'IngestionPlanner' in source, "Pipeline should reference IngestionPlanner type"
    
    print("✓ Planner attribute exists in pipeline")


def test_rabbitmq_queue_module_exists():
    """Test that RabbitMQ queue module exists."""
    try:
        from src.workflows.ingestion.rabbitmq_queue import RabbitMQIngestQueue
        assert RabbitMQIngestQueue is not None
        
        # Check that it has required methods
        queue = RabbitMQIngestQueue(max_retries=3)
        assert hasattr(queue, 'enqueue_job')
        assert hasattr(queue, 'enqueue_batch')
        assert hasattr(queue, 'process_jobs')
        assert hasattr(queue, 'connect')
        
        print("✓ RabbitMQIngestQueue module exists with required methods")
    except ImportError as e:
        pytest.fail(f"RabbitMQIngestQueue import failed: {e}")


def test_job_state_repository_exists():
    """Test that JobStateRepository exists for SQLite control-plane."""
    try:
        from src.workflows.ingestion.state.job_state_repository import JobStateRepository
        assert JobStateRepository is not None
        
        # Check that it has required methods
        repo = JobStateRepository()
        assert hasattr(repo, 'try_claim')
        assert hasattr(repo, 'mark_done')
        assert hasattr(repo, 'mark_failed')
        
        print("✓ JobStateRepository exists for SQLite control-plane")
    except ImportError as e:
        pytest.fail(f"JobStateRepository import failed: {e}")


def test_planner_module_exists():
    """Test that IngestionPlanner exists."""
    try:
        from src.workflows.ingestion.jobs.planner import IngestionPlanner
        assert IngestionPlanner is not None
        
        print("✓ IngestionPlanner module exists")
    except ImportError as e:
        pytest.fail(f"IngestionPlanner import failed: {e}")


def test_worker_module_exists():
    """Test that IngestionWorker exists."""
    try:
        from src.workflows.ingestion.jobs.worker import IngestionWorker
        assert IngestionWorker is not None
        
        print("✓ IngestionWorker module exists")
    except ImportError as e:
        pytest.fail(f"IngestionWorker import failed: {e}")


def test_strategy_uses_rabbitmq_planner():
    """Test that BaseStrategy uses RabbitMQ planner when configured."""
    from src.workflows.ingestion.strategies.base import IngestionStrategy
    
    # Check that _run_ingestion method exists and has RabbitMQ logic
    strategy_code = inspect.getsource(IngestionStrategy._run_ingestion)
    
    # Check for RabbitMQ related keywords
    assert 'RabbitMQ' in strategy_code, "Strategy should mention RabbitMQ"
    assert 'planner' in strategy_code, "Strategy should use planner"
    assert 'publish' in strategy_code, "Strategy should have publish logic"
    
    print("✓ BaseStrategy uses RabbitMQ planner logic")


def test_systemd_service_exists():
    """Test that systemd service for workers exists."""
    service_path = "systemd/user/tool-ingestion-worker.service"
    assert os.path.exists(service_path), f"Systemd service not found: {service_path}"
    
    # Read service file
    with open(service_path, 'r') as f:
        service_content = f.read()
    
    # Check for required components
    # The service runs worker_cli which starts ingestion workers
    assert "worker_cli" in service_content, "Service should run worker_cli"
    assert "rabbitmq" in service_content.lower(), "Service should mention RabbitMQ"
    assert "ingestion" in service_content.lower(), "Service should mention ingestion"
    
    print("✓ Systemd service for workers exists")


def test_env_configuration():
    """Test that .env has RabbitMQ configuration."""
    env_path = ".env"
    assert os.path.exists(env_path), ".env file not found"
    
    with open(env_path, 'r') as f:
        env_content = f.read()
    
    # Check for RabbitMQ configuration
    assert "RABBITMQ_" in env_content, ".env should have RabbitMQ configuration"
    assert "INGESTION_RESUMABLE_ENABLED" in env_content, ".env should have resumable ingestion flag"
    
    print("✓ .env has RabbitMQ configuration")


if __name__ == "__main__":
    # Run all tests
    print("Running RabbitMQ + SQLite architecture validation tests...")
    print("=" * 60)
    
    test_functions = [
        test_redis_operations_renamed_to_sqlite_operations,
        test_ingestqueue_references_removed,
        test_planner_attribute_exists,
        test_rabbitmq_queue_module_exists,
        test_job_state_repository_exists,
        test_planner_module_exists,
        test_worker_module_exists,
        test_strategy_uses_rabbitmq_planner,
        test_systemd_service_exists,
        test_env_configuration,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in test_functions:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"✗ {test_func.__name__} failed: {e}")
            failed += 1
    
    print("=" * 60)
    print(f"Test results: {passed} passed, {failed} failed")
    
    if failed > 0:
        sys.exit(1)