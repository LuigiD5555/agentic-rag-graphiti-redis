# Weaviate Tests

Este directorio contiene scripts de verificación y pruebas para Weaviate.

This directory contains verification scripts and tests for Weaviate.

## Archivos / Files

### verify_data.py
Script para verificar los datos almacenados en Weaviate.

Script to verify data stored in Weaviate.

**Uso / Usage:**
```bash
python tests/weaviate/verify_data.py
```

**Funcionalidad / Functionality:**
- Verifica la conexión a Weaviate
- Lista todas las colecciones/clases
- Muestra estadísticas de documentos
- Verifica la integridad de los datos

## Requisitos / Requirements

- Weaviate debe estar ejecutándose (puerto 8080)
- Variables de entorno configuradas en `.env`

- Weaviate must be running (port 8080)
- Environment variables configured in `.env`
