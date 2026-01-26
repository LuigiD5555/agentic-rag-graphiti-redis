#!/bin/bash
# Script para ejecutar tests de RAG Agentic Graphiti

set -e

# Garantizar que las rutas relativas operen desde la raíz del repo
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Verificar que estamos en el directorio correcto
if [ ! -f "pytest.ini" ]; then
    print_error "No se encontró pytest.ini. Ejecuta desde el directorio raíz del proyecto."
    exit 1
fi

# Función para ejecutar tests unitarios
run_unit_tests() {
    print_header "EJECUTANDO TESTS UNITARIOS"
    echo "Estos tests son rápidos y no requieren servicios externos."
    echo ""
    python -m pytest tests/unit/ --tb=short -v --strict-markers -ra
}

# Función para ejecutar tests de integración
run_integration_tests() {
    if [ "$RUN_INTEGRATION" != "1" ]; then
        print_error "Los tests de integración requieren RUN_INTEGRATION=1"
        echo "Ejecuta: export RUN_INTEGRATION=1"
        echo "O usa: RUN_INTEGRATION=1 $0 integration"
        exit 1
    fi
    
    print_header "EJECUTANDO TESTS DE INTEGRACIÓN"
    echo "Estos tests pueden requerir servicios externos (Weaviate, etc.)"
    echo ""
    python -m pytest tests/integration/ --tb=short -v --strict-markers -ra
}

# Función para ejecutar todos los tests
run_all_tests() {
    print_header "EJECUTANDO TODOS LOS TESTS"
    echo "Nota: Los tests de integración se saltan a menos que RUN_INTEGRATION=1"
    echo ""
    python -m pytest --tb=short -v --strict-markers -ra
}

# Función para ejecutar tests con cobertura
run_coverage_tests() {
    print_header "EJECUTANDO TESTS CON COBERTURA"
    echo ""
    python -m pytest --cov=src --cov-report=term --cov-report=html:coverage_html --tb=short -v --strict-markers -ra
}

# Función para ejecutar tests específicos
run_specific_tests() {
    print_header "EJECUTANDO TESTS ESPECÍFICOS: $1"
    echo ""
    python -m pytest "$1" --tb=short -v --strict-markers -ra
}

# Función para mostrar ayuda
show_help() {
    echo "Uso: $0 [comando]"
    echo ""
    echo "Comandos:"
    echo "  unit        Ejecutar solo tests unitarios (rápidos)"
    echo "  integration Ejecutar tests de integración (requiere RUN_INTEGRATION=1)"
    echo "  all         Ejecutar todos los tests (default)"
    echo "  coverage    Ejecutar tests con reporte de cobertura"
    echo "  path        Ejecutar tests en una ruta específica"
    echo "  help        Mostrar esta ayuda"
    echo ""
    echo "Ejemplos:"
    echo "  $0 unit                    # Solo tests unitarios"
    echo "  $0 all                     # Todos los tests"
    echo "  $0 coverage                # Tests con cobertura"
    echo "  RUN_INTEGRATION=1 $0 integration  # Tests de integración"
    echo "  $0 tests/unit/rag/         # Tests en directorio específico"
    echo ""
    echo "Variables de entorno:"
    echo "  RUN_INTEGRATION=1  Habilita tests de integración"
}

# Procesar argumentos
case "${1:-all}" in
    unit)
        run_unit_tests
        ;;
    integration)
        run_integration_tests
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
        # Si el argumento es una ruta, ejecutar tests en esa ruta
        if [ -d "$1" ] || [ -f "$1" ]; then
            run_specific_tests "$1"
        else
            print_error "Comando no reconocido: $1"
            echo ""
            show_help
            exit 1
        fi
        ;;
esac
