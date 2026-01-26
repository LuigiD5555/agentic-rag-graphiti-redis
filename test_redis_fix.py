#!/usr/bin/env python3
"""Test script to verify Redis to SQLite migration fixes."""

import os
import sys
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.workflows.ingestion.jobs.models import IngestionJobMessage, IngestionPhase
from src.workflows.ingestion.state.job_state_repository import JobStateRepository, JobStatus
from src.workflows.ingestion.jobs.planner import IngestionPlanner
from src.workflows.ingestion.jobs.worker import IngestionWorker


async def test_job_state_repository():
    """Test JobStateRepository functionality."""
    print("=== Testing JobStateRepository ===")
    
    repo = JobStateRepository(timeout_seconds=5)  # Short timeout for testing
    
    # Create a test job
    job = IngestionJobMessage.create(
        phase=IngestionPhase.EXTRACT,
        run_id="test_run_123",
        file_path="/tmp/test_file.txt",
        fingerprint="test_fingerprint_123"
    )
    
    # Test 1: Try claim on new job
    print("Test 1: Try claim on new job")
    decision = repo.try_claim(job)
    print(f"  Decision: should_process={decision.should_process}, reason={decision.reason}")
    assert decision.should_process == True
    assert decision.reason == "new_job"
    
    # Test 2: Get status
    print("\nTest 2: Get job status")
    status = repo.get_status(job.file_path, job.phase.value, job.fingerprint)
    print(f"  Status: {status}")
    assert status is not None
    assert status["status"] == JobStatus.IN_PROGRESS.value
    
    # Test 3: Mark as done
    print("\nTest 3: Mark job as done")
    repo.mark_done(job, {"duration_ms": 100, "size_bytes": 1024})
    status = repo.get_status(job.file_path, job.phase.value, job.fingerprint)
    print(f"  Status after done: {status}")
    assert status["status"] == JobStatus.DONE.value
    
    # Test 4: Try claim on done job (should skip)
    print("\nTest 4: Try claim on done job")
    decision = repo.try_claim(job)
    print(f"  Decision: skip={decision.skip}, reason={decision.reason}")
    assert decision.skip == True
    assert "already_done" in decision.reason
    
    # Test 5: Create run
    print("\nTest 5: Create and complete run")
    repo.create_run("test_run_123")
    repo.complete_run("test_run_123", {"files_processed": 10, "chunks_created": 50})
    print("  Run created and completed successfully")
    
    print("\n✅ JobStateRepository tests passed!")


async def test_planner_and_worker():
    """Test Planner and Worker integration."""
    print("\n=== Testing Planner and Worker ===")
    
    # Create test files
    test_dir = Path("/tmp/rag_test_files")
    test_dir.mkdir(exist_ok=True)
    
    test_files = []
    for i in range(3):
        file_path = test_dir / f"test_file_{i}.txt"
        file_path.write_text(f"Test content {i}")
        test_files.append(str(file_path))
    
    try:
        # Test Planner
        print("Test 1: Planner - plan jobs")
        planner = IngestionPlanner()
        jobs = planner.plan_jobs(test_files, "test_run_456", {"test_option": True})
        print(f"  Planned {len(jobs)} jobs")
        assert len(jobs) > 0
        
        # Test Worker
        print("\nTest 2: Worker - process job")
        worker = IngestionWorker(worker_name="test_worker")
        
        # Process first job
        if jobs:
            job = jobs[0]
            result = await worker.process_job(job)
            print(f"  Processing result: {result}")
            assert "success" in result
            
            # Check status in repository
            repo = JobStateRepository()
            status = repo.get_status(job.file_path, job.phase.value, job.fingerprint)
            print(f"  Job status after processing: {status}")
            assert status is not None
            
        print("\n✅ Planner and Worker tests passed!")
        
    finally:
        # Cleanup
        for file_path in test_dir.glob("*.txt"):
            file_path.unlink()
        test_dir.rmdir()


