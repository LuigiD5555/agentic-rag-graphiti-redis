#!/usr/bin/env python3
"""
Test Suite for RAG Agentic Graphiti

This file provides a convenient way to run all project tests via pytest. It offers options
for different test types:

1. Unit tests (fast, no external dependencies)
2. Integration tests (require external services)
3. All tests

Usage:
    python -m pytest tests/test_suite.py           # Runs all tests by default
    python -m pytest tests/test_suite.py -m unit   # Unit tests only
    python -m pytest tests/test_suite.py -m integration  # Integration tests only (requires RUN_INTEGRATION=1)
    python -m pytest tests/test_suite.py --setup-fallback  # With setup fallback option
"""

import os
import sys
import pytest


def run_unit_tests():
    """Runs only the unit tests."""
    print("=== Running Unit Tests ===")
    print("These tests are fast and do not require external services.")
    print("-" * 50)
    
    # Run tests in the unit/ directory (markers are not consistently applied)
    return pytest.main([
        "tests/unit/",
        "--tb=short",
        "-v",
        "--strict-markers",
        "-ra"
    ])


def run_integration_tests():
    """Runs integration tests (requires RUN_INTEGRATION=1)."""
    if os.getenv("RUN_INTEGRATION") != "1":
        print("ERROR: Integration tests require RUN_INTEGRATION=1")
        print("Run: export RUN_INTEGRATION=1")
        return 1
    
    print("=== Running Integration Tests ===")
    print("These tests may require external services (Weaviate, etc.)")
    print("-" * 50)
    
    # Run tests in the integration/ directory (markers are not consistently applied)
    return pytest.main([
        "tests/integration/",
        "--tb=short",
        "-v",
        "--strict-markers",
        "-ra"
    ])


def run_all_tests():
    """Runs all tests (unit tests by default, integration optional)."""
    print("=== Running All Tests ===")
    print("Note: Integration tests are skipped unless RUN_INTEGRATION=1")
    print("-" * 50)
    
    # Run pytest with the default configuration
    return pytest.main([
        "--tb=short",
        "-v",
        "--strict-markers",
        "-ra"
    ])


def run_tests_with_fallback():
    """Runs tests with the setup-fallback option."""
    print("=== Running Tests with Setup Fallback ===")
    print("Configures fallback directories when volumes are inaccessible")
    print("-" * 50)
    
    return pytest.main([
        "--setup-fallback",
        "--tb=short",
        "-v",
        "--strict-markers",
        "-ra"
    ])


def main():
    """Main function to run the test suite."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Test Suite for RAG Agentic Graphiti",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s unit              # Unit tests only
  %(prog)s integration       # Integration tests (requires RUN_INTEGRATION=1)
  %(prog)s all               # All tests
  %(prog)s fallback          # Tests with setup-fallback
  
  RUN_INTEGRATION=1 %(prog)s integration  # Run integration tests
        """
    )
    
    parser.add_argument(
        "mode",
        choices=["unit", "integration", "all", "fallback"],
        nargs="?",
        default="all",
        help="Run mode (default: all)"
    )
    
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Generate coverage report"
    )
    
    args = parser.parse_args()
    
    # Configurar argumentos adicionales para coverage si se solicita
    pytest_args = []
    if args.coverage:
        pytest_args.extend([
            "--cov=src",
            "--cov-report=term",
            "--cov-report=html:coverage_html"
        ])
    
    # Run according to the selected mode
    if args.mode == "unit":
        return run_unit_tests()
    elif args.mode == "integration":
        return run_integration_tests()
    elif args.mode == "fallback":
        return run_tests_with_fallback()
    else:  # all
        return run_all_tests()


if __name__ == "__main__":
    sys.exit(main())
