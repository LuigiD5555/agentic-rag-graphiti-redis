# Multilingual Tests

This directory contains tests to verify the multilingual support of the RAG system.

## Files

### test_language_detection.py
Test script for automatic language detection.

**Usage:**
```bash
podman exec rag-graphiti-agentic_app_1 python tests/multilingual/test_language_detection.py
```

### test_ingestion.sh
Test script for multilingual document ingestion.

**Usage:**
```bash
./tests/multilingual/test_ingestion.sh
```

### test_data.txt
Test data file with content in 10 different languages:
- English
- Spanish
- Chinese
- Japanese
- Korean
- Russian
- Arabic
- French
- German
- Portuguese

## Run All Tests

```bash
# Language detection
podman exec rag-graphiti-agentic_app_1 python tests/multilingual/test_language_detection.py

# Multilingual ingestion
./tests/multilingual/test_ingestion.sh
```

## Expected Results

All tests should:
- Detect all 10 languages correctly
- Ingest content without encoding errors
- Preserve all special characters