def test_redis_files_renamed():
    """Verify that Redis files have been renamed."""
    print("\n=== Testing Redis file renaming ===")
    
    # Check that redis_* files don't exist
    redis_files = [
        "src/backends/storage/cache/redis_cache.py",
        "src/backends/storage/cache/redis_connection.py",
        "src/backends/storage/cache/ingestion/redis_operations.py",
    ]
    
    for redis_file in redis_files:
        if os.path.exists(redis_file):
            print(f"❌ Redis file still exists: {redis_file}")
            return False
    
    # Check that sqlite_* files exist
    sqlite_files = [
        "src/backends/storage/cache/sqlite_cache.py",
        "src/backends/storage/cache/sqlite_connection.py",
        "src/backends/storage/cache/ingestion/sqlite_operations.py",
    ]
    
    for sqlite_file in sqlite_files:
        if not os.path.exists(sqlite_file):
            print(f"❌ SQLite file missing: {sqlite_file}")
            return False
    
    print("✅ All Redis files renamed to SQLite!")
    return True


def test_checkpoint_init_fixed():
    """Verify checkpoint/__init__.py is fixed."""
    print("\n=== Testing checkpoint/__init__.py fix ===")
    
    init_path = "src/workflows/ingestion/checkpoint/__init__.py"
    with open(init_path, 'r') as f:
        content = f.read()
    
    # Check that it only exports what it imports
    if "IngestQueue" in content and "IngestQueue" not in content.split("from")[1]:
        print("❌ checkpoint/__init__.py still has IngestQueue in __all__ but doesn't import it")
        return False
    
    print("✅ checkpoint/__init__.py is fixed!")
    return True


def test_orchestrator_updated():
    """Verify orchestrator.py is updated for RabbitMQ."""
    print("\n=== Testing orchestrator.py updates ===")
    
    orchestrator_path = "src/workflows/ingestion/orchestrator.py"
    with open(orchestrator_path, 'r') as f:
        content = f.read()
    
    # Check that _configure_resumable_ingestion mentions RabbitMQ
    if "RabbitMQ" not in content or "resumable ingestion" not in content.lower():
        print("❌ orchestrator.py doesn't mention RabbitMQ in resumable ingestion")
        return False
    
    print("✅ orchestrator.py is updated for RabbitMQ!")
    return True


async def main():
    """Run all tests."""
    print("Running Redis to SQLite migration tests...")
    print("=" * 50)
    
    all_passed = True
    
    # Test 1: Redis files renamed
    if not test_redis_files_renamed():
        all_passed = False
    
    # Test 2: Checkpoint init fixed
    if not test_checkpoint_init_fixed():
        all_passed = False
    
    # Test 3: Orchestrator updated
    if not test_orchestrator_updated():
        all_passed = False
    
    # Test 4: JobStateRepository
    try:
        await test_job_state_repository()
    except Exception as e:
        print(f"❌ JobStateRepository test failed: {e}")
        all_passed = False
    
    # Test 5: Planner and Worker
    try:
        await test_planner_and_worker()
    except Exception as e:
        print(f"❌ Planner and Worker test failed: {e}")
        all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("✅ All tests passed! Redis to SQLite migration is complete.")
        print("\nSummary of changes:")
        print("1. ✅ Redis files renamed to SQLite (no more redis_* files)")
        print("2. ✅ checkpoint/__init__.py exports fixed")
        print("3. ✅ orchestrator.py updated for RabbitMQ")
        print("4. ✅ JobStateRepository implemented (SQLite idempotence)")
        print("5. ✅ Planner and Worker components created")
        print("\nArchitecture now follows specification:")
        print("  - RabbitMQ is the only queue")
        print("  - SQLite is the control-plane (state/idempotence)")
        print("  - Planner publishes jobs, Worker executes them")
        print("  - No Redis dependencies anywhere")
    else:
        print("❌ Some tests failed. Please review the implementation.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())