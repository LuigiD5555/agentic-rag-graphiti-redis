# Integración de Preprocessing Tools en el Pipeline de Ingesta

## ¿Qué hace el sistema de preprocessing?

El preprocessor **intercepta automáticamente** archivos que necesitan conversión antes de la ingesta y los procesa usando las herramientas socket-activated.

### Flujo Automático

```
Usuario ejecuta comando de ingesta
         ↓
FileDiscoveryService encuentra archivos
         ↓
FilePreprocessor revisa cada archivo:
         ↓
    ¿Es DOCX/XLSX/PPTX? → tool-office convierte a TXT
    ¿Es ZIP/7z/tar?     → tool-extractor extrae contenido
    ¿Es PNG/JPG? (OCR)  → tool-ocr extrae texto
         ↓
Archivo procesado → Pipeline de ingesta normal
         ↓
Embeddings → Vector Store
```

## Configuración (.env)

Ya está configurado en tu `.env` al final del archivo:

```bash
# Habilitar/deshabilitar herramientas
ENABLE_OFFICE_CONVERSION=true   # ✅ Habilitado
ENABLE_EXTRACTOR_EXTRACTION=true  # ✅ Habilitado
ENABLE_OCR=false                # ❌ Deshabilitado (más lento)

# URLs de las herramientas (socket-activated)
TOOL_OFFICE_URL=http://127.0.0.1:9102
TOOL_FILEEXTRACTOR_URL=http://127.0.0.1:9101
TOOL_OCR_URL=http://127.0.0.1:9103

# Límites de seguridad
ARCHIVE_MAX_SIZE_MB=500
TOOL_REQUEST_TIMEOUT=120
```

## Integración en el Código

### Opción 1: Integración en file_processor.py (Recomendado)

Modifica `src/ingestion/pipeline/file_processor.py` para preprocesar antes de la carga:

```python
# Al inicio del archivo
from src.ingestion.preprocessor import get_preprocessor

def process_candidate_file(
    pipeline: Any,
    full_path: str,
    catalog: IngestionCatalog,
    estimate_lock: threading.Lock,
) -> tuple[int, int]:
    """Process a single candidate file through the pipeline."""

    # NUEVO: Preprocesar archivo si es necesario
    preprocessor = get_preprocessor()
    file_path = Path(full_path)

    if preprocessor.should_preprocess(file_path):
        logger.info(f"Preprocessing {file_path.name}...")
        processed_path = preprocessor.preprocess(file_path)

        if processed_path is None:
            # Preprocessing falló
            logger.error(f"Failed to preprocess {file_path}")
            return 0, 0

        if processed_path.is_dir():
            # File extraction → procesar cada archivo extraído
            logger.info(f"Extractor extracted to {processed_path}, processing contents...")
            total_chunks = 0
            total_embeddings = 0
            for extracted_file in processed_path.rglob("*"):
                if extracted_file.is_file():
                    chunks, embeds = process_candidate_file(
                        pipeline, str(extracted_file), catalog, estimate_lock
                    )
                    total_chunks += chunks
                    total_embeddings += embeds
            return total_chunks, total_embeddings

        # Usar archivo procesado en lugar del original
        full_path = str(processed_path)
        logger.info(f"Using preprocessed file: {processed_path.name}")

    # Continuar con el procesamiento normal...
    # (resto del código existente)
```

### Opción 2: Integración en orchestrator.py

Alternativamente, preprocesa en el orquestador antes de pasar al pipeline:

