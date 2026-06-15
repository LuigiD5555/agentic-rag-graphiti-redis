#!/usr/bin/env python3
"""Verification script for AdaptiveHybridScanner.

This is a standalone script (not collected by pytest) to quickly sanity-check
scanner behavior on a temporary directory tree.
"""

import os
import shutil
import tempfile
import time

from src.workflows.ingestion.discovery.adaptive_scanner import AdaptiveHybridScanner, SchedulerPolicy
from src.workflows.ingestion.discovery.cache import DiscoveryCacheManager
from src.workflows.ingestion.discovery.pattern_matching import PatternMatcher
from src.workflows.ingestion.discovery.filters import build_filters
from src.workflows.ingestion.options import DiscoveryOptions

def create_test_directory_structure() -> str:
    """Create and return a temporary test directory tree."""
    tmpdir = tempfile.mkdtemp(prefix="adaptive_scanner_")

    os.makedirs(os.path.join(tmpdir, "dir1", "subdir1"), exist_ok=True)
    os.makedirs(os.path.join(tmpdir, "dir2"), exist_ok=True)

    test_files = [
        os.path.join(tmpdir, "file1.txt"),
        os.path.join(tmpdir, "file2.md"),
        os.path.join(tmpdir, "dir1", "file3.txt"),
        os.path.join(tmpdir, "dir1", "subdir1", "file4.txt"),
        os.path.join(tmpdir, "dir2", "file5.py"),
    ]

    for file_path in test_files:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"Test content for {file_path}\n")

    return tmpdir

def verify_adaptive_scanner():
    """Verify the adaptive scanner functionality."""
    print("Testing AdaptiveHybridScanner...")
    
    # Create test directory
    test_root = create_test_directory_structure()
    print(f"Created test directory: {test_root}")
    
    try:
        cache_manager = DiscoveryCacheManager()
        pattern_matcher = PatternMatcher()

        opts = DiscoveryOptions(
            roots=[test_root],
            allowed_exts=[".txt", ".md", ".py"],
            excluded_dirs=[],
            excluded_globs=set(),
            follow_symlinks=False,
            progress_every=10,
        )
        filters = build_filters(opts, pattern_matcher)
        expected_files = 5

        for policy in [SchedulerPolicy.DFS, SchedulerPolicy.BFS, SchedulerPolicy.PRIORITY]:
            print(f"\nTesting with scheduler policy: {policy.value}")

            scanner = AdaptiveHybridScanner(
                cache_manager=cache_manager,
                pattern_matcher=pattern_matcher,
                scheduler_policy=policy,
                enable_parallel=False,
                max_workers=2,
            )

            files = []
            start_time = time.time()

            dirs_scanned, run_id = scanner.scan_directory(
                root=test_root,
                filters=filters,
                excluded_globs=opts.excluded_globs,
                follow_symlinks=opts.follow_symlinks,
                files=files,
                progress_every=opts.progress_every,
                options_hash=cache_manager.compute_options_hash(opts),
            )

            elapsed = time.time() - start_time

            print(f"  Run ID: {run_id}")
            print(f"  Directories scanned: {dirs_scanned}")
            print(f"  Files found: {len(files)}")
            print(f"  Time elapsed: {elapsed:.2f} seconds")

            if len(files) == expected_files:
                print(f"  ✓ Found all {expected_files} test files")
            else:
                print(f"  ✗ Expected {expected_files} files, found {len(files)}")

            for i, file_path in enumerate(sorted(files), 1):
                print(f"    {i}. {os.path.relpath(file_path, test_root)}")

        print("\nTesting parallel scanning...")

        scanner = AdaptiveHybridScanner(
            cache_manager=cache_manager,
            pattern_matcher=pattern_matcher,
            scheduler_policy=SchedulerPolicy.PRIORITY,
            enable_parallel=True,
            max_workers=2,
        )

        files = []
        start_time = time.time()

        dirs_scanned, run_id = scanner.scan_directory(
            root=test_root,
            filters=filters,
            excluded_globs=opts.excluded_globs,
            follow_symlinks=opts.follow_symlinks,
            files=files,
            progress_every=opts.progress_every,
            options_hash=cache_manager.compute_options_hash(opts),
        )

        elapsed = time.time() - start_time

        print(f"  Parallel scan completed in {elapsed:.2f} seconds")
        print(f"  Files found: {len(files)}")

        if len(files) == expected_files:
            print("  ✓ Parallel scanning found all test files")
        else:
            print("  ✗ Parallel scanning missed some files")

        print("\nTesting with exclusions...")

        opts_with_exclusions = DiscoveryOptions(
            roots=[test_root],
            allowed_exts=[".txt", ".md", ".py"],
            excluded_dirs=[],
            excluded_globs={"*.py"},
            follow_symlinks=False,
            progress_every=10,
        )

        filters = build_filters(opts_with_exclusions, pattern_matcher)

        scanner = AdaptiveHybridScanner(
            cache_manager=cache_manager,
            pattern_matcher=pattern_matcher,
            scheduler_policy=SchedulerPolicy.PRIORITY,
            enable_parallel=False,
            max_workers=2,
        )

        files = []
        dirs_scanned, run_id = scanner.scan_directory(
            root=test_root,
            filters=filters,
            excluded_globs=opts_with_exclusions.excluded_globs,
            follow_symlinks=opts_with_exclusions.follow_symlinks,
            files=files,
            progress_every=opts_with_exclusions.progress_every,
            options_hash=cache_manager.compute_options_hash(opts_with_exclusions),
        )

        if len(files) == 4:
            print("  ✓ Correctly excluded Python files")
        else:
            print(f"  ✗ Expected 4 files after exclusion, found {len(files)}")

        print("\nAll checks completed!")
    finally:
        shutil.rmtree(test_root, ignore_errors=True)

if __name__ == "__main__":
    verify_adaptive_scanner()
