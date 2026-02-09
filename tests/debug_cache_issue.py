#!/usr/bin/env python3
"""Debug cache issue."""

import os
import sys
import tempfile
from pathlib import Path

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.workflows.ingestion.discovery.cache import DiscoveryCacheManager
from src.backends.storage.cache.ingestion.manager import IngestionCacheManager

def debug_cache_issue():
    """Debug the cache issue."""
    print("=== Debugging Cache Issue ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        # Create test directory
        test_dir = tmpdir_path / "test"
        test_dir.mkdir()
        
        # Create test files
        (test_dir / "file1.py").write_text("print('Hello World')")
        (test_dir / "file2.md").write_text("# Documentation")
        (test_dir / "file3.txt").write_text("Plain text")
        
        # Create a subdirectory
        subdir = test_dir / "subdir"
        subdir.mkdir()
        (subdir / "file4.py").write_text("def test(): pass")
        
        print(f"Test directory: {test_dir}")
        print(f"Files created: {list(test_dir.rglob('*'))}")
        
        # Initialize cache manager
        cache_manager = IngestionCacheManager()
        discovery_cache = DiscoveryCacheManager(cache_manager=cache_manager)
        
        # Test 1: Get directory hash
        print("\n1. Getting directory hash...")
        hash1 = discovery_cache.get_dir_hash(str(test_dir))
        print(f"   Hash: {hash1}")
        
        # Test 2: Cache directory
        print("\n2. Caching directory...")
        files = [
            str(test_dir / "file1.py"),
            str(test_dir / "file2.md"),
            str(test_dir / "file3.txt"),
            str(test_dir / "subdir" / "file4.py")
        ]
        discovery_cache.cache_directory(str(test_dir), files, "test_hash")
        
        # Test 3: Check if directory is unchanged
        print("\n3. Checking if directory is unchanged...")
        cached = discovery_cache.is_dir_unchanged(str(test_dir), "test_hash")
        if cached:
            print(f"   Cache hit! Found {len(cached.files)} files")
            print(f"   Files: {cached.files}")
        else:
            print("   Cache miss")
        
        # Test 4: Modify a file
        print("\n4. Modifying file1.py...")
        (test_dir / "file1.py").write_text("print('Hello World Modified')")
        
        # Test 5: Check again
        print("\n5. Checking after modification...")
        cached2 = discovery_cache.is_dir_unchanged(str(test_dir), "test_hash")
        if cached2:
            print(f"   Cache hit! Found {len(cached2.files)} files")
            print(f"   Files: {cached2.files}")
        else:
            print("   Cache miss (expected)")
        
        # Test 6: Get new hash
        print("\n6. Getting new directory hash...")
        hash2 = discovery_cache.get_dir_hash(str(test_dir))
        print(f"   New hash: {hash2}")
        print(f"   Hashes different? {hash1 != hash2}")
        
        # Test 7: Check cache stats
        print("\n7. Cache stats:")
        stats = discovery_cache.get_stats()
        for key, value in stats.items():
            print(f"   {key}: {value}")

if __name__ == "__main__":
    debug_cache_issue()