```python
# En src/ingestion/orchestrator.py

from src.ingestion.preprocessor import get_preprocessor

class IngestionOrchestrator:
    def __init__(self, config: Config) -> None:
        # ... código existente ...

        # NUEVO: Inicializar preprocessor
        self._preprocessor = get_preprocessor()

        # Log status
        status = self._preprocessor.get_status()
        log.info("Preprocessing tools status: %s", status)

    def run(self, options: IngestionOptions) -> None:
        # ... código existente hasta discovery ...

        candidates, visited_dirs = self._discover_files(options)

        # NUEVO: Preprocesar archivos antes del pipeline
        preprocessed_candidates = self._preprocess_candidates(candidates)

        # Continuar con el pipeline usando archivos preprocesados
        candidates = sort_paths_by_size_desc(preprocessed_candidates)
        # ... resto del código ...

    def _preprocess_candidates(self, candidates: List[str]) -> List[str]:
        """Preprocess files that need conversion."""
        preprocessed = []

        for file_path in candidates:
            path = Path(file_path)

            if self._preprocessor.should_preprocess(path):
                log.info(f"Preprocessing: {path.name}")
                processed = self._preprocessor.preprocess(path)

                if processed is None:
                    log.warning(f"Skipping {path} (preprocessing failed)")
                    continue

                if processed.is_dir():
                    # Extractor extraído → agregar todos los archivos
                    for extracted in processed.rglob("*"):
                        if extracted.is_file():
                            preprocessed.append(str(extracted))
                else:
                    # Archivo convertido → usar versión procesada
                    preprocessed.append(str(processed))
            else:
                # No necesita preprocessing → usar original
                preprocessed.append(file_path)

        log.info(f"Preprocessing complete: {len(candidates)} → {len(preprocessed)} files")
        return preprocessed
```

## Comportamiento Específico por Tipo de Archivo

### Office Documents (.docx, .xlsx, .pptx)

**Qué hace:**
- Convierte a texto plano usando LibreOffice headless
- Usa tool-office (socket 9102)
- Guarda en `/tmp/rag-preprocessing/<filename>.txt`

**Ejemplo:**
```
Input:  /mnt/documents/report.docx
        ↓ (tool-office)
Output: /tmp/rag-preprocessing/report.txt
        ↓ (pipeline normal)
Chunks → Embeddings → Weaviate
```

**Habilitado:** ✅ Por defecto (`ENABLE_OFFICE_CONVERSION=true`)

### Extractors (.zip, .7z, .tar, .tar.gz)

**Qué hace:**
- Extrae el archivo completo
- Usa tool-extractor (socket 9101)
- Guarda en `/tmp/rag-preprocessing/<archive_name>/`
- Procesa **cada archivo extraído** recursivamente

**Ejemplo:**
```
Input:  /mnt/docs/project.zip
        ↓ (tool-extractor)
Output: /tmp/rag-preprocessing/project/
        ├── file1.txt
        ├── file2.pdf
        └── subdir/
            └── file3.md
        ↓ (procesar cada uno)
3 archivos → Pipeline → Embeddings
```

**Habilitado:** ✅ Por defecto (`ENABLE_EXTRACTOR_EXTRACTION=true`)

**Límites de seguridad:**
- Tamaño máximo: 500 MB (configurable con `ARCHIVE_MAX_SIZE_MB`)
- Máximo archivos: 10,000 (configurable con `ARCHIVE_MAX_FILES`)

### Images & Scanned PDFs (.png, .jpg, .pdf con OCR)

**Qué hace:**
- Extrae texto usando Tesseract OCR
- Usa tool-ocr (socket 9103)
- Guarda en `/tmp/rag-preprocessing/<filename>_ocr.txt`

**Ejemplo:**
```
Input:  /mnt/scans/document.pdf
        ↓ (tool-ocr)
Output: /tmp/rag-preprocessing/document_ocr.txt
        ↓ (pipeline normal)
Chunks → Embeddings → Weaviate
```

**Habilitado:** ❌ Por defecto (`ENABLE_OCR=false`)
- **Razón:** Más lento, puede no ser necesario para todos
- **Para habilitar:** `ENABLE_OCR=true` en `.env`

**Idiomas soportados:**
- `eng` (English) - por defecto
- `spa` (Spanish)
- `fra` (French)
- `deu` (German)

Configurar con: `OCR_DEFAULT_LANGUAGE=spa` en `.env`

## Activación de Sockets

**¡Importante!** Los sockets deben estar habilitados ANTES de ejecutar la ingesta:

```bash
# Habilitar sockets (solo una vez)
systemctl --user enable --now tool-office.socket
systemctl --user enable --now tool-extractor.socket

# Opcional (si quieres OCR)
systemctl --user enable --now tool-ocr.socket

# Verificar que estén activos
systemctl --user list-sockets | grep tool-
```

**Resultado esperado:**
```
127.0.0.1:9101  tool-extractor.socket  tool-extractor.service
127.0.0.1:9102  tool-office.socket   tool-office.service
127.0.0.1:9103  tool-ocr.socket      tool-ocr.service
```

## Comportamiento en Runtime

### Primera Petición (Cold Start)

