#!/bin/bash
# Test script for multilingual document ingestion

set -e

echo "=========================================="
echo "MULTILINGUAL INGESTION TEST"
echo "=========================================="
echo ""

# Copy test file to container
echo "1. Copying multilingual test file to container..."
podman cp tests/multilingual/test_data.txt rag-graphiti-agentic_app_1:/tmp/test_multilingual.txt

# Test text reading with fallbacks
echo ""
echo "2. Testing text reading with multilingual encoding support..."
podman exec rag-graphiti-agentic_app_1 python -c "
from src.workflows.ingestion.pipeline.utils.text_reading import read_text_with_fallbacks

result = read_text_with_fallbacks('/tmp/test_multilingual.txt')
print(f'Encoding detected: {result.encoding}')
print(f'Text length: {len(result.text)} characters')
print(f'First 200 chars: {result.text[:200]}...')

# Check if all languages are present
languages = ['English', 'Spanish', '中文', '日本語', '한국어', 'Русский', 'العربي', 'française', 'Deutscher', 'Português']
for lang in languages:
    if lang in result.text:
        print(f'✓ Found: {lang}')
    else:
        print(f'✗ Missing: {lang}')
"

echo ""
echo "3. Testing PlainTextLoader..."
podman exec rag-graphiti-agentic_app_1 python -c "
from src.workflows.ingestion.loaders.text_loader import PlainTextLoader

loader = PlainTextLoader('/tmp/test_multilingual.txt')
docs = loader.load()

print(f'Documents loaded: {len(docs)}')
for doc in docs:
    print(f'  - Source: {doc.metadata.get(\"source\")}')
    print(f'  - Encoding: {doc.metadata.get(\"encoding\")}')
    print(f'  - Content length: {len(doc.page_content)} chars')

    # Verify multilingual content
    languages = ['Artificial Intelligence', 'artificial intelligence', '人工智能', '人工知能', '인공 지능', 'Искусственный интеллект', 'الذكاء الاصطناعي', 'intelligence artificielle', 'Künstliche Intelligenz', 'inteligência artificial']
    found = sum(1 for lang in languages if lang in doc.page_content)
    print(f'  - Languages detected: {found}/{len(languages)}')
"

echo ""
echo "=========================================="
echo "TEST COMPLETED"
echo "=========================================="
