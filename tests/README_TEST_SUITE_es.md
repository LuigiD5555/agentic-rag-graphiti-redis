# Test Suite para RAG Agentic Graphiti

Este directorio contiene todos los tests del proyecto organizados en una estructura que permite ejecutarlos fácilmente con pytest.

## Estructura de Tests

```
tests/
├── __init__.py
├── conftest.py              # Configuración compartida de pytest
├── test_suite.py           # Script principal para ejecutar tests
├── README_TEST_SUITE.md    # Esta documentación
├── infrastructure/         # Tests de infraestructura
├── integration/           # Tests de integración
│   ├── diagnostics/       # Tests de diagnóstico
│   ├── documents/         # Tests de documentos
│   ├── memory/           # Tests de memoria (algunos marcados como skip)
│   ├── messaging/        # Tests de mensajería
│   ├── ocr/             # Tests de OCR
│   └── rag/             # Tests de RAG
├── scripts/              # Scripts de verificación
├── systemd/             # Tests de systemd
├── tools/               # Herramientas de test
└── unit/                # Tests unitarios
    ├── infrastructure/  # Tests unitarios de infraestructura
    ├── ingestion/       # Tests unitarios de ingestión
    ├── multilingual/    # Tests unitarios multilingües
    ├── providers/       # Tests unitarios de proveedores
    ├── rag/            # Tests unitarios de RAG
    ├── storage/        # Tests unitarios de almacenamiento
    └── utils/          # Tests unitarios de utilidades
```

## Cómo Ejecutar los Tests

### Opción 1: Usando el Test Suite (Recomendado)

```bash
# Ejecutar todos los tests (unitarios por defecto)
python tests/test_suite.py all

# Solo tests unitarios
python tests/test_suite.py unit

# Tests de integración (requiere RUN_INTEGRATION=1)
export RUN_INTEGRATION=1
python tests/test_suite.py integration

# Tests con opción de setup-fallback
python tests/test_suite.py fallback

# Con reporte de cobertura
python tests/test_suite.py all --coverage
```

### Opción 2: Usando pytest directamente

```bash
# Todos los tests (unitarios por defecto, integración excluida a menos que RUN_INTEGRATION=1)
python -m pytest

# Solo tests unitarios (por directorio)
python -m pytest tests/unit/

# Solo tests de integración (por directorio, requiere RUN_INTEGRATION=1)
export RUN_INTEGRATION=1
python -m pytest tests/integration/

# Tests específicos por marcador (algunos tests tienen marcadores)
python -m pytest -m "not slow"          # Excluir tests lentos
python -m pytest -m infrastructure      # Solo tests de infraestructura
python -m pytest -m preflight          # Solo tests de pre-vuelo

# Con opciones adicionales
python -m pytest -v                    # Verboso
python -m pytest --tb=short            # Traceback corto
python -m pytest -x                    # Parar en el primer error
```

### Opción 3: Script de shell

```bash
# Ejecutar tests rápidos (solo unitarios)
./run_tests.sh

# Ejecutar todos los tests
./run_tests.sh all

# Ejecutar tests de integración
./run_tests.sh integration
```

## Marcadores de Tests

Los tests están organizados usando marcadores de pytest:

### Categorías principales
- `unit`: Tests unitarios (rápidos, sin dependencias externas)
- `integration`: Tests de integración (pueden requerir servicios externos)
- `slow`: Tests que toman tiempo significativo

### Dependencias externas
- `requires_weaviate`: Tests que requieren Weaviate
- `requires_neo4j`: Tests que requieren Neo4J (algunos marcados como skip)
- `requires_lmstudio`: Tests que requieren LM Studio

### Infraestructura
- `infrastructure`: Tests de infraestructura y sistema
- `preflight`: Verificaciones de pre-vuelo antes del inicio
- `volumes`: Verificación de volúmenes y configuración de fallback

## Configuración

### Variables de entorno
- `RUN_INTEGRATION=1`: Habilita la ejecución de tests de integración
- `USER_SETTINGS_FILE`: Archivo de configuración de usuario (aislado en tests)

### Archivo de configuración pytest.ini
El archivo `pytest.ini` en la raíz del proyecto configura:
- Patrones de descubrimiento de tests
- Marcadores personalizados
- Opciones por defecto (excluye tests de integración a menos que RUN_INTEGRATION=1)

## Tests Marcados como Skip

Algunos tests están marcados como `skip` por las siguientes razones:

1. **NER functionality not currently configured**: Tests que dependen de Named Entity Recognition
2. **External cache migration tests are obsolete**: The SQLite control plane now handles cache/checkpoint behavior, so those tests remain skipped until a SQLite-focused suite replaces them
3. **Memory integration tests require ChatMemory functionality which may not be configured**: Tests de integración de memoria

Para habilitar estos tests en el futuro, simplemente remover el decorador `@pytest.mark.skip`.

## Mejores Prácticas

1. **Antes de un Pull Request**: Ejecutar `python tests/test_suite.py all`
2. **Desarrollo local**: Ejecutar `python tests/test_suite.py unit` frecuentemente
3. **Verificación completa**: Ejecutar `RUN_INTEGRATION=1 python tests/test_suite.py integration` antes de releases
4. **Cobertura**: Usar `--coverage` para generar reportes de cobertura

## Solución de Problemas

### Error: "Set RUN_INTEGRATION=1 to run integration tests"
```bash
export RUN_INTEGRATION=1
```

### Error: Módulos no encontrados
Algunos tests pueden requerir dependencias adicionales. Verificar `requirements.txt`.

### Tests lentos
Usar `-m "not slow"` para excluir tests lentos durante el desarrollo.

### Tests específicos fallando
Ejecutar tests individualmente para debugging:
```bash
python -m pytest tests/unit/rag/test_rag_engine.py -v
