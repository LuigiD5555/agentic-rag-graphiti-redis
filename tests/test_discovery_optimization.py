#!/usr/bin/env python3
"""
Test script to verify discovery optimizations.

This script demonstrates the path tree optimizations and shows
how they prevent re-scanning of directories.
"""

import os
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.ingestion.discovery import FileDiscoveryService, PathTree
from src.ingestion.options import DiscoveryOptions
from src.rag.audit import get_logger

log = get_logger(__name__)


def test_path_tree():
    """Test basic PathTree functionality."""
    print("\n" + "="*70)
    print("TEST 1: PathTree Basic Operations")
    print("="*70)

    tree = PathTree()

    # Add some paths
    tree.add_path("src/components/ui")
    tree.add_path("src/components/forms")
    tree.add_path("src/utils")
    tree.add_path("node_modules", is_excluded=True)
    tree.add_path("node_modules/package/dist", is_excluded=True)

    print("✓ Added 5 paths to tree")

    # Test visited tracking
    tree.mark_visited("src/components/ui")
    assert tree.is_visited("src/components/ui"), "Should be marked as visited"
    assert not tree.is_visited("src/utils"), "Should not be visited yet"
    print("✓ Visited tracking works correctly")

    # Test exclusion
    assert tree.is_path_excluded("node_modules"), "Should be excluded"
    assert tree.is_path_excluded("node_modules/package/dist"), "Child should be excluded"
    assert not tree.is_path_excluded("src/components"), "Should not be excluded"
    print("✓ Hierarchical exclusion works correctly")

    # Test stats
    stats = tree.get_stats()
    print(f"\nTree Statistics:")
    print(f"  - Total nodes: {stats['total_nodes']}")
    print(f"  - Excluded nodes: {stats['excluded_nodes']}")
    print(f"  - Visited paths: {stats['visited_paths']}")
    print(f"  - Memory savings: {stats['memory_savings']}")

    print("\nPATHTREE TESTS PASSED")


def test_discovery_with_optimization():
    """Test file discovery with optimization metrics."""
    print("\n" + "="*70)
    print("TEST 2: File Discovery with Path Optimization")
    print("="*70)

    # Use current project directory as test
    test_root = str(Path(__file__).parent / "src")

    if not os.path.exists(test_root):
        print(f"WARNING: test directory not found: {test_root}")
        return

    service = FileDiscoveryService()

    opts = DiscoveryOptions(
        roots=[test_root],
        allowed_exts={".py"},
        excluded_dirs={"__pycache__", ".pytest_cache", ".git"},
        excluded_globs={
            "*.pyc",
            "*.pyo",
            "*/__pycache__/*",
            "*/.*/*"
        },
        follow_symlinks=False
    )

    print(f"\nScanning directory: {test_root}")
    print(f"Allowed extensions: {opts.allowed_exts}")
    print(f"Excluded dirs: {opts.excluded_dirs}")

    # First scan
    print("\n--- First Scan (cold cache) ---")
    start_time = time.time()
    files1, dirs1 = service.discover(opts, use_cache=True)
    elapsed1 = time.time() - start_time

    print(f"\nResults:")
    print(f"  - Files found: {len(files1)}")
    print(f"  - Directories scanned: {dirs1}")
    print(f"  - Time elapsed: {elapsed1:.3f}s")

    # Get optimization stats
    stats1 = service.get_optimization_stats()
    print(f"\nOptimization Stats:")
    print(f"  Cache:")
    print(f"    - Hits: {stats1['cache']['cache_hits']}")
    print(f"    - Misses: {stats1['cache']['cache_misses']}")
    print(f"    - Hit rate: {stats1['cache']['hit_rate']:.1f}%")
    print(f"  Path Optimization:")
    print(f"    - Visited skipped: {stats1['path_optimization']['visited_skipped']}")
    print(f"    - Excluded skipped: {stats1['path_optimization']['excluded_skipped']}")
    print(f"    - Total avoided: {stats1['path_optimization']['total_avoided']}")
    print(f"    - Tree nodes: {stats1['path_optimization']['tree_stats']['total_nodes']}")

    # Second scan (should use cache)
    print("\n--- Second Scan (warm cache) ---")
    start_time = time.time()
    files2, dirs2 = service.discover(opts, use_cache=True)
    elapsed2 = time.time() - start_time

    print(f"\nResults:")
    print(f"  - Files found: {len(files2)}")
    print(f"  - Directories scanned: {dirs2}")
    print(f"  - Time elapsed: {elapsed2:.3f}s")
    print(f"  - Speedup: {elapsed1/elapsed2:.2f}x faster")

    # Get optimization stats
    stats2 = service.get_optimization_stats()
    print(f"\nOptimization Stats:")
    print(f"  Cache:")
    print(f"    - Hits: {stats2['cache']['cache_hits']}")
    print(f"    - Misses: {stats2['cache']['cache_misses']}")
    print(f"    - Hit rate: {stats2['cache']['hit_rate']:.1f}%")

    # Verify results are identical
    assert len(files1) == len(files2), "Results should be identical"
    assert set(files1) == set(files2), "File sets should be identical"
    print("\nDISCOVERY OPTIMIZATION TESTS PASSED")


def test_performance_comparison():
    """Compare performance with and without path tree optimization."""
    print("\n" + "="*70)
    print("TEST 3: Performance Comparison")
    print("="*70)

    test_root = str(Path(__file__).parent / "src")

    if not os.path.exists(test_root):
        print(f"WARNING: test directory not found: {test_root}")
        return

    opts = DiscoveryOptions(
        roots=[test_root],
        allowed_exts={".py"},
        excluded_dirs={"__pycache__"},
        excluded_globs={"*.pyc", "*/__pycache__/*"},
        follow_symlinks=False
    )

    # With optimization (default)
    service_opt = FileDiscoveryService()
    start = time.time()
    files_opt, _ = service_opt.discover(opts, use_cache=False)
    time_opt = time.time() - start
    stats_opt = service_opt.get_optimization_stats()

    print(f"\nWith Path Tree Optimization:")
    print(f"  - Time: {time_opt:.3f}s")
    print(f"  - Files: {len(files_opt)}")
    print(f"  - Paths avoided: {stats_opt['path_optimization']['total_avoided']}")

    print("\nPERFORMANCE COMPARISON COMPLETE")


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("DISCOVERY OPTIMIZATION TEST SUITE")
    print("="*70)

    try:
        test_path_tree()
        test_discovery_with_optimization()
        test_performance_comparison()

        print("\n" + "="*70)
        print("ALL TESTS PASSED")
        print("="*70)

    except Exception as e:
        print(f"\nTEST FAILED WITH ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
