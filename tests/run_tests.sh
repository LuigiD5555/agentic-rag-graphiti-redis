#!/bin/bash
# Script to run tests for RAG Agentic Graphiti

set -e

# Ensure relative paths operate from the repository root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Color palette for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Verify we are in the expected repository root
if [ ! -f "pytest.ini" ]; then
    print_error "pytest.ini not found. Run this script from the repository root."
    exit 1
fi

run_unit_tests() {
    print_header "RUNNING UNIT TESTS"
    echo "These tests are fast and do not require external services."
    echo ""
    python -m pytest tests/unit/ --tb=short -v --strict-markers -ra
}

run_integration_tests() {
    if [ "$RUN_INTEGRATION" != "1" ]; then
        print_error "Integration tests require RUN_INTEGRATION=1"
        echo "Run: export RUN_INTEGRATION=1"
        echo "Or use: RUN_INTEGRATION=1 $0 integration"
        exit 1
    fi

    print_header "RUNNING INTEGRATION TESTS"
    echo "These tests may require external services (Weaviate, etc.)"
    echo ""
    python -m pytest tests/integration/ --tb=short -v --strict-markers -ra
}

run_all_tests() {
    print_header "RUNNING ALL TESTS"
    echo "Note: Integration tests are skipped unless RUN_INTEGRATION=1"
    echo ""
    python -m pytest --tb=short -v --strict-markers -ra
}

run_coverage_tests() {
    print_header "RUNNING TESTS WITH COVERAGE"
    echo ""
    python -m pytest --cov=src --cov-report=term --cov-report=html:coverage_html --tb=short -v --strict-markers -ra
}

run_specific_tests() {
    print_header "RUNNING SPECIFIC TESTS: $1"
    echo ""
    python -m pytest "$1" --tb=short -v --strict-markers -ra
}

show_help() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  unit        Run unit tests only (fast)"
    echo "  integration Run integration tests (requires RUN_INTEGRATION=1)"
    echo "  all         Run all tests (default)"
    echo "  coverage    Run tests with coverage report"
    echo "  path        Run tests at a specific path"
    echo "  help        Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 unit                    # Unit tests only"
    echo "  $0 all                     # All tests"
    echo "  $0 coverage                # Tests with coverage"
    echo "  RUN_INTEGRATION=1 $0 integration  # Integration tests"
    echo "  $0 tests/unit/rag/         # Tests in a specific directory"
    echo ""
    echo "Environment variables:"
    echo "  RUN_INTEGRATION=1  Enables integration tests"
}

# Process command-line arguments
case "${1:-all}" in
    unit)
        run_unit_tests
        ;;
    integration)
        run_integration_tests
        ;;
    all)
        run_all_tests
        ;;
    coverage)
        run_coverage_tests
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        # If the argument looks like a path, run tests there
        if [ -d "$1" ] || [ -f "$1" ]; then
            run_specific_tests "$1"
        else
            print_error "Unrecognized command: $1"
            echo ""
            show_help
            exit 1
        fi
        ;;
esac
