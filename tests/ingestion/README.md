# Ingestion Tests

Este directorio contiene scripts de verificación para el proceso de ingesta.

This directory contains verification scripts for the ingestion process.

## Archivos / Files

### verify_streaming.py
Script para verificar la ingesta en modo streaming.

Script to verify streaming ingestion mode.

**Uso / Usage:**
```bash
python tests/ingestion/verify_streaming.py
```

**Funcionalidad / Functionality:**
- Verifica el procesamiento de archivos en streaming
- Monitorea el progreso de ingesta
- Valida la integridad de los chunks generados
