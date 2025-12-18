#!/bin/bash
# Script para verificar que las correcciones estén implementadas

echo "================================================================================"
echo "VERIFICACIÓN DE CORRECCIONES IMPLEMENTADAS"
echo "================================================================================"
echo ""

# Test 1: Verificar que sort_paths_by_size_desc use orden ascendente
echo "TEST 1: Verificando orden de archivos (ascendente)"
echo "--------------------------------------------------------------------------------"
if grep -q "key=lambda p: (sizes\[p\], p.lower())" src/utils/file_operations.py; then
    echo "✅ ÉXITO: Orden ascendente configurado (pequeño→grande)"
else
    echo "❌ FALLO: Orden ascendente NO configurado"
fi
echo ""

# Test 2: Verificar que helpers.py use _DEFAULT_EXCLUDED_FILES
echo "TEST 2: Verificando importación de exclusiones por defecto"
echo "--------------------------------------------------------------------------------"
if grep -q "from src.settings import _DEFAULT_EXCLUDED_FILES" src/rag/ingestion/helpers.py; then
    echo "✅ ÉXITO: Importa exclusiones por defecto"
else
    echo "❌ FALLO: No importa exclusiones por defecto"
fi

if grep -q "excluded_directory_names = _DEFAULT_EXCLUDED_FILES.copy()" src/rag/ingestion/helpers.py; then
    echo "✅ ÉXITO: Usa exclusiones por defecto como base"
else
    echo "❌ FALLO: No usa exclusiones por defecto"
fi
echo ""

# Test 3: Verificar límites en CSVLoader
echo "TEST 3: Verificando límites en CSVLoader"
echo "--------------------------------------------------------------------------------"
if grep -q "MAX_ROWS = 50000" src/rag/ingestion/loaders/csv_loader.py; then
    echo "✅ ÉXITO: Límite de 50,000 filas configurado"
else
    echo "❌ FALLO: Límite de filas no configurado"
fi

if grep -q "MAX_FILE_SIZE_BYTES = 150 \* 1024 \* 1024" src/rag/ingestion/loaders/csv_loader.py; then
    echo "✅ ÉXITO: Límite de 150 MB configurado"
else
    echo "❌ FALLO: Límite de tamaño no configurado"
fi
echo ""

# Test 4: Verificar límites y timeout en PDFLoader
echo "TEST 4: Verificando límites y timeout en PDFLoader"
echo "--------------------------------------------------------------------------------"
if grep -q "MAX_PDF_SIZE_BYTES.*500.*1024.*1024" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "✅ ÉXITO: Límite máximo de PDF configurado (500 MB)"
else
    echo "❌ FALLO: Límite de tamaño no configurado"
fi

if grep -q "LOAD_TIMEOUT_SECONDS = 300" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "✅ ÉXITO: Timeout de 300s configurado"
else
    echo "❌ FALLO: Timeout no configurado"
fi

if grep -q "def _load_with_timeout" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "✅ ÉXITO: Método _load_with_timeout implementado"
else
    echo "❌ FALLO: Método _load_with_timeout no encontrado"
fi

if grep -q "def _is_scanned_pdf" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "✅ ÉXITO: Detección de PDFs escaneados implementada"
else
    echo "❌ FALLO: Detección de PDFs escaneados no encontrada"
fi

if grep -q "def _load_incrementally" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "✅ ÉXITO: Carga incremental de PDFs implementada"
else
    echo "❌ FALLO: Carga incremental no encontrada"
fi

if grep -q "LARGE_PDF_THRESHOLD = 50 \* 1024 \* 1024" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "✅ ÉXITO: Umbral de PDF grande configurado (50 MB)"
else
    echo "❌ FALLO: Umbral de PDF grande no configurado"
fi

if grep -q "MAX_PDF_SIZE_BYTES = 500 \* 1024 \* 1024" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "✅ ÉXITO: Límite máximo aumentado a 500 MB"
else
    echo "❌ FALLO: Límite máximo no actualizado"
fi

if grep -q "PAGES_PER_BATCH = 50" src/rag/ingestion/loaders/pdf_loader.py; then
    echo "✅ ÉXITO: Tamaño de lote configurado (50 páginas)"
else
    echo "❌ FALLO: Tamaño de lote no configurado"
fi
echo ""

# Test 5: Verificar que _DEFAULT_EXCLUDED_FILES tenga los críticos
echo "TEST 5: Verificando contenido de exclusiones por defecto"
echo "--------------------------------------------------------------------------------"
critical_dirs=("node_modules" ".git" "__pycache__" "venv" ".venv" "site-packages" ".next" "dist" "build")
for dir in "${critical_dirs[@]}"; do
    if grep -q "\"$dir\"" src/settings.py; then
        echo "✅ Encontrado: $dir"
    else
        echo "❌ Falta: $dir"
    fi
done
echo ""

echo "================================================================================"
echo "VERIFICACIÓN COMPLETADA"
echo "================================================================================"
echo ""
echo "Si todos los tests pasaron, el sistema está listo para ejecutar la ingesta."
echo ""
echo "Para probar con archivos reales:"
echo "  cd /app"
echo "  python -m src.rag.ingestion --paths /mnt/resources/Libros --max-files 50 --log-level DEBUG"
echo ""
