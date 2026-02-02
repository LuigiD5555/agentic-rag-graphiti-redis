# RAG Tools - Socket-Activated Microservices

This directory contains on-demand, socket-activated tools for document processing in the RAG pipeline.

## Architecture

Each tool is:
- **Containerized** (Podman)
- **Socket-activated** (systemd)
- **On-demand** (starts automatically on first request)
- **Isolated** (read-only containers, minimal capabilities)

### Tools Available

| Tool | Port | Purpose | Technologies |
|------|------|---------|--------------|
| **tool-document-processor** | 9106 | OCR + Office conversion | LibreOffice, Tesseract, poppler |
| **tool-extractor** | 9101 | File extraction | unzip, 7z, tar |
| **tool-ocr** | 9103 | Optical Character Recognition | Tesseract, poppler |
| **tool-monitoring** | 9107 | Code quality monitoring | vulture, coverage.py, AST analysis |

## How Socket Activation Works

```
User/RAG makes request to http://127.0.0.1:9106
         ↓
systemd detects connection on socket
         ↓
systemd starts tool-document-processor.service
         ↓
service starts container on port 19104
         ↓
systemd-socket-proxyd bridges 9106 → 19104
         ↓
request reaches container
```

**Benefits:**
- No resources consumed when idle
- Automatic startup on first request
- No manual container management needed
- Clean separation of concerns

## Quick Start

### 1. Build Images

```bash
cd tools
./build-all.sh
```

This builds the tool images:
- `rag-tool-document-processor:latest`
- `rag-tool-extractor:latest`
- `rag-tool-ocr:latest`
- `rag-tool-monitoring:latest`

### 2. Install systemd Units

```bash
./install-systemd.sh
```

This:
- Copies `.socket` and `.service` files to `~/.config/systemd/user/`
- Creates cache directories in `~/.cache/rag-tools/`
- Reloads systemd

### 3. Enable Sockets

```bash
systemctl --user enable --now tool-document-processor.socket
systemctl --user enable --now tool-extractor.socket
systemctl --user enable --now tool-ocr.socket
systemctl --user enable --now tool-monitoring.socket
```

### 4. Test

```bash
# Test document processor tool
curl http://127.0.0.1:9106/healthz

# Test archive tool
curl http://127.0.0.1:9101/healthz

# Test OCR tool
curl http://127.0.0.1:9103/healthz

# Test monitoring tool
curl http://127.0.0.1:9107/healthz

```

The first request to each port will:
1. Trigger systemd to start the service
2. Start the container
3. Wait for healthcheck
4. Proxy the request

Subsequent requests will be instant (container is already running).

## Tool Details

### tool-document-processor

**Convert Office documents to PDF/text/markdown (plus OCR endpoints)**

Endpoints:
- `POST /convert` - Convert DOCX/XLSX/PPTX to PDF, TXT, or MD

Example:
```bash
curl -X POST http://127.0.0.1:9106/convert \
  -H "Content-Type: application/json" \
  -d '{
    "input_path": "/mnt/documents/report.docx",
    "output_format": "pdf"
  }'
```

### tool-extractor

**Extract archives safely**

Endpoints:
- `POST /extract` - Extract ZIP, 7z, tar, etc.
- `POST /list` - List archive contents without extracting

Example:
```bash
curl -X POST http://127.0.0.1:9101/extract \
  -H "Content-Type: application/json" \
  -d '{
    "archive_path": "/mnt/documents/data.zip",
    "max_size_mb": 500
  }'
```

### tool-ocr

**OCR for images and PDFs**

Endpoints:
- `POST /ocr` - Perform OCR on image or PDF
- `POST /pdf-to-images` - Convert PDF pages to images

Example:
```bash
curl -X POST http://127.0.0.1:9103/ocr \
  -H "Content-Type: application/json" \
  -d '{
    "input_path": "/mnt/documents/scan.pdf",
    "language": "eng",
    "output_format": "txt"
  }'
```

### tool-monitoring

**Code quality monitoring and legacy code detection**

The monitoring tool provides comprehensive code quality analysis including:
- **Static analysis** with vulture for dead code detection
- **Dynamic analysis** with coverage.py for unused code paths
- **Real-time monitoring** for development environments
- **Pipeline classification** to identify code belonging to specific workflows
- **Legacy code detection** for unused integrations (qdrant, redis, etc.)

**Endpoints:**
- `GET /healthz` - Health check
- `POST /analyze/bloat` - Run bloat analysis (vulture + coverage)
- `POST /analyze/coverage` - Run coverage analysis only
- `POST /analyze/vulture` - Run vulture static analysis only
- `GET /reports/{report_type}` - Get analysis reports
- `POST /cleanup/legacy` - Run legacy code cleanup (interactive)

**Example: Run bloat analysis**
```bash
curl -X POST http://127.0.0.1:9107/analyze/bloat \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "development",
    "include_coverage": true,
    "include_vulture": true,
    "generate_reports": true
  }'
```

