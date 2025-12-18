#!/bin/bash
# Script to verify that the fixes are implemented

echo "================================================================================"
echo "VERIFICATION OF IMPLEMENTED FIXES"
echo "================================================================================"
echo ""

# Test 1: verify that sort_paths_by_size_desc uses ascending order
echo "TEST 1: Verifying file order (ascending)"
echo "--------------------------------------------------------------------------------"
if grep -q "key=lambda p: (sizes\[p\], p.lower())" src/utils/file_operations.py; then
    echo "OK: Ascending order configured (small to large)"
else
    echo "ERROR: Ascending order is not configured"
fi
echo ""

# Test 2: verify that helpers.py uses _DEFAULT_EXCLUDED_FILES
echo "TEST 2: Verifying import of default exclusions"
echo "--------------------------------------------------------------------------------"
if grep -q "from src.settings import _DEFAULT_EXCLUDED_FILES" src/rag/ingestion/helpers.py; then
    echo "OK: Default exclusions are imported"
else
    echo "ERROR: Default exclusions are not imported"
fi

if grep -q "excluded_directory_names = _DEFAULT_EXCLUDED_FILES.copy()" src/rag/ingestion/helpers.py; then
    echo "OK: Default exclusions are used as base"
else
    echo "ERROR: Default exclusions are not used as base"
fi
echo ""

# Test 3: verify limits in CSVLoader
echo "TEST 3: Verifying limits in CSVLoader"
echo "--------------------------------------------------------------------------------"
if grep -q "MAX_ROWS = 50000" src/rag/ingestion/loaders/csv_loader.py; then
    echo "OK: 50,000 row limit configured"
else
    echo "ERROR: Row limit is not configured"
fi

if grep -q "MAX_FILE_SIZE_BYTES = 150 \* 1024 \* 1024" src/rag/ingestion/loaders/csv_loader.py; then
    echo "OK: 150 MB file size limit configured"
else
    echo "ERROR: File size limit is not configured"
fi
echo ""

# Test 4: verify limits and timeout in PDFLoader
echo "TEST 4: Verifying limits and timeout in PDFLoader"
echo "--------------------------------------------------------------------------------"
if grep -q "MAX_PDF_SIZE_BYTES.*500.*1024.*1024" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "OK: PDF maximum size configured (500 MB)"
else
    echo "ERROR: PDF maximum size is not configured"
fi

if grep -q "LOAD_TIMEOUT_SECONDS = 300" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "OK: 300s timeout configured"
else
    echo "ERROR: Timeout is not configured"
fi

if grep -q "def _load_with_timeout" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "OK: _load_with_timeout method implemented"
else
    echo "ERROR: _load_with_timeout method not found"
fi

if grep -q "def _is_scanned_pdf" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "OK: scanned PDF detection implemented"
else
    echo "ERROR: scanned PDF detection not found"
fi

if grep -q "def _load_incrementally" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "OK: incremental PDF loading implemented"
else
    echo "ERROR: incremental PDF loading not found"
fi

if grep -q "LARGE_PDF_THRESHOLD = 50 \* 1024 \* 1024" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "OK: large PDF threshold configured (50 MB)"
else
    echo "ERROR: large PDF threshold is not configured"
fi

if grep -q "MAX_PDF_SIZE_BYTES = 500 \* 1024 \* 1024" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "OK: PDF maximum size increased to 500 MB"
else
    echo "ERROR: PDF maximum size is not updated"
fi

if grep -q "PAGES_PER_BATCH = 50" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "OK: batch size configured (50 pages)"
else
    echo "ERROR: batch size is not configured"
fi
echo ""

# Test 5: verify that _DEFAULT_EXCLUDED_FILES contains critical entries
echo "TEST 5: Verifying default exclusion content"
echo "--------------------------------------------------------------------------------"
critical_dirs=("node_modules" ".git" "__pycache__" "venv" ".venv" "site-packages" ".next" "dist" "build")
for dir in "${critical_dirs[@]}"; do
    if grep -q "\"$dir\"" src/settings.py; then
        echo "OK: Found $dir"
    else
        echo "ERROR: Missing $dir"
    fi
done
echo ""

echo "================================================================================"
echo "VERIFICATION COMPLETED"
echo "================================================================================"
echo ""
echo "If all tests passed, the system is ready to run ingestion."
echo ""
echo "To test with real files:"
echo "  cd /app"
echo "  python -m src.ingestion --paths /mnt/resources/Libros --max-files 50 --log-level DEBUG"
echo ""
