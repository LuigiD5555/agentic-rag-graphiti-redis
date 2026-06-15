# Tests Directory Structure

This directory contains all testing and verification code for the RAG project, organized by component.

## Directory Organization

```
tests/
├── tools/                    # Tool management tests & examples
│   ├── client_example.py    # Example HTTP client for tool endpoints
│   └── gui_verifier_demo.py # Demo showing GUI integration with setup_verifier
│
├── rag/                     # RAG system tests
│   └── integration/         # Integration tests for RAG pipeline
│       ├── test_api.py
│       ├── test_openai_sdk.py
│       ├── test_rag_query.py
│       └── test_stack_smoke.py
│
├── ingestion/               # Ingestion pipeline tests
├── multilingual/            # Multilingual processing tests
├── weaviate/               # Weaviate database tests
├── memory/                 # Memory system tests
│   └── verify_memory_phase1.py
│
├── unit/                   # Unit tests
├── scripts/                # Testing utilities & scripts
└── systemd/                # Systemd configuration tests
```

## Key Testing Tools

### Tool Management
- `tests/tools/client_example.py` - HTTP client for testing tool endpoints (office, archive, ocr)
- `tests/tools/gui_verifier_demo.py` - Examples of programmatic setup verification

### Setup Verification
Located in `src/utils/tools/setup_verifier.py` (not in tests/ since it's production code):
```bash
# Verify entire system setup
python -m src.utils.tools.setup_verifier

# Get JSON output for automation
python -m src.utils.tools.setup_verifier --json
```

### Memory Verification
- `tests/memory/verify_memory_phase1.py` - Phase 1 memory system verification

## Running Tests

### Unit Tests
```bash
pytest tests/unit/
```

### Integration Tests
```bash
pytest tests/rag/integration/
```

### Tool Tests
```bash
# Example client usage
python tests/tools/client_example.py

# GUI verifier examples
python tests/tools/gui_verifier_demo.py
```

### Memory Tests
```bash
python tests/memory/verify_memory_phase1.py
```

## Organization Philosophy

- **tests/tools/** - Everything related to preprocessing tool containers
- **tests/rag/** - RAG pipeline, API, and query tests
- **tests/ingestion/** - Document ingestion and processing
- **tests/memory/** - Memory and graph store verification
- **tests/unit/** - Low-level unit tests
- **tests/scripts/** - Development utilities

All verification and example code belongs in `tests/` to keep the main codebase clean and focused on production code.