**Example: Get reports**
```bash
# Get bloat analysis report
curl http://127.0.0.1:9107/reports/bloat

# Get coverage report
curl http://127.0.0.1:9107/reports/coverage

# Get vulture report
curl http://127.0.0.1:9107/reports/vulture
```

**Environment Variables:**
The monitoring tool respects these environment variables:
- `ENABLE_COVERAGE_MONITORING` - Enable coverage.py dynamic analysis
- `ENABLE_VULTURE_MONITORING` - Enable vulture static analysis
- `ENABLE_REALTIME_MONITORING` - Enable real-time background monitoring
- `MONITORING_MODE` - "development" or "production"

## Management Commands

### Check Socket Status

```bash
# List all sockets
systemctl --user list-sockets

# Check specific socket
systemctl --user status tool-document-processor.socket
```

### Check Service Status

```bash
# Check if service is running
systemctl --user status tool-document-processor.service

# View logs
journalctl --user -u tool-document-processor.service -f
```

### Stop Services

Services will stop automatically when inactive. To stop manually:

```bash
systemctl --user stop tool-document-processor.service
```

The socket remains active and will restart the service on next request.

### Disable Socket Activation

```bash
systemctl --user disable --now tool-document-processor.socket
```

This completely disables the tool.

## Integration with RAG API

In your RAG API configuration (`.env` or settings):

```bash
TOOL_OFFICE_URL=http://127.0.0.1:9106
TOOL_EXTRACTOR_URL=http://127.0.0.1:9101
TOOL_OCR_URL=http://127.0.0.1:9103
```

Your ingestion pipeline can now call these endpoints as needed:

```python
import requests

# Convert DOCX to PDF
response = requests.post(
    "http://127.0.0.1:9106/convert",
    json={
        "input_path": "/mnt/documents/report.docx",
        "output_format": "pdf"
    }
)

if response.json()["success"]:
    pdf_path = response.json()["output_path"]
    # Process PDF...
```

## Security

Each tool runs with:
- **Non-root user** (`tooluser`, UID 1000)
- **Read-only root filesystem** (`--read-only`)
- **No new privileges** (`--security-opt=no-new-privileges`)
- **All capabilities dropped** (`--cap-drop=all`)
- **Limited mounts:**
  - `/mnt` (read-only) - input files
  - `~/.cache/rag-tools/<tool>` (read-write) - work directory
  - `/tmp` (tmpfs) - temporary files

## Troubleshooting

### Container won't start

Check logs:
```bash
journalctl --user -u tool-document-processor.service -n 50
```

Try starting manually:
```bash
podman run --rm -p 127.0.0.1:19104:8000 rag-tool-document-processor:latest
curl http://127.0.0.1:19104/healthz
```

### Socket not responding

Check socket status:
```bash
systemctl --user status tool-document-processor.socket
```

Restart socket:
```bash
systemctl --user restart tool-document-processor.socket
```

### Permission denied errors

Ensure cache directories exist and are writable:
```bash
ls -la ~/.cache/rag-tools/
```

## Development

### Rebuild a Single Tool

```bash
cd tools/office
podman build -t rag-tool-document-processor:latest .
```

### Test Locally (without systemd)

```bash
cd tools/office
podman run --rm -p 8000:8000 \
  -v ~/.cache/rag-tools/office:/work \
  -v /mnt:/mnt:ro \
  rag-tool-document-processor:latest
```

Then test:
```bash
curl http://localhost:8000/healthz
```

### Add a New Tool

1. Create directory: `tools/newtool/`
2. Add `src/app.py` with FastAPI app
3. Add `Dockerfile` and `requirements.txt`
4. Create systemd units (see existing examples)
5. Choose a port (e.g., 9105 external, 19105 internal)
6. Update `build-all.sh` and `install-systemd.sh`

## Advanced: Automatic Shutdown

Currently, containers stay running once started. To add automatic shutdown after idle:

**Option 1:** Add idle detection to the tool's Python app
```python
import threading
import time

last_request = time.time()

@app.middleware("http")
async def track_requests(request, call_next):
    global last_request
    last_request = time.time()
    return await call_next(request)

def idle_shutdown():
    while True:
        if time.time() - last_request > 300:  # 5 min
            os._exit(0)
        time.sleep(60)

threading.Thread(target=idle_shutdown, daemon=True).start()
```

**Option 2:** Use systemd idle timeout (requires systemd 256+)
```ini
[Service]
RuntimeMaxSec=300
```

## Port Reference

| Port | Internal Port | Tool | Protocol |
|------|---------------|------|----------|
| 9101 | 19101 | archive | HTTP |
| 9106 | 19104 | document-processor | HTTP |
| 9103 | 19103 | ocr | HTTP |
| 9107 | 19107 | monitoring | HTTP |

## License

Same as main project.
