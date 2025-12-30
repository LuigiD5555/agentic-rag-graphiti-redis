# Preprocessing Tools Integration in the Ingestion Pipeline

## What the preprocessing system does

The preprocessor automatically intercepts files that need conversion before ingestion and processes them using socket-activated tools.

### Automatic Flow

```
User runs ingestion command
         ↓
FileDiscoveryService finds files
         ↓
FilePreprocessor checks each file:
         ↓
    DOCX/XLSX/PPTX?  -> tool-office converts to TXT
    ZIP/7z/tar?      -> tool-extractor extracts content
    PNG/JPG? (OCR)   -> tool-ocr extracts text
         ↓
Processed file -> Normal ingestion pipeline
         ↓
Embeddings -> Vector Store
```

## Configuration (.env)

Configured at the end of your `.env` file:

```bash
# Enable/disable tools
ENABLE_OFFICE_CONVERSION=true
ENABLE_EXTRACTOR_EXTRACTION=true
ENABLE_OCR=false

# Tool URLs (socket-activated)
TOOL_OFFICE_URL=http://127.0.0.1:9102
TOOL_FILEEXTRACTOR_URL=http://127.0.0.1:9101
TOOL_OCR_URL=http://127.0.0.1:9103

# Safety limits
ARCHIVE_MAX_SIZE_MB=500
TOOL_REQUEST_TIMEOUT=120
```

## Code Integration

### Option 1: Integrate in `file_processor.py` (recommended)

Modify `src/ingestion/pipeline/file_processor.py` to preprocess before loading:

```python
# At the top of the file
from src.ingestion.preprocessor import get_preprocessor

def process_candidate_file(
    pipeline: Any,
    full_path: str,
    catalog: IngestionCatalog,
    estimate_lock: threading.Lock,
) -> tuple[int, int]:
    """Process a single candidate file through the pipeline."""

    # NEW: Preprocess file if needed
    preprocessor = get_preprocessor()
    file_path = Path(full_path)

    if preprocessor.should_preprocess(file_path):
        logger.info(f"Preprocessing {file_path.name}...")
        processed_path = preprocessor.preprocess(file_path)

        if processed_path is None:
            logger.error(f"Failed to preprocess {file_path}")
            return 0, 0

        if processed_path.is_dir():
            # File extraction -> process each extracted file
            logger.info(
                f"Extractor extracted to {processed_path}, processing contents..."
            )
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

        # Use processed file instead of the original
        full_path = str(processed_path)
        logger.info(f"Using preprocessed file: {processed_path.name}")

    # Continue with normal processing...
```

### Option 2: Integrate in `orchestrator.py`

Preprocess in the orchestrator before passing to the pipeline:

```python
# In src/ingestion/orchestrator.py

from src.ingestion.preprocessor import get_preprocessor

class IngestionOrchestrator:
    def __init__(self, config: Config) -> None:
        # ... existing code ...

        # NEW: Initialize preprocessor
        self._preprocessor = get_preprocessor()

        # Log status
        status = self._preprocessor.get_status()
        log.info("Preprocessing tools status: %s", status)

    def run(self, options: IngestionOptions) -> None:
        # ... existing code until discovery ...
        pass
```

## File-Type Behavior

### Office files (DOCX/XLSX/PPTX)
- Converted to text with `tool-office`.
- The converted `.txt` is ingested instead of the original.

### Archives (ZIP/7z/tar)
- Extracted with `tool-extractor`.
- Each extracted file is processed recursively.

### Images (PNG/JPG) with OCR
- OCR runs only if `ENABLE_OCR=true`.
- The extracted text is ingested.

## Safety Limits

- Max archive size: `ARCHIVE_MAX_SIZE_MB` (default 500 MB)
- Tool request timeout: `TOOL_REQUEST_TIMEOUT` (default 120s)

## Logs and Debugging

- Check tool status in logs when the orchestrator starts.
- Use `podman-compose logs -f` to follow ingestion logs.

## Next Steps

Choose Option 1 or 2 and integrate it into your codebase.
