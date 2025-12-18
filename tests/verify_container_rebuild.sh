#!/bin/bash
# Verification script to confirm container rebuild applied all changes

set -e

echo "================================================================================"
echo "POST-REBUILD VERIFICATION"
echo "================================================================================"
echo ""

CONTAINER_NAME="rag-agentic-graphiti-app-1"

# Check if container is running
echo "1. Verifying that the container is running..."
if podman ps --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
    echo "   OK: Container '$CONTAINER_NAME' is running"
else
    echo "   ERROR: Container '$CONTAINER_NAME' is NOT running"
    echo "   Run: podman-compose up -d"
    exit 1
fi
echo ""

# Check settings.py inside container
echo "2. Verifying settings.py inside the container..."
DOCS_PATHS=$(podman exec "$CONTAINER_NAME" python -c "from src.settings import DOCS_PATHS; print(DOCS_PATHS)" 2>/dev/null || echo "ERROR")

if [[ "$DOCS_PATHS" == *"/mnt/resources/Libros/Aprendizaje"* ]] && [[ "$DOCS_PATHS" != *"/mnt/Documents/Documents"* ]]; then
    echo "   OK: DOCS_PATHS is correct, only includes /mnt/resources/Libros/Aprendizaje"
elif [[ "$DOCS_PATHS" == "ERROR" ]]; then
    echo "   ERROR: Could not read settings.py from the container"
    exit 1
else
    echo "   ERROR: DOCS_PATHS still includes /mnt/Documents/Documents"
    echo "   Current DOCS_PATHS: $DOCS_PATHS"
    echo ""
    echo "   FIX: you need to rebuild the container:"
    echo "   podman-compose down"
    echo "   podman-compose build --no-cache app"
    echo "   podman-compose up -d"
    exit 1
fi
echo ""

# Check exclusion globs
echo "3. Verifying configured exclusions..."
EXCLUDE_GLOBS=$(podman exec "$CONTAINER_NAME" python -c "from src.settings import DOCS_EXCLUDE_GLOBS; print(len(DOCS_EXCLUDE_GLOBS))" 2>/dev/null || echo "0")

if [[ "$EXCLUDE_GLOBS" -gt 0 ]]; then
    echo "   OK: DOCS_EXCLUDE_GLOBS configured ($EXCLUDE_GLOBS patterns)"
else
    echo "   WARNING: DOCS_EXCLUDE_GLOBS is empty (this can be fine if you only use enabled paths)"
fi
echo ""

