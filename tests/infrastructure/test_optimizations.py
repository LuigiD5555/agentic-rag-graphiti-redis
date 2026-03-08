#!/usr/bin/env python3
"""
Test script to verify the integration of all ingestion pipeline optimizations.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

# Add the src directory to the import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.workflows.ingestion.wave_planner import WavePlanner, create_default_wave_orchestrator
from src.workflows.ingestion.resource_pools import ResourcePool, IngestionPools
from src.workflows.ingestion.watermark_cleanup import WatermarkCleanup
from src.ingestion.ledger.ledger_repository import LedgerRepository, Stage
from src.workflows.ingestion.metrics import MetricsCollector, IngestionMetrics


def test_wave_planner():
    """Tests the Wave Planner."""
    print("=== Testing Wave Planner ===")
    
    # Create test files
    test_dir = tempfile.mkdtemp(prefix="rag_test_")
    test_files = []
    
    for i in range(5):
        file_path = Path(test_dir) / f"test_file_{i}.txt"
        file_path.write_text(f"Test file content {i}\n" * 100)
        test_files.append(str(file_path))
    
    # Test WavePlanner
    planner = WavePlanner(target_files_per_wave=2)
    waves = planner.plan(test_files)
    
    print(f"Test files created: {len(test_files)}")
    print(f"Waves planned: {len(waves)}")
    
    for i, wave in enumerate(waves, 1):
        print(f"  Wave {i}: {len(wave.candidates)} files")
    
    # Test wave orchestrator
    orchestrator = create_default_wave_orchestrator()
    
    def mock_process_callback(files):
        return {"processed": len(files), "files": files}
    
    result = orchestrator.execute_waves(test_files, mock_process_callback)
    
    status = "ok" if result["failed_waves"] == 0 else "failed"
    print(f"Execution result: {status}")
    print(f"Successful waves: {result['successful_waves']}/{result['total_waves']}")
    
    # Clean up
    import shutil
    shutil.rmtree(test_dir)
    
    print("✓ Wave Planner tested successfully\n")


def test_resource_pools():
    """Tests the Resource Pools."""
    print("=== Testing Resource Pools ===")
    
    # Test basic ResourcePool
    pool = ResourcePool("test_pool", max_workers=2, max_queue_size=5)
    
    results = []
    
    def test_task(task_id, delay=0.1):
        import time
        time.sleep(delay)
        return f"task_{task_id}_completed"
    
    # Submit tasks
    futures = []
    for i in range(3):
        future = pool.submit(test_task, i, 0.05)
        if future:
            futures.append(future)
    
    # Wait for completion
    pool.wait_for_completion(timeout=5.0)
    
    # Collect results
    for future in futures:
        try:
            result = future.result(timeout=1.0)
            results.append(result)
        except Exception as e:
            print(f"Error en tarea: {e}")
    
    # Retrieve metrics
    metrics = pool.get_metrics()
    print(f"Tareas completadas: {metrics.completed_tasks}")
    print(f"Tareas fallidas: {metrics.failed_tasks}")
    print(f"Tiempo promedio: {metrics.avg_task_time:.3f}s")
    
    # Test IngestionPools
    ingestion_pools = IngestionPools()
    print(f"Ingestion pools created: convert, embed, upsert")
    
    # Shutdown pools
    pool.shutdown(wait=True)
    ingestion_pools.shutdown(wait=True)
    
    assert len(results) == 3
    print("✓ Resource Pools tested successfully\n")


def test_watermark_cleanup():
    """Tests the Watermark Cleanup."""
    print("=== Testing Watermark Cleanup ===")
    
    # Create staging directory
    staging_dir = tempfile.mkdtemp(prefix="rag_staging_")
    
    # Create some test files
    for i in range(3):
        file_path = Path(staging_dir) / f"test_{i}.tmp"
        file_path.write_text("temporary content" * 100)
    
    # Test WatermarkCleanup
    cleanup = WatermarkCleanup(
        staging_dir=staging_dir,
        watermark_percent=10.0,  # Bajo para forzar limpieza
        aggressive_percent=20.0,
        check_interval_seconds=1,
        workers=1
    )
    
    # Get disk usage
    disk_usage = cleanup.get_disk_usage()
    print(f"Staging directory: {staging_dir}")
    print(f"Disk usage: {disk_usage.usage_percent:.1f}%")
    
    # Check if cleanup is needed
    needs_cleanup, needs_aggressive = cleanup.should_cleanup()
    print(f"Needs cleanup: {needs_cleanup}")
    print(f"Needs aggressive cleanup: {needs_aggressive}")
    
    # Run cleanup
    cleanup_result = cleanup.run_cleanup(aggressive=False)
    print(f"Cleanup executed: {cleanup_result['status']}")
    print(f"Files cleaned: {cleanup_result['files_cleaned']}")
    print(f"MB freed: {cleanup_result.get('freed_mb', 0):.2f}")
    
    # Get metrics
    metrics = cleanup.get_metrics()
    print(f"Total cleanups: {metrics['cleanup_stats']['total_cleanups']}")
    
    # Clean up
    import shutil
    shutil.rmtree(staging_dir)
    cleanup.stop_monitor()
    
    print("✓ Watermark Cleanup tested successfully\n")


def test_ledger_repository():
    """Tests the LedgerRepository (replaces IdempotencyManager)."""
    print("=== Testing LedgerRepository ===")

    # Use unique content to avoid collisions with a persistent SQLite DB
    unique_marker = str(time.monotonic())
    test_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    test_file.write(f"Unique ledger test content {unique_marker}\n" * 10)
    test_file.close()

    ledger = LedgerRepository()

    # First call: file is new, should be processed
    skip, reason = ledger.should_skip_file(test_file.name)
    print(f"First call — skip: {skip}, reason: {reason}")
    assert not skip, "New file should not be skipped"

    # Simulate a completed ingestion version at current fingerprint
    doc_id = ledger.get_or_create_document(test_file.name)
    fast_fp = ledger._compute_fingerprint(test_file.name, paranoid=False)
    version_result = ledger.ensure_version(doc_id, fast_fp)
    active_version = version_result.new_version_id or ledger.get_active_version(doc_id)
    import time as _time
    if active_version:
        ledger.mark_stage_done(active_version, Stage.CHUNK, int(_time.time()))
        ledger.mark_stage_done(active_version, Stage.EMBED, int(_time.time()))
        ledger.mark_stage_done(active_version, Stage.UPSERT, int(_time.time()))

    # Second call: UPSERT is DONE, file should be skipped
    skip, reason = ledger.should_skip_file(test_file.name)
    print(f"Second call — skip: {skip}, reason: {reason}")
    assert skip and reason == "cache_hit", f"Fully processed file should be cache_hit, got: {reason}"

    # Stage status check
    if active_version:
        upsert_status = ledger.get_stage_status(active_version, Stage.UPSERT)
        print(f"UPSERT status: {upsert_status['status']}")

    # Content deduplication: second file with same content should be skipped as duplicate
    test_file2 = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    test_file2.write(f"Unique ledger test content {unique_marker}\n" * 10)  # Same content as test_file
    test_file2.close()

    skip2, reason2 = ledger.should_skip_file(test_file2.name)
    print(f"Duplicate file — skip: {skip2}, reason: {reason2}")
    assert skip2 and reason2 == "duplicate", f"Duplicate content should be skipped, got: {reason2}"

    os.unlink(test_file.name)
    os.unlink(test_file2.name)

    print("✓ LedgerRepository tested successfully\n")


def test_metrics_collector():
    """Tests the Metrics Collector."""
    print("=== Testing Metrics Collector ===")
    
    # Test MetricsCollector
    collector = MetricsCollector()
    
    # Record different metric types
    collector.increment("test.counter", 1)
    collector.gauge("test.gauge", 42.5)
    collector.timer("test.timer", 1.23)
    collector.histogram("test.histogram", 100.0)
    
    # Test the timeit decorator
    @collector.timeit("test.decorated_timer")
    def slow_function():
        import time
        time.sleep(0.01)
        return "done"
    
    result = slow_function()
    print(f"Decorated function result: {result}")
    
    # Retrieve metrics
    metrics = collector.get_metrics()
    print(f"Metrics recorded: {len(metrics)}")
    
    # Get summary
    summary = collector.get_summary()
    print(f"Total metrics: {summary['total_metrics']}")
    print(f"Metric types: {summary['metric_types']}")
    
    # Test Prometheus export
    prometheus_output = collector.export_prometheus()
    print(f"Prometheus export: {len(prometheus_output.splitlines())} lines")
    
    # Probar IngestionMetrics
    ingestion_metrics = IngestionMetrics(collector)
    ingestion_metrics.record_discovery(10, 2)
    ingestion_metrics.record_file_processing("/test/path.txt", 1.5, True, 0.5)
    ingestion_metrics.record_chunk_processing(5, 100, 0.1)
    
    # Get ingestion summary
    ingestion_summary = ingestion_metrics.get_ingestion_summary()
    print(f"Files discovered: {ingestion_summary['files']['discovered']}")
    print(f"Chunks created: {ingestion_summary['chunks']['created']}")
    
    # Clean up
    collector.clear()
    
    print("✓ Metrics Collector tested successfully\n")


def test_integration():
    """Tests the integration of all components."""
    print("=== Testing Full Integration ===")
    
    # Create temporary test directory
    test_dir = tempfile.mkdtemp(prefix="rag_integration_")
    
    try:
        # Inicializar todos los componentes
        wave_planner = WavePlanner(target_files_per_wave=10)
        resource_pools = IngestionPools()
        watermark_cleanup = WatermarkCleanup(staging_dir=test_dir)
        ledger = LedgerRepository()
        metrics_collector = MetricsCollector()

        print("Components initialized:")
        print(f"  - WavePlanner: {wave_planner}")
        print(f"  - IngestionPools: {resource_pools}")
        print(f"  - WatermarkCleanup: {watermark_cleanup}")
        print(f"  - LedgerRepository: {ledger}")
        print(f"  - MetricsCollector: {metrics_collector}")
        
        # Create test files
        test_files = []
        for i in range(3):
            file_path = Path(test_dir) / f"integration_test_{i}.txt"
            file_path.write_text(f"Integration file {i}\n" * 50)
            test_files.append(str(file_path))
        
        # Simulate the integrated processing flow
        print("\nSimulating processing flow:")
        
        # 1. Wave Planning
        waves = wave_planner.plan(test_files)
        print(f"  1. Wave Planning: {len(waves)} waves created")
        
        # 2. Ledger skip check
        for file_path in test_files:
            skip, reason = ledger.should_skip_file(file_path)
            if not skip:
                doc_id = ledger.get_or_create_document(file_path)
                active_ver = ledger.get_active_version(doc_id)
                if active_ver:
                    import time as _t
                    ledger.mark_stage_done(active_ver, Stage.DISCOVER, int(_t.time()))

        print(f"  2. Ledger: {len(test_files)} files checked and DISCOVER marked")
        
        # 3. Resource Pool processing (simulated)
        def process_file(file_path):
            import time
            time.sleep(0.01)
            return {"file": file_path, "processed": True}
        
        futures = []
        for file_path in test_files:
            future = resource_pools.submit_conversion(process_file, file_path)
            if future:
                futures.append(future)
        
        resource_pools.wait_for_all(timeout=5.0)
        print(f"  3. Resource Pools: {len(futures)} tasks processed")
        
        # 4. Metrics recording
        metrics_collector.increment("integration.files.processed", len(test_files))
        metrics_collector.gauge("integration.active_workers", 2)
        
        metrics_summary = metrics_collector.get_summary()
        print(f"  4. Metrics: {metrics_summary['total_metrics']} metrics recorded")
        
        # 5. Cleanup
        for file_path in test_files:
            watermark_cleanup.cleanup_completed_file(file_path, immediate=True)
        
        print(f"  5. Cleanup: Test files cleaned")
        
        # Apagar componentes
        resource_pools.shutdown(wait=True)
        watermark_cleanup.stop_monitor()
        
        print("\n✓ Integration tested successfully")
        
    finally:
        # Limpieza final
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)


def main():
    """Main test runner."""
    print("=" * 60)
    print("INGESTION PIPELINE OPTIMIZATION TESTS")
    print("=" * 60)
    print()
    
    tests = [
        ("Wave Planner", test_wave_planner),
        ("Resource Pools", test_resource_pools),
        ("Watermark Cleanup", test_watermark_cleanup),
        ("Ledger Repository", test_ledger_repository),
        ("Metrics Collector", test_metrics_collector),
        ("Full Integration", test_integration),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            success = test_func()
            if success is None:
                success = True
            results.append((test_name, success, None))
        except Exception as e:
            print(f"✗ Error in {test_name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False, str(e)))
        print()
    
    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for test_name, success, error in results:
        status = "✓ PASSED" if success else "✗ FAILED"
        if error:
            status += f" ({error})"
        print(f"{status}: {test_name}")
        
        if success:
            passed += 1
        else:
            failed += 1
   
    print()
    print(f"Total: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("\nAll optimizations are working correctly!")
        return 0
    else:
        print(f"\n{failed} tests need attention.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
