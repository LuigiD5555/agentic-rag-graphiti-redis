#!/usr/bin/env python3
"""
Test Suite para RAG Agentic Graphiti

Este archivo proporciona una forma conveniente de ejecutar todos los tests del proyecto
usando pytest. Incluye opciones para ejecutar diferentes tipos de tests:

1. Tests unitarios (rápidos, sin dependencias externas)
2. Tests de integración (requieren servicios externos)
3. Todos los tests

Uso:
    python -m pytest tests/test_suite.py           # Ejecuta tests unitarios por defecto
    python -m pytest tests/test_suite.py -m unit   # Solo tests unitarios
    python -m pytest tests/test_suite.py -m integration  # Solo tests de integración (requiere RUN_INTEGRATION=1)
    python -m pytest tests/test_suite.py --setup-fallback  # Con opción de fallback
"""

import os
import sys
import pytest


def run_unit_tests():
    """Ejecuta solo los tests unitarios."""
    print("=== Ejecutando Tests Unitarios ===")
    print("Estos tests son rápidos y no requieren servicios externos.")
    print("-" * 50)
    
    # Ejecutar tests en directorio unit/ (no usar marcador ya que no están consistentemente marcados)
    return pytest.main([
        "tests/unit/",
        "--tb=short",
        "-v",
        "--strict-markers",
        "-ra"
    ])


def run_integration_tests():
    """Ejecuta tests de integración (requiere RUN_INTEGRATION=1)."""
    if os.getenv("RUN_INTEGRATION") != "1":
        print("ERROR: Los tests de integración requieren RUN_INTEGRATION=1")
        print("Ejecuta: export RUN_INTEGRATION=1")
        return 1
    
    print("=== Ejecutando Tests de Integración ===")
    print("Estos tests pueden requerir servicios externos (Weaviate, etc.)")
    print("-" * 50)
    
    # Ejecutar tests en directorio integration/ (no usar marcadores)
    return pytest.main([
        "tests/integration/",
        "--tb=short",
        "-v",
        "--strict-markers",
        "-ra"
    ])


def run_all_tests():
    """Ejecuta todos los tests (unitarios por defecto, integración opcional)."""
    print("=== Ejecutando Todos los Tests ===")
    print("Nota: Los tests de integración se saltan a menos que RUN_INTEGRATION=1")
    print("-" * 50)
    
    # Ejecutar pytest con configuración por defecto
    return pytest.main([
        "--tb=short",
        "-v",
        "--strict-markers",
        "-ra"
    ])


def run_tests_with_fallback():
    """Ejecuta tests con opción de setup-fallback."""
    print("=== Ejecutando Tests con Setup Fallback ===")
    print("Configura directorios de fallback cuando los volúmenes no son accesibles")
    print("-" * 50)
    
    return pytest.main([
        "--setup-fallback",
        "--tb=short",
        "-v",
        "--strict-markers",
        "-ra"
    ])


def main():
    """Función principal para ejecutar el test suite."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Test Suite para RAG Agentic Graphiti",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  %(prog)s unit              # Solo tests unitarios
  %(prog)s integration       # Tests de integración (requiere RUN_INTEGRATION=1)
  %(prog)s all               # Todos los tests
  %(prog)s fallback          # Tests con setup-fallback
  
  RUN_INTEGRATION=1 %(prog)s integration  # Para ejecutar tests de integración
        """
    )
    
    parser.add_argument(
        "mode",
        choices=["unit", "integration", "all", "fallback"],
        nargs="?",
        default="all",
        help="Modo de ejecución (default: all)"
    )
    
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Generar reporte de cobertura"
    )
    
    args = parser.parse_args()
    
    # Configurar argumentos adicionales para coverage si se solicita
    pytest_args = []
    if args.coverage:
        pytest_args.extend([
            "--cov=src",
            "--cov-report=term",
            "--cov-report=html:coverage_html"
        ])
    
    # Ejecutar según el modo seleccionado
    if args.mode == "unit":
        return run_unit_tests()
    elif args.mode == "integration":
        return run_integration_tests()
    elif args.mode == "fallback":
        return run_tests_with_fallback()
    else:  # all
        return run_all_tests()


if __name__ == "__main__":
    sys.exit(main())