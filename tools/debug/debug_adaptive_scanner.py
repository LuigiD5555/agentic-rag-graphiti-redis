#!/usr/bin/env python3
"""Debug script for AdaptiveHybridScanner."""

import os
import tempfile
import time

from src.workflows.ingestion.discovery.adaptive_scanner import AdaptiveHybridScanner, SchedulerPolicy
from src.workflows.ingestion.discovery.cache import DiscoveryCacheManager
from src.workflows.ingestion.discovery.pattern_matching import PatternMatcher
from src.workflows.ingestion.discovery.filters import build_filters
from src.workflows.ingestion.options import DiscoveryOptions

def create_test_directory_structure():
    """Create a test directory structure for scanning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some directories and files
        os.makedirs(os.path.join(tmpdir, "dir1", "subdir1"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "dir2"), exist_ok=True)
        
        # Create some test files
        test_files = [
            os.path.join(tmpdir, "file1.txt"),
            os.path.join(tmpdir, "file2.md"),
            os.path.join(tmpdir, "dir1", "file3.txt"),
            os.path.join(tmpdir, "dir1", "subdir1", "file4.txt"),
            os.path.join(tmpdir, "dir2", "file5.py"),
        ]
        
        for file_path in test_files:
            with open(file_path, "w") as f:
                f.write(f"Test content for {file_path}")
        
        return tmpdir

def debug_scanner():
    """Debug the adaptive scanner functionality."""
    print("Debugging AdaptiveHybridScanner...")
    
    # Create test directory
    test_root = create_test_directory_structure()
    print(f"Created test directory: {test_root}")
    
    # List directory contents
    print("\nDirectory structure:")
    for root, dirs, files in os.walk(test_root):
        level = root.replace(test_root, '').count(os.sep)
        indent = ' ' * 2 * level
        print(f'{indent}{os.path.basename(root)}/')
        subindent = ' ' * 2 * (level + 1)
        for file in files:
            print(f'{subindent}{file}')
    
    # Initialize components
    cache_manager = DiscoveryCacheManager()
    pattern_matcher = PatternMatcher()
    
    # Create scanner
    scanner = AdaptiveHybridScanner(
        cache_manager=cache_manager,
        pattern_matcher=pattern_matcher,
        scheduler_policy=SchedulerPolicy.DFS,
        enable_parallel=False,
        max_workers=2
    )
    
    # Create discovery options
    opts = DiscoveryOptions(
        roots=(test_root,),
        allowed_exts={".txt", ".md", ".py"},
        excluded_dirs=set(),
        excluded_globs=set(),
        follow_symlinks=False,
        progress_every=10
    )
    
    # Build filters
    filters = build_filters(opts, pattern_matcher)
    print(f"\nNumber of filters: {len(filters)}")
    
    # Scan directory
    files = []
    start_time = time.time()
    
    print("\nStarting scan...")
    dirs_scanned, run_id = scanner.scan_directory(
        root=test_root,
        filters=filters,
        excluded_globs=opts.excluded_globs,
        follow_symlinks=opts.follow_symlinks,
        files=files,
        progress_every=opts.progress_every,
        options_hash=cache_manager.compute_options_hash(opts)
    )
    
    elapsed = time.time() - start_time
    
    print(f"\nScan completed:")
    print(f"  Run ID: {run_id}")
    print(f"  Directories scanned: {dirs_scanned}")
    print(f"  Files found: {len(files)}")
    print(f"  Time elapsed: {elapsed:.2f} seconds")
    
    if files:
        print("\nFound files:")
        for i, file_path in enumerate(sorted(files), 1):
            print(f"  {i}. {os.path.relpath(file_path, test_root)}")
    else:
        print("\nNo files found!")

        # Let's manually check what should be found
        expected_relpaths = [
            "file1.txt",
            "file2.md",
            os.path.join("dir1", "file3.txt"),
            os.path.join("dir1", "subdir1", "file4.txt"),
            os.path.join("dir2", "file5.py"),
        ]
        print("\nExpected files (manual check):")
        for i, relpath in enumerate(expected_relpaths, 1):
            print(f"  {i}. {relpath}")


if __name__ == "__main__":
    debug_scanner()
