#!/usr/bin/env python3
"""
Test script para verificar que las correcciones de ingesta funcionen correctamente.

Este script verifica:
1. Que las exclusiones por defecto estén activas
2. Que el orden de archivos sea ascendente (pequeño→grande)
3. Que los límites de PDF/CSV estén configurados correctamente
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag.ingestion.helpers import build_ingestion_options_from_args
from src.rag.ingestion.loaders.pdf_loader import PDFLoader
from src.rag.ingestion.loaders.csv_loader import CSVLoader
from src.utils.file_operations import sort_paths_by_size_desc
from src.settings import _DEFAULT_EXCLUDED_FILES
import argparse


def test_exclusions():
    """Verificar que las exclusiones por defecto están activas."""
    print("\n" + "="*80)
    print("TEST 1: Verificando exclusiones por defecto")
    print("="*80)

    # Simular args sin exclusiones explícitas
    args = argparse.Namespace(
        paths=["/mnt/Documents"],
        exts=None,
        exclude_dirs=None,
        exclude_patterns=None,
        enabled_paths=None,
        follow_symlinks=False,
        dry_run=False,
        per_file=False,
        max_files=0,
        log_level="INFO",
        scan_progress=0
    )

    # Simular config sin exclusiones
    class MockConfig:
        DOCS_PATHS = ["/mnt/Documents"]
        DOCS_FILE_EXTS = [".pdf", ".txt"]
        DOCS_EXCLUDE_DIRS = ()
        DOCS_EXCLUDE_GLOBS = ()
        DOCS_ENABLED_PATHS = ()
        DOCS_FOLLOW_SYMLINKS = False
        INGEST_LOG_LEVEL = "INFO"

    options = build_ingestion_options_from_args(args, MockConfig())

    print(f"\n✓ Exclusiones activas: {len(options.excluded_directory_names)} directorios")
    print(f"  Muestra: {sorted(list(options.excluded_directory_names))[:10]}")

    # Verificar que contiene los defaults críticos
    critical_excludes = {"node_modules", ".git", "__pycache__", "venv", ".venv"}
    missing = critical_excludes - options.excluded_directory_names

    if missing:
        print(f"\n❌ FALLO: Faltan exclusiones críticas: {missing}")
        return False
    else:
        print(f"\n✅ ÉXITO: Todas las exclusiones críticas están activas")
        return True


def test_file_order():
    """Verificar que el orden de archivos sea ascendente."""
    print("\n" + "="*80)
    print("TEST 2: Verificando orden de archivos (ascendente)")
    print("="*80)

    # Crear archivos de prueba simulados
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear archivos de diferentes tamaños
        files = []
        for name, size in [("big.txt", 1000), ("small.txt", 10), ("medium.txt", 100)]:
            path = os.path.join(tmpdir, name)
            with open(path, "w") as f:
                f.write("x" * size)
            files.append(path)

        # Ordenar
        sorted_files = sort_paths_by_size_desc(files)

        # Verificar orden
        sizes = [os.path.getsize(f) for f in sorted_files]
        print(f"\nArchivos ordenados:")
        for path, size in zip(sorted_files, sizes):
            print(f"  {os.path.basename(path)}: {size} bytes")

        # Verificar que sea ascendente
        is_ascending = all(sizes[i] <= sizes[i+1] for i in range(len(sizes)-1))

        if is_ascending:
            print(f"\n✅ ÉXITO: Orden ascendente correcto (pequeño→grande)")
            return True
        else:
            print(f"\n❌ FALLO: Orden NO es ascendente")
            return False


def test_pdf_limits():
    """Verificar que PDFLoader tenga límites configurados."""
    print("\n" + "="*80)
    print("TEST 3: Verificando límites de PDFLoader")
    print("="*80)

    print(f"\nLímite de tamaño de PDF: {PDFLoader.MAX_PDF_SIZE_BYTES / (1024*1024):.1f} MB")
    print(f"Timeout de carga: {PDFLoader.LOAD_TIMEOUT_SECONDS} segundos")

    expected_size = 500 * 1024 * 1024  # 500 MB
    expected_timeout = 300  # 5 minutos

    if PDFLoader.MAX_PDF_SIZE_BYTES == expected_size:
        print("✓ Límite de tamaño correcto")
        size_ok = True
    else:
        print(f"✗ Límite de tamaño incorrecto: esperado {expected_size}, actual {PDFLoader.MAX_PDF_SIZE_BYTES}")
        size_ok = False

    if PDFLoader.LOAD_TIMEOUT_SECONDS == expected_timeout:
        print("✓ Timeout correcto")
        timeout_ok = True
    else:
        print(f"✗ Timeout incorrecto: esperado {expected_timeout}, actual {PDFLoader.LOAD_TIMEOUT_SECONDS}")
        timeout_ok = False

    if size_ok and timeout_ok:
        print(f"\n✅ ÉXITO: Límites de PDF configurados correctamente")
        return True
    else:
        print(f"\n❌ FALLO: Límites de PDF incorrectos")
        return False


def test_csv_limits():
    """Verificar que CSVLoader tenga límites configurados."""
    print("\n" + "="*80)
    print("TEST 4: Verificando límites de CSVLoader")
    print("="*80)

    print(f"\nLímite de filas: {CSVLoader.MAX_ROWS:,}")
    print(f"Límite de tamaño de archivo: {CSVLoader.MAX_FILE_SIZE_BYTES / (1024*1024):.1f} MB")

    expected_rows = 50000
    expected_size = 150 * 1024 * 1024  # 150 MB

    if CSVLoader.MAX_ROWS == expected_rows:
        print("✓ Límite de filas correcto")
        rows_ok = True
    else:
        print(f"✗ Límite de filas incorrecto: esperado {expected_rows}, actual {CSVLoader.MAX_ROWS}")
        rows_ok = False

    if CSVLoader.MAX_FILE_SIZE_BYTES == expected_size:
        print("✓ Límite de tamaño correcto")
        size_ok = True
    else:
        print(f"✗ Límite de tamaño incorrecto: esperado {expected_size}, actual {CSVLoader.MAX_FILE_SIZE_BYTES}")
        size_ok = False

    if rows_ok and size_ok:
        print(f"\n✅ ÉXITO: Límites de CSV configurados correctamente")
        return True
    else:
        print(f"\n❌ FALLO: Límites de CSV incorrectos")
        return False


def main():
    """Ejecutar todos los tests."""
    print("\n" + "="*80)
    print("VERIFICACIÓN DE CORRECCIONES DE INGESTA")
    print("="*80)

    results = []
    results.append(("Exclusiones por defecto", test_exclusions()))
    results.append(("Orden de archivos", test_file_order()))
    results.append(("Límites de PDF", test_pdf_limits()))
    results.append(("Límites de CSV", test_csv_limits()))

    # Resumen
    print("\n" + "="*80)
    print("RESUMEN DE RESULTADOS")
    print("="*80)

    for name, passed in results:
        status = "✅ PASÓ" if passed else "❌ FALLÓ"
        print(f"{status}: {name}")

    all_passed = all(passed for _, passed in results)
    print("\n" + "="*80)
    if all_passed:
        print("✅ TODOS LOS TESTS PASARON - Sistema listo para ingesta")
    else:
        print("❌ ALGUNOS TESTS FALLARON - Revisar configuración")
    print("="*80 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
