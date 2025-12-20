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
| **tool-office** | 9102 | Office document conversion | LibreOffice, pdftotext |
| **tool-archive** | 9101 | Archive extraction | unzip, 7z, tar |
| **tool-ocr** | 9103 | Optical Character Recognition | Tesseract, poppler |
| **tool-gpu** | 9104 | GPU-accelerated processing | CUDA, PyTorch |

## How Socket Activation Works

```
User/RAG makes request to http://127.0.0.1:9102
         ↓
systemd detects connection on socket
         ↓
systemd starts tool-office.service
         ↓
service starts container on port 19102
         ↓
systemd-socket-proxyd bridges 9102 → 19102
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

This builds all four tool images:
- `rag-tool-office:latest`
- `rag-tool-archive:latest`
- `rag-tool-ocr:latest`
- `rag-tool-gpu:latest`

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
systemctl --user enable --now tool-office.socket
systemctl --user enable --now tool-archive.socket
systemctl --user enable --now tool-ocr.socket
systemctl --user enable --now tool-gpu.socket
```

### 4. Test

```bash
# Test office tool
curl http://127.0.0.1:9102/healthz

# Test archive tool
curl http://127.0.0.1:9101/healthz

# Test OCR tool
curl http://127.0.0.1:9103/healthz

# Test GPU tool
curl http://127.0.0.1:9104/healthz
```

The first request to each port will:
1. Trigger systemd to start the service
2. Start the container
3. Wait for healthcheck
4. Proxy the request

Subsequent requests will be instant (container is already running).

## Tool Details

### tool-office

**Convert Office documents to PDF/text/markdown**

Endpoints:
- `POST /convert` - Convert DOCX/XLSX/PPTX to PDF, TXT, or MD

Example:
```bash
curl -X POST http://127.0.0.1:9102/convert \
  -H "Content-Type: application/json" \
  -d '{
    "input_path": "/mnt/documents/report.docx",
    "output_format": "pdf"
  }'
```

### tool-archive

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

### tool-gpu

**GPU-accelerated processing**

Endpoints:
- `GET /gpu-info` - Check GPU availability
- `POST /gpu-ocr` - GPU-accelerated OCR (placeholder)
- `POST /benchmark` - GPU benchmark

Example:
```bash
curl http://127.0.0.1:9104/gpu-info
```

## Management Commands

### Check Socket Status

```bash
# List all sockets
systemctl --user list-sockets

# Check specific socket
systemctl --user status tool-office.socket
```

### Check Service Status

```bash
# Check if service is running
systemctl --user status tool-office.service

# View logs
journalctl --user -u tool-office.service -f
```

### Stop Services

Services will stop automatically when inactive. To stop manually:

```bash
systemctl --user stop tool-office.service
```

The socket remains active and will restart the service on next request.

### Disable Socket Activation

```bash
systemctl --user disable --now tool-office.socket
```

This completely disables the tool.

## Integration with RAG API

In your RAG API configuration (`.env` or settings):

```bash
TOOL_OFFICE_URL=http://127.0.0.1:9102
TOOL_ARCHIVE_URL=http://127.0.0.1:9101
TOOL_OCR_URL=http://127.0.0.1:9103
TOOL_GPU_URL=http://127.0.0.1:9104
```

Your ingestion pipeline can now call these endpoints as needed:

```python
import requests

# Convert DOCX to PDF
response = requests.post(
    "http://127.0.0.1:9102/convert",
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
journalctl --user -u tool-office.service -n 50
```

Try starting manually:
```bash
podman run --rm -p 127.0.0.1:19102:8000 rag-tool-office:latest
curl http://127.0.0.1:19102/healthz
```

### Socket not responding

Check socket status:
```bash
systemctl --user status tool-office.socket
```

Restart socket:
```bash
systemctl --user restart tool-office.socket
```

### Permission denied errors

Ensure cache directories exist and are writable:
```bash
ls -la ~/.cache/rag-tools/
```

### GPU tool issues

For `tool-gpu`, ensure:
1. NVIDIA drivers installed
2. `nvidia-container-toolkit` installed
3. CDI configured for Podman

Check GPU access:
```bash
podman run --rm --device=nvidia.com/gpu=all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

## Development

### Rebuild a Single Tool

```bash
cd tools/office
podman build -t rag-tool-office:latest .
```

### Test Locally (without systemd)

```bash
cd tools/office
podman run --rm -p 8000:8000 \
  -v ~/.cache/rag-tools/office:/work \
  -v /mnt:/mnt:ro \
  rag-tool-office:latest
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
| 9102 | 19102 | office | HTTP |
| 9103 | 19103 | ocr | HTTP |
| 9104 | 19104 | gpu | HTTP |

## License

Same as main project.
