#!/usr/bin/env python3
"""Test script to verify ingestion handles volume failures gracefully."""

import os
import sys
import tempfile
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

def test_volume_detection():
    """Test the volume detection logic."""
    print("=== Testing Volume Detection ===")
    
    from src.workflows.ingestion.helpers import _detect_available_volumes
    
    volumes = _detect_available_volumes()
    print(f"Detected volumes: {volumes}")
    
    # Check that paths are accessible
    for vol in volumes:
        if os.path.exists(vol):
            print(f"✓ Volume {vol} exists")
            try:
                os.listdir(vol)
                print(f"  ✓ Can list directory")
            except Exception as e:
                print(f"  ✗ Cannot list directory: {e}")
        else:
            print(f"✗ Volume {vol} does not exist")
    
    return len(volumes) > 0

def test_discovery_service():
    """Test the discovery service with multiple paths."""
    print("\n=== Testing Discovery Service ===")
    
    from src.workflows.ingestion.discovery.service import FileDiscoveryService
    from src.workflows.ingestion.options import DiscoveryOptions
    
    # Create a temporary directory with some test files
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        test_files = [
            "test1.pdf",
            "test2.txt",
            "test3.md"
        ]
        
        for fname in test_files:
            with open(os.path.join(tmpdir, fname), 'w') as f:
                f.write(f"Test content for {fname}")
        
        print(f"Created test directory: {tmpdir}")
        print(f"Test files: {test_files}")
        
        # Test with one good path and one bad path
        discovery = FileDiscoveryService()
        
        opts = DiscoveryOptions(
            roots=[tmpdir, "/non/existent/path/123456"],  # One good, one bad
            enabled_paths=[],
            allowed_exts={'.pdf', '.txt', '.md'},
            excluded_dirs=set(),
            excluded_globs=set(),
            follow_symlinks=False,
            progress_every=0
        )
        
        files, visited_dirs = discovery.discover(opts, use_cache=False)
        
        print(f"\nDiscovery results:")
        print(f"  Found {len(files)} files")
        print(f"  Visited {visited_dirs} directories")
        
        if files:
            print("  Files found:")
            for f in files:
                print(f"    - {f}")
        
        # Should find files from good path even though bad path fails
        assert len(files) == 3, f"Expected 3 files, found {len(files)}"
        print("✓ Discovery service correctly handled non-existent path")
        
        return True

def test_build_ingestion_options():
    """Test building ingestion options from config."""
    print("\n=== Testing Ingestion Options Building ===")
    
    from src.workflows.ingestion.helpers import build_ingestion_options_from_args
    from src.conf import settings
    
    # Mock args object
    class MockArgs:
        paths = None
        exts = None
        exclude_dirs = None
        exclude_patterns = None
        enabled_paths = None
        follow_symlinks = False
        dry_run = False
        per_file = False
        max_files = 0
        streaming = None
        log_level = None
        scan_progress = 0
        strategy = None
        phased_ingestion = None
        max_ram_percent = None
        run_id = None
    
    args = MockArgs()
    
    # Build options using current settings
    options = build_ingestion_options_from_args(args, settings)
    
    print(f"Root paths: {options.root_paths}")
    print(f"Allowed extensions: {options.allowed_extensions}")
    print(f"Excluded directories: {options.excluded_directory_names}")
    
    # Check that we have paths
    assert len(options.root_paths) > 0, "Should have at least one root path"
    print(f"✓ Built ingestion options with {len(options.root_paths)} root paths")
    
    # Check that paths from DOCS_PATHS are included
    docs_paths = getattr(settings, 'DOCS_PATHS', [])
    for path in docs_paths:
        if path in options.root_paths:
            print(f"✓ DOCS_PATHS entry '{path}' is in root paths")
    
    return True

def main():
    """Run all tests."""
    print("Testing ingestion system robustness...")
    print("=" * 50)
    
    tests_passed = 0
    tests_total = 3
    
    try:
        if test_volume_detection():
            tests_passed += 1
    except Exception as e:
        print(f"✗ Volume detection test failed: {e}")
    
    try:
        if test_discovery_service():
            tests_passed += 1
    except Exception as e:
        print(f"✗ Discovery service test failed: {e}")
    
    try:
        if test_build_ingestion_options():
            tests_passed += 1
    except Exception as e:
        print(f"✗ Ingestion options test failed: {e}")
    
    print("\n" + "=" * 50)
    print(f"Test results: {tests_passed}/{tests_total} tests passed")
    
    if tests_passed == tests_total:
        print("✓ All tests passed! Ingestion system should handle volume failures gracefully.")
        return 0
    else:
        print("✗ Some tests failed. Review the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
