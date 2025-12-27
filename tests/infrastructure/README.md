# Infrastructure Tests

Tests de verificación de infraestructura y configuración del sistema.

## Overview

Este directorio contiene tests de infraestructura que verifican que el sistema esté correctamente configurado antes de iniciarse:

- **Pre-flight Checks** ([test_preflight.py](test_preflight.py)): Verificaciones completas del sistema antes de iniciar
- **Volume Checks** ([test_volumes.py](test_volumes.py)): Verificación de volúmenes externos y setup de fallbacks

## Pre-Flight Checks (`test_preflight.py`)

Suite completa de verificaciones del sistema que se ejecutan antes de levantar los servicios.

### Categorías de Tests

1. **System Commands**: Verifica que comandos requeridos estén instalados
   - `podman`, `systemctl`, `curl`, `python3`
   - `podman-compose` o `podman compose`
   - `pytest`

2. **Configuration Files**: Valida archivos de configuración
   - Existencia de `podman-compose.yml`
   - YAML válido y bien formado
   - Servicios requeridos definidos
   - Archivo `.env` o `.env.example`

3. **Podman Configuration**: Verifica configuración de Podman
   - Podman está corriendo y accesible
   - Versión de Podman
   - Socket de Podman habilitado

4. **Python Environment**: Valida entorno Python
   - Python 3.9+
   - Paquetes requeridos instalados

5. **Directory Structure**: Verifica estructura de directorios
   - Directorio `src/` existe
   - Directorios `data/` y `.volumes/` accesibles

6. **Port Availability**: Verifica disponibilidad de puertos
   - 8080 (Weaviate), 7474/7687 (Neo4j), 6379 (Redis)
   - 8000 (RAG API), 5555 (Open WebUI)

7. **System Resources**: Verifica recursos del sistema
   - Espacio en disco suficiente (≥5GB recomendado)
   - Memoria disponible (≥4GB recomendado)

### Uso

```bash
# Ejecutar todos los pre-flight checks
pytest tests/infrastructure/test_preflight.py -v

# Ejecutar en modo silencioso (para scripts)
pytest tests/infrastructure/test_preflight.py -q

# Ejecutar solo verificaciones de comandos
pytest tests/infrastructure/test_preflight.py::TestSystemCommands -v

# Ejecutar solo verificaciones de puertos
pytest tests/infrastructure/test_preflight.py::TestPortAvailability -v

# Usar marker
pytest -m preflight -v
```

### Integración con start-everything.sh

El script [start-everything.sh](../../start-everything.sh) ejecuta estos checks en el STEP 1.5:

```bash
python3 -m pytest tests/infrastructure/test_preflight.py -v --tb=short
```

Si algún check falla, el script pregunta si deseas continuar de todas formas.

### Ejemplo de Salida (Pre-flight)

```text
====================================================================
Pre-Flight Checks Summary
====================================================================

✓ All pre-flight checks passed

System is ready to start:
  - Required commands installed
  - Configuration files valid
  - Python environment ready
  - Podman configured
  - Sufficient resources available

====================================================================
```

## Volume Tests (`test_volumes.py`)

Tests para verificar que los volúmenes externos estén disponibles y configurar directorios de fallback cuando sea necesario.

### Uso Básico

```bash
# Ejecutar todos los tests de volúmenes (solo verificación)
pytest tests/infrastructure/test_volumes.py -v

# Ejecutar con setup de fallback (usado por start-everything.sh)
pytest tests/infrastructure/test_volumes.py::TestVolumeIntegration::test_libros_volume_with_fallback_setup --setup-fallback -v -s

# Ejecutar solo tests de accesibilidad
pytest tests/infrastructure/test_volumes.py::TestVolumeAccessibility -v

# Ejecutar solo tests de fallback
pytest tests/infrastructure/test_volumes.py::TestFallbackSetup -v
```

### Markers

Los tests tienen markers especiales para ejecución selectiva:

```bash
# Ejecutar solo tests de infraestructura
pytest -m infrastructure -v

# Ejecutar solo tests de volúmenes
pytest -m volumes -v

# Excluir tests de infraestructura
pytest -m "not infrastructure" -v
```

### Opciones de Línea de Comandos

- `--setup-fallback`: Crea directorios de fallback cuando los volúmenes no estén accesibles
  - Sin esta opción, solo verifica y reporta el estado
  - Con esta opción, configura fallbacks automáticamente

### Qué Hacen los Tests

1. **TestVolumeAccessibility**: Verifica que podemos detectar si los volúmenes están accesibles
   - `test_libros_volume_check`: Verifica el volumen de Libros
   - `test_volume_timeout_handling`: Verifica que los timeouts funcionen correctamente

2. **TestFallbackSetup**: Verifica la creación de directorios de fallback
   - `test_fallback_directory_creation`: Verifica creación de directorios
   - `test_volume_marker_creation`: Verifica creación de markers
   - `test_fallback_marker_removal`: Verifica limpieza de markers

3. **TestVolumeIntegration**: Test de integración completo
   - `test_libros_volume_with_fallback_setup`: Flujo completo de verificación y setup
   - `test_env_file_update`: Verifica actualización del archivo .env

### Integración con start-everything.sh (Volumes)

El script [start-everything.sh](../../start-everything.sh) usa este test en el STEP 4:

```bash
python3 -m pytest tests/infrastructure/test_volumes.py::TestVolumeIntegration::test_libros_volume_with_fallback_setup --setup-fallback -v -s
```

Esto:

1. Verifica que los volúmenes externos estén disponibles
2. Si no lo están, crea directorios de fallback automáticamente
3. Actualiza el archivo `.env` con la ruta activa (`ACTIVE_LIBROS_DIR`)
4. Crea archivos marker para documentar el estado

### Archivos Generados

El test puede generar:

- **`.env`**: Actualizado con `ACTIVE_LIBROS_DIR=<path>`
- **`<fallback_dir>/.using-fallback`**: Marker que indica uso de fallback
- **`<primary_dir>/.volume-available`**: Marker que indica volumen disponible

### Ejemplo de Salida (Volumes)

```text
====================================================================
Volume Check Summary
====================================================================

✓ All volumes are accessible

Primary volumes in use:
  - Libros: /mnt/resources/Libros

Volume check complete. Safe to start containers.
```

O si hay problemas:

```text
====================================================================
Volume Check Summary
====================================================================

⚠ Using fallback directories

Active directories:
  - Libros: ./data/libros-fallback (FALLBACK)

Note: Containers will start successfully using fallback directories.
      Once you fix the volume issues, restart containers to use primary volumes.

Volume check complete. Safe to start containers.
```

## Ventajas sobre check-volumes.sh

Este enfoque en Python tiene varias ventajas sobre el script bash anterior:

1. **Testeable**: Cada función tiene tests unitarios
2. **Mantenible**: Código más claro y estructurado
3. **Reutilizable**: Se puede importar como módulo
4. **Consistente**: Mismo lenguaje que el resto del proyecto
5. **Mejor manejo de errores**: Excepciones tipadas
6. **IDE support**: Autocompletado, type hints, etc.
