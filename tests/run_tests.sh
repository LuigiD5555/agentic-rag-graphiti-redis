#!/bin/sh
# Script to run tests for RAG Agentic Graphiti

set -e

# Ensure relative paths operate from the repository root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Color palette for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    printf "%b\n" "${BLUE}========================================${NC}"
    printf "%b\n" "${BLUE}  $1${NC}"
    printf "%b\n" "${BLUE}========================================${NC}"
}

print_success() {
    printf "%b\n" "${GREEN}✓ $1${NC}"
}

print_error() {
    printf "%b\n" "${RED}✗ $1${NC}"
}

print_warning() {
    printf "%b\n" "${YELLOW}⚠ $1${NC}"
}

# Verify we are in the expected repository root
if [ ! -f "pytest.ini" ]; then
    print_error "pytest.ini not found. Run this script from the repository root."
    exit 1
fi

run_unit_tests() {
    print_header "RUNNING UNIT TESTS"
    echo "Fast/default profile. Integration suite is not collected here."
    echo ""
    python -m pytest \
        tests/unit/ \
        tests/infrastructure/ \
        tests/test_checkpoint_fix.py \
        tests/test_checkpoint_system.py \
        tests/test_pattern_matching.py \
        --tb=short -v --strict-markers -ra \
        -m "not preflight_host"
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

run_host_preflight_tests() {
    print_header "RUNNING HOST PREFLIGHT TESTS"
    echo "Host-only checks (podman/systemd/.env/compose). Run on host, not inside app container."
    echo ""
    python -m pytest tests/infrastructure/test_preflight.py --tb=short -v --strict-markers -ra -m preflight_host
}

run_runtime_preflight_tests() {
    print_header "RUNNING RUNTIME PREFLIGHT TESTS"
    echo "Container/runtime checks."
    echo ""
    python -m pytest tests/infrastructure/test_preflight.py --tb=short -v --strict-markers -ra -m preflight_runtime
}

run_stack_smoke() {
    print_header "RUNNING STACK SMOKE TEST"
    echo "Requires compose stack and RUN_STACK_SMOKE=1."
    echo ""
    RUN_INTEGRATION=1 RUN_STACK_SMOKE=1 python -m pytest \
        tests/integration/rag/test_stack_smoke.py \
        --tb=short -v --strict-markers -ra
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
    echo "  host        Run host-only preflight checks"
    echo "  runtime     Run runtime/container preflight checks"
    echo "  smoke       Run stack smoke integration test"
    echo "  coverage    Run tests with coverage report"
    echo "  path        Run tests at a specific path"
    echo "  help        Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 unit                    # Unit tests only"
    echo "  $0 all                     # All tests"
    echo "  $0 coverage                # Tests with coverage"
    echo "  RUN_INTEGRATION=1 $0 integration  # Integration tests"
    echo "  $0 host                           # Host-only preflight checks"
    echo "  $0 runtime                        # Runtime/container preflight checks"
    echo "  $0 smoke                          # Stack smoke test"
    echo "  $0 tests/unit/rag/         # Tests in a specific directory"
    echo ""
    echo "Environment variables:"
    echo "  RUN_INTEGRATION=1  Enables integration tests"
    echo "  RUN_STACK_SMOKE=1  Enables stack smoke test"
}

# Process command-line arguments
case "${1:-all}" in
    unit)
        run_unit_tests
        ;;
    integration)
        run_integration_tests
        ;;
    host)
        run_host_preflight_tests
        ;;
    runtime)
        run_runtime_preflight_tests
        ;;
    smoke)
        run_stack_smoke
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
