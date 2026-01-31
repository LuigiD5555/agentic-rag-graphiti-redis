#!/usr/bin/env python3
"""Test script to verify checkpoint fix for scanning."""

import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.workflows.ingestion.orchestrator import IngestionOrchestrator
from src.workflows.ingestion.options import IngestionOptions
from src.backends.storage.sqlite.manager import get_sqlite_manager

def test_checkpoint_system():
    """Test that checkpoint system prevents re-scanning."""
    print("=== Testing Checkpoint System ===")
    
    # Initialize orchestrator
    orchestrator = IngestionOrchestrator()
    
    # Create test options
    test_dir = "/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills"
    if not os.path.exists(test_dir):
        print(f"Test directory not found: {test_dir}")
        print("Using current directory instead...")
        test_dir = "."
    
    opts = IngestionOptions(
        root_paths=[test_dir],
        allowed_extensions=['.py', '.md', '.txt'],
        excluded_directory_names=['node_modules', '.git', '__pycache__'],
        excluded_path_globs=['*.log', '*.tmp']
    )
    
    print(f"\n1. First scan (should scan everything)...")
    start_time = time.time()
    result1 = orchestrator.run_incremental_scan(opts)
    elapsed1 = time.time() - start_time
    
    print(f"   First scan: {result1.get('discovery', {}).get('changed_files', 0)} files, {elapsed1:.2f}s")
    
    print(f"\n2. Second scan (should use cache/checkpoints)...")
    start_time = time.time()
    result2 = orchestrator.run_incremental_scan(opts)
    elapsed2 = time.time() - start_time
    
    print(f"   Second scan: {result2.get('discovery', {}).get('changed_files', 0)} files, {elapsed2:.2f}s")
    
    # Check SQLite for scan runs
    sqlite_manager = get_sqlite_manager()
    with sqlite_manager.control_plane.get_connection() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM scan_runs")
        scan_runs_count = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT COUNT(*) FROM scan_visited")
        visited_dirs_count = cursor.fetchone()[0]
        
        cursor = conn.execute("SELECT COUNT(*) FROM scan_files")
        scanned_files_count = cursor.fetchone()[0]
    
    print(f"\n3. SQLite Checkpoint Stats:")
    print(f"   - Scan runs: {scan_runs_count}")
    print(f"   - Visited directories: {visited_dirs_count}")
    print(f"   - Scanned files: {scanned_files_count}")
    
    # Check if second scan was faster (should be)
    if elapsed2 < elapsed1 * 0.5:  # Second scan should be at least 2x faster
        print(f"\n✓ SUCCESS: Second scan was {elapsed1/elapsed2:.1f}x faster (checkpoints working)")
    else:
        print(f"\n⚠ WARNING: Second scan was only {elapsed1/elapsed2:.1f}x faster")
        print("   Checkpoints may not be working optimally")
    
    # Check scan_run_id
    scan_run_id = result2.get('scan_run_id')
    if scan_run_id:
        print(f"✓ Scan run ID persisted: {scan_run_id}")
    else:
        print("⚠ No scan run ID returned")
    
    return result1, result2

def test_cache_hit_rate():
    """Test cache hit rate statistics."""
    print("\n=== Testing Cache Hit Rate ===")
    
    from src.workflows.ingestion.orchestrator import IngestionOrchestrator
    from src.workflows.ingestion.options import IngestionOptions
    
    orchestrator = IngestionOrchestrator()
    
    test_dir = "."
    opts = IngestionOptions(
        root_paths=[test_dir],
        allowed_extensions=['.py'],
        excluded_directory_names=['node_modules', '.git', '__pycache__']
    )
    
    # Run discovery twice
    discovery_opts = orchestrator._to_discovery_options(opts)
    
    # First discovery
    print("1. First discovery...")
    files1, dirs1 = orchestrator._discovery.discover(discovery_opts, use_cache=True)
    stats1 = orchestrator._discovery.get_cache_stats()
    print(f"   Files: {len(files1)}, Dirs: {dirs1}")
    print(f"   Cache hits: {stats1['cache']['cache_hits']}, misses: {stats1['cache']['cache_misses']}")
    
    # Second discovery (should have more cache hits)
    print("\n2. Second discovery (should have cache hits)...")
    files2, dirs2 = orchestrator._discovery.discover(discovery_opts, use_cache=True)
    stats2 = orchestrator._discovery.get_cache_stats()
    print(f"   Files: {len(files2)}, Dirs: {dirs2}")
    print(f"   Cache hits: {stats2['cache']['cache_hits']}, misses: {stats2['cache']['cache_misses']}")
    
    hit_rate = stats2['cache']['hit_rate']
    if hit_rate > 50:  # Should have >50% hit rate on second run
        print(f"✓ Good cache hit rate: {hit_rate:.1f}%")
    else:
        print(f"⚠ Low cache hit rate: {hit_rate:.1f}%")

if __name__ == "__main__":
    print("Testing checkpoint fix for scanning issue...")
    print("=" * 60)
    
    try:
        test_checkpoint_system()
        print("\n" + "=" * 60)
        test_cache_hit_rate()
        print("\n" + "=" * 60)
        print("Test completed successfully!")
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)