```bash
# Tu comando de ingesta
python -m src.main

# Log de preprocessing:
INFO: Preprocessing report.docx...
INFO: Converting Office document: report.docx
# (5-10 segundos esperando que systemd inicie el contenedor)
INFO: Successfully converted report.docx → report.txt
INFO: Using preprocessed file: report.txt
```

**Primera vez:** 5-10 segundos (systemd inicia contenedor)

### Peticiones Subsiguientes (Warm)

```bash
# Segundo archivo DOCX
INFO: Preprocessing budget.xlsx...
INFO: Converting Office document: budget.xlsx
# (< 1 segundo, contenedor ya está corriendo)
INFO: Successfully converted budget.xlsx → budget.txt
```

**Siguientes:** < 1 segundo (contenedor ya activo)

## Logs y Debugging

### Ver si herramientas están disponibles

```python
from src.ingestion.preprocessor import get_preprocessor

preprocessor = get_preprocessor()
status = preprocessor.get_status()
print(status)
```

**Output esperado:**
```json
{
  "enabled": {
    "office": true,
    "archive": true,
    "ocr": false
  },
  "tools_available": {
    "office": true,    // ✅ Socket activo y respondiendo
    "archive": true,   // ✅ Socket activo y respondiendo
    "ocr": true        // ✅ Socket activo (aunque no habilitado)
  }
}
```

### Ver logs de preprocessing

```bash
# Durante ingesta, busca estas líneas:
grep -i "preprocessing\|converting\|extracting" <tu_log_file>
```

### Ver logs de herramientas

```bash
# Ver logs de tool-office
journalctl --user -u tool-office.service -f

# Ver logs de tool-extractor
journalctl --user -u tool-extractor.service -f
```

## Manejo de Errores

### Si una herramienta falla

El preprocessor **no bloqueará la ingesta**:

```python
if processed_path is None:
    log.warning(f"Skipping {file_path} (preprocessing failed)")
    continue  # Salta el archivo, continúa con el siguiente
```

**Opciones:**
1. **Saltar el archivo** (comportamiento actual)
2. **Usar archivo original** (fallback)
3. **Abortar ingesta** (estricto)

### Si socket no está activo

```
WARNING: Office tool not available at http://127.0.0.1:9102.
Make sure socket is enabled: systemctl --user status tool-office.socket
```

**Solución:**
```bash
systemctl --user enable --now tool-office.socket
```

## Testing

### Test rápido de preprocessing

```python
from pathlib import Path
from src.ingestion.preprocessor import get_preprocessor

preprocessor = get_preprocessor()

# Test Office conversion
docx_file = Path("/mnt/documents/test.docx")
if docx_file.exists():
    result = preprocessor.preprocess(docx_file)
    print(f"Result: {result}")

# Test File extraction
zip_file = Path("/mnt/documents/test.zip")
if zip_file.exists():
    result = preprocessor.preprocess(zip_file)
    print(f"Extracted to: {result}")
```

### Test de sockets manualmente

```bash
# Office
curl http://127.0.0.1:9102/healthz

# Extractor
curl http://127.0.0.1:9101/healthz

# OCR
curl http://127.0.0.1:9103/healthz
```

## Resumen

### ✅ Configurado Automáticamente

- URLs de herramientas en `.env`
- Office y Extractor habilitados por defecto
- Límites de seguridad configurados
- Timeouts razonables

### 🔧 Requiere Acción Manual

1. **Habilitar sockets** (una sola vez):
   ```bash
   systemctl --user enable --now tool-{office,archive}.socket
   ```

2. **Integrar en tu código** (elegir opción 1 o 2 arriba)

3. **Construir imágenes** (si no lo has hecho):
   ```bash
   cd tools && ./build-all.sh
   ```

### 🎯 Resultado Final

Tu comando de ingesta funcionará exactamente igual:

```bash
python -m src.main
```

Pero ahora:
- ✅ Archivos DOCX/XLSX/PPTX se convierten automáticamente a texto
- ✅ Archivos ZIP/7z/tar se extraen y procesan automáticamente
- ✅ Todo sucede transparentemente, sin intervención manual
- ✅ Las herramientas se activan solo cuando se necesitan
- ✅ Zero overhead cuando están idle

---

**Next:** Elige Opción 1 o 2 para integrar en tu código, y estarás listo!
