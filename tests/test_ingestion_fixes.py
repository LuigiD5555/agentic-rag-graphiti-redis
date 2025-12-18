#!/usr/bin/env python3
"""
Test script to verify that ingestion-related fixes work correctly.

This script verifies:
1. That default exclusions are active
2. That file ordering is ascending (small to large)
3. That PDF/CSV limits are configured correctly
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingestion.helpers import build_ingestion_options_from_args
from src.ingestion.loaders.pdf_loader import PDFLoader
from src.ingestion.loaders.csv_loader import CSVLoader
from src.utils.file_operations import sort_paths_by_size_desc
from src.settings import _DEFAULT_EXCLUDED_FILES
import argparse


def test_exclusions():
    """Verify that default exclusions are active."""
    print("\n" + "="*80)
    print("TEST 1: Verifying default exclusions")
    print("="*80)

    # Simulate args without explicit exclusions
    args = argparse.Namespace(
        paths=["/mnt/Documents"],
        exts=None,
        exclude_dirs=None,
        exclude_patterns=None,
        enabled_paths=None,
        follow_symlinks=False,
        dry_run=False,
        per_file=False,
        max_files=0,
        log_level="INFO",
        scan_progress=0
    )

    # Simulate config without exclusions
    class MockConfig:
        DOCS_PATHS = ["/mnt/Documents"]
        DOCS_FILE_EXTS = [".pdf", ".txt"]
        DOCS_EXCLUDE_DIRS = ()
        DOCS_EXCLUDE_GLOBS = ()
        DOCS_ENABLED_PATHS = ()
        DOCS_FOLLOW_SYMLINKS = False
        INGEST_LOG_LEVEL = "INFO"

    options = build_ingestion_options_from_args(args, MockConfig())

    print(f"\nActive exclusions: {len(options.excluded_directory_names)} directories")
    print(f"  Sample: {sorted(list(options.excluded_directory_names))[:10]}")

    # Verify that critical defaults are present
    critical_excludes = {"node_modules", ".git", "__pycache__", "venv", ".venv"}
    missing = critical_excludes - options.excluded_directory_names

    if missing:
        print(f"\nERROR: missing critical exclusions: {missing}")
        return False
    else:
        print("\nSUCCESS: all critical exclusions are active")
        return True


def test_file_order():
    """Verify that file ordering is ascending."""
    print("\n" + "="*80)
    print("TEST 2: Verifying file order (ascending)")
    print("="*80)

    # Create simulated test files
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create files with different sizes
        files = []
        for name, size in [("big.txt", 1000), ("small.txt", 10), ("medium.txt", 100)]:
            path = os.path.join(tmpdir, name)
            with open(path, "w") as f:
                f.write("x" * size)
            files.append(path)

        # Sort
        sorted_files = sort_paths_by_size_desc(files)

        # Verify order
        sizes = [os.path.getsize(f) for f in sorted_files]
        print(f"\nSorted files:")
        for path, size in zip(sorted_files, sizes):
            print(f"  {os.path.basename(path)}: {size} bytes")

        # Verify that order is ascending
        is_ascending = all(sizes[i] <= sizes[i+1] for i in range(len(sizes)-1))

        if is_ascending:
            print("\nSUCCESS: ascending order is correct (small to large)")
            return True
        else:
            print("\nERROR: ascending order is not correct")
            return False


def test_pdf_limits():
    """Verify that PDFLoader limits are configured."""
    print("\n" + "="*80)
    print("TEST 3: Verifying PDFLoader limits")
    print("="*80)

    print(f"\nPDF size limit: {PDFLoader.MAX_PDF_SIZE_BYTES / (1024*1024):.1f} MB")
    print(f"Load timeout: {PDFLoader.LOAD_TIMEOUT_SECONDS} seconds")

    expected_size = 500 * 1024 * 1024  # 500 MB
    expected_timeout = 300  # 5 minutes

    if PDFLoader.MAX_PDF_SIZE_BYTES == expected_size:
        print("Size limit is correct")
        size_ok = True
    else:
        print(f"Size limit is incorrect: expected {expected_size}, found {PDFLoader.MAX_PDF_SIZE_BYTES}")
        size_ok = False

    if PDFLoader.LOAD_TIMEOUT_SECONDS == expected_timeout:
        print("Timeout is correct")
        timeout_ok = True
    else:
        print(f"Timeout is incorrect: expected {expected_timeout}, found {PDFLoader.LOAD_TIMEOUT_SECONDS}")
        timeout_ok = False

    if size_ok and timeout_ok:
        print("\nSUCCESS: PDF limits are configured correctly")
        return True
    else:
        print("\nERROR: PDF limits are not configured correctly")
        return False


def test_csv_limits():
    """Verify that CSVLoader limits are configured."""
    print("\n" + "="*80)
    print("TEST 4: Verifying CSVLoader limits")
    print("="*80)

    print(f"\nRow limit: {CSVLoader.MAX_ROWS:,}")
    print(f"File size limit: {CSVLoader.MAX_FILE_SIZE_BYTES / (1024*1024):.1f} MB")

    expected_rows = 50000
    expected_size = 150 * 1024 * 1024  # 150 MB

    if CSVLoader.MAX_ROWS == expected_rows:
        print("Row limit is correct")
        rows_ok = True
    else:
        print(f"Row limit is incorrect: expected {expected_rows}, found {CSVLoader.MAX_ROWS}")
        rows_ok = False

    if CSVLoader.MAX_FILE_SIZE_BYTES == expected_size:
        print("File size limit is correct")
        size_ok = True
    else:
        print(f"File size limit is incorrect: expected {expected_size}, found {CSVLoader.MAX_FILE_SIZE_BYTES}")
        size_ok = False

    if rows_ok and size_ok:
        print("\nSUCCESS: CSV limits are configured correctly")
        return True
    else:
        print("\nERROR: CSV limits are not configured correctly")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("VERIFICATION OF INGESTION FIXES")
    print("="*80)

    results = []
    results.append(("Default exclusions", test_exclusions()))
    results.append(("File order", test_file_order()))
    results.append(("PDF limits", test_pdf_limits()))
    results.append(("CSV limits", test_csv_limits()))

    # Summary
    print("\n" + "="*80)
    print("SUMMARY OF RESULTS")
    print("="*80)

    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"{status}: {name}")

    all_passed = all(passed for _, passed in results)
    print("\n" + "="*80)
    if all_passed:
        print("ALL TESTS PASSED - system is ready for ingestion")
    else:
        print("SOME TESTS FAILED - review configuration")
    print("="*80 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
