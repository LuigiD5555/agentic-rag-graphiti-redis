# Multilingual Tests / Pruebas Multilingües

Este directorio contiene pruebas para verificar el soporte multilingüe del sistema RAG.

This directory contains tests to verify the multilingual support of the RAG system.

## Archivos / Files

### test_language_detection.py
Script de prueba para la detección automática de idiomas.

Test script for automatic language detection.

**Uso / Usage:**
```bash
podman exec rag-graphiti-agentic_app_1 python tests/multilingual/test_language_detection.py
```

### test_ingestion.sh
Script de prueba para la ingesta de documentos multilingües.

Test script for multilingual document ingestion.

**Uso / Usage:**
```bash
./tests/multilingual/test_ingestion.sh
```

### test_data.txt
Archivo de datos de prueba con contenido en 10 idiomas diferentes:
- English
- Español (Spanish)
- 中文 (Chinese)
- 日本語 (Japanese)
- 한국어 (Korean)
- Русский (Russian)
- العربية (Arabic)
- Français (French)
- Deutsch (German)
- Português (Portuguese)

Test data file with content in 10 different languages.

## Ejecutar Todas las Pruebas / Run All Tests

```bash
# Detección de idiomas / Language detection
podman exec rag-graphiti-agentic_app_1 python tests/multilingual/test_language_detection.py

# Ingesta multilingüe / Multilingual ingestion
./tests/multilingual/test_ingestion.sh
```

## Resultados Esperados / Expected Results

Todas las pruebas deben:
- ✅ Detectar correctamente los 10 idiomas
- ✅ Ingestar el contenido sin errores de encoding
- ✅ Preservar todos los caracteres especiales

All tests should:
- ✅ Correctly detect all 10 languages
- ✅ Ingest content without encoding errors
- ✅ Preserve all special characters
