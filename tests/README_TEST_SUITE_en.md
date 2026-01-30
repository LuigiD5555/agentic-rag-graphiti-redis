# Test Suite for RAG Agentic Graphiti

This directory houses all project tests organized to make them easy to run via pytest.

## Test Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared pytest configuration
├── test_suite.py            # Entry point script for running tests
├── README_TEST_SUITE.md     # This documentation
├── infrastructure/          # Infrastructure tests
├── integration/             # Integration tests
│   ├── diagnostics/         # Diagnostics tests
│   ├── documents/           # Document-focused tests
│   ├── memory/              # Memory tests (some are marked skip)
│   ├── messaging/           # Messaging tests
│   ├── ocr/                 # OCR tests
│   └── rag/                 # RAG integration tests
├── scripts/                 # Verification scripts
├── systemd/                 # systemd-specific tests
├── tools/                   # Testing utilities and helpers
└── unit/                    # Unit tests
    ├── infrastructure/      # Infrastructure unit tests
    ├── ingestion/           # Ingestion unit tests
    ├── multilingual/        # Multilingual unit tests
    ├── providers/           # Provider unit tests
    ├── rag/                 # RAG unit tests
    ├── storage/             # Storage unit tests
    └── utils/               # Utility unit tests
```

## How to Run the Tests

### Option 1: Using the Test Suite (Recommended)

```bash
# Run every test (unit tests by default)
python tests/test_suite.py all

# Unit tests only
python tests/test_suite.py unit

# Integration tests (requires RUN_INTEGRATION=1)
export RUN_INTEGRATION=1
python tests/test_suite.py integration

# Tests with setup-fallback enabled
python tests/test_suite.py fallback

# With coverage reporting
python tests/test_suite.py all --coverage
```

### Option 2: Using pytest directly

```bash
# Run all tests (unit tests by default, integration excluded unless RUN_INTEGRATION=1)
python -m pytest

# Unit tests only (by directory)
python -m pytest tests/unit/

# Integration tests only (requires RUN_INTEGRATION=1)
export RUN_INTEGRATION=1
python -m pytest tests/integration/

# Run tests with markers (some tests provide markers)
python -m pytest -m "not slow"          # Skip slow tests
python -m pytest -m infrastructure      # Infrastructure-focused tests
python -m pytest -m preflight           # Preflight checks

# Additional pytest options
python -m pytest -v                    # Verbose
python -m pytest --tb=short            # Short tracebacks
python -m pytest -x                    # Exit after first failure
```

### Option 3: Shell script helper

```bash
# Run the fast unit tests
./run_tests.sh

# Run every test
./run_tests.sh all

# Run integration tests
./run_tests.sh integration
```

## Test Markers

Tests are organized using pytest markers:

### Main categories
- `unit`: Unit tests (fast, no external dependencies)
- `integration`: Integration tests (may require external services)
- `slow`: Long-running tests

### External dependencies
- `requires_weaviate`: Tests requiring Weaviate
- `requires_neo4j`: Tests requiring Neo4J (some are marked skip)
- `requires_lmstudio`: Tests requiring LM Studio

### Infrastructure and operations
- `infrastructure`: Infrastructure or system-level checks
- `preflight`: Preflight verifications before startup
- `volumes`: Volume checks and fallback configuration

## Configuration

### Environment variables
- `RUN_INTEGRATION=1`: Enables the execution of integration tests
- `USER_SETTINGS_FILE`: Overrides user configuration when isolated tests need it

### pytest.ini configuration file
The `pytest.ini` file at the repository root configures:
- Test discovery patterns
- Custom markers
- Default options (integration tests are excluded unless RUN_INTEGRATION=1)

## Tests Marked as Skip

Some tests remain marked `skip` for the following reasons:

1. **NER functionality not currently configured**: Tests that rely on Named Entity Recognition
2. **External cache migration tests are obsolete**: The SQLite control plane now manages cache/checkpoint behavior, so these tests stay skipped until a SQLite-focused suite replaces them
3. **Memory integration tests require ChatMemory functionality which may not be configured**: The memory integration tests

To enable these tests later, simply remove the `@pytest.mark.skip` decorator.

## Best Practices

1. **Before a pull request**: Run `python tests/test_suite.py all`
2. **During local development**: Run `python tests/test_suite.py unit` frequently
3. **Full verification**: Use `RUN_INTEGRATION=1 python tests/test_suite.py integration` prior to releases
4. **Coverage**: Add `--coverage` to generate coverage reports

## Troubleshooting

### Error: "Set RUN_INTEGRATION=1 to run integration tests"
```bash
export RUN_INTEGRATION=1
```

### Error: Missing modules
Some tests depend on additional packages. Check `requirements.txt`.

### Slow tests
Use `-m "not slow"` to skip slow tests during development.

### Specific tests failing
Run tests individually for debugging:
```bash
python -m pytest tests/unit/rag/test_rag_engine.py -v
```