# Check PDFLoader incremental loading
echo "4. Verifying PDFLoader incremental loading..."
PDF_CHECK=$(podman exec "$CONTAINER_NAME" python -c "
from src.rag.ingestion.loaders.pdf_loader import PDFLoader
print(f'MAX_PDF_SIZE={PDFLoader.MAX_PDF_SIZE_BYTES/(1024*1024):.0f}MB')
print(f'LARGE_THRESHOLD={PDFLoader.LARGE_PDF_THRESHOLD/(1024*1024):.0f}MB')
print(f'PAGES_PER_BATCH={PDFLoader.PAGES_PER_BATCH}')
print(f'TIMEOUT={PDFLoader.LOAD_TIMEOUT_SECONDS}s')
" 2>/dev/null || echo "ERROR")

if [[ "$PDF_CHECK" == *"MAX_PDF_SIZE=500MB"* ]] && [[ "$PDF_CHECK" == *"PAGES_PER_BATCH=50"* ]]; then
    echo "   OK: PDFLoader is configured correctly:"
    echo "$PDF_CHECK" | sed 's/^/      /'
else
    echo "   ERROR: PDFLoader does not have the expected configuration"
    echo "   Current value: $PDF_CHECK"
    exit 1
fi
echo ""

# Check CSVLoader limits
echo "5. Verifying CSVLoader row limits..."
CSV_CHECK=$(podman exec "$CONTAINER_NAME" python -c "
from src.rag.ingestion.loaders.csv_loader import CSVLoader
print(f'MAX_ROWS={CSVLoader.MAX_ROWS}')
print(f'MAX_FILE_SIZE={CSVLoader.MAX_FILE_SIZE_BYTES/(1024*1024):.0f}MB')
" 2>/dev/null || echo "ERROR")

if [[ "$CSV_CHECK" == *"MAX_ROWS=50000"* ]]; then
    echo "   OK: CSVLoader is configured correctly:"
    echo "$CSV_CHECK" | sed 's/^/      /'
else
    echo "   ERROR: CSVLoader does not have the expected configuration"
    echo "   Current value: $CSV_CHECK"
    exit 1
fi
echo ""

# Check file sorting order
echo "6. Verifying file order (ascending)..."
SORT_CHECK=$(podman exec "$CONTAINER_NAME" python -c "
import tempfile
import os
from src.utils.file_operations import sort_paths_by_size_desc

# Create temp files with different sizes
with tempfile.TemporaryDirectory() as tmpdir:
    files = []
    for name, size in [('big.txt', 1000), ('small.txt', 10), ('medium.txt', 100)]:
        path = os.path.join(tmpdir, name)
        with open(path, 'w') as f:
            f.write('x' * size)
        files.append(path)

    sorted_files = sort_paths_by_size_desc(files)
    sizes = [os.path.getsize(f) for f in sorted_files]

    # Check if ascending
    is_ascending = all(sizes[i] <= sizes[i+1] for i in range(len(sizes)-1))
    print('ASCENDING' if is_ascending else 'DESCENDING')
" 2>/dev/null || echo "ERROR")

if [[ "$SORT_CHECK" == "ASCENDING" ]]; then
    echo "   OK: Ascending order configured (small to large)"
else
    echo "   ERROR: Order is not ascending"
    exit 1
fi
echo ""

# Test LM Studio connection
echo "7. Verifying connection to LM Studio..."
LM_HOST=$(podman exec "$CONTAINER_NAME" sh -lc 'echo "${LMSTUDIO_HOST:-127.0.0.1}"' 2>/dev/null || echo "127.0.0.1")
LM_PORT=$(podman exec "$CONTAINER_NAME" sh -lc 'echo "${LMSTUDIO_PORT:-1234}"' 2>/dev/null || echo "1234")
LM_STUDIO_CHECK=$(podman exec "$CONTAINER_NAME" curl -s "http://${LM_HOST}:${LM_PORT}/v1/models" 2>/dev/null || echo "ERROR")

if [[ "$LM_STUDIO_CHECK" == *"\"object\":\"list\""* ]]; then
    MODEL_COUNT=$(echo "$LM_STUDIO_CHECK" | grep -o '"id"' | wc -l)
    echo \"   OK: LM Studio is reachable ($MODEL_COUNT models available)\"
else
    echo \"   WARNING: could not connect to LM Studio\"
    echo \"   Verify that LM Studio is running and that the container can reach http://${LM_HOST}:${LM_PORT}\"
fi
echo ""

# Summary
echo "================================================================================"
echo "VERIFICATION SUMMARY"
echo "================================================================================"
echo ""
echo "Container rebuild verification completed successfully"
echo "settings.py configuration applied correctly"
echo "PDFLoader configured (500 MB max, batches of 50 pages)"
echo "CSVLoader configured (50,000 row limit)"
echo "Ascending file order verified (small to large)"
echo ""
echo "NEXT STEP: run a test ingestion"
echo ""
echo "   podman exec -it $CONTAINER_NAME bash -c \\"
echo "       'python -m src.rag.ingestion --max-files 10 --log-level DEBUG'"
echo ""
echo "   You should see:"
echo "   - Only ~500-2000 candidate files (NOT 198,272)"
echo "   - Smaller files processed first"
echo "   - Visible progress within seconds"
echo ""
echo "================================================================================"
