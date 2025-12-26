#!/bin/bash
set -e

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not available. Run this on the host."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

if [ ! -f "$HOME/.config/systemd/user/tool-office.socket" ]; then
  echo "Installing systemd units..."
  "$SCRIPT_DIR/install-systemd.sh"
fi

echo "Enabling tool sockets (socket-activated services)..."
echo "Note: Only sockets are enabled, NOT services. Services start automatically on first request."
echo ""

# Ensure services are NOT enabled (socket activation only)
systemctl --user disable tool-office.service 2>/dev/null || true
systemctl --user disable tool-archive.service 2>/dev/null || true
systemctl --user disable tool-ocr.service 2>/dev/null || true
systemctl --user disable tool-gpu.service 2>/dev/null || true

# Enable and start ONLY the sockets
systemctl --user enable --now tool-office.socket
systemctl --user enable --now tool-archive.socket

if grep -q "ENABLE_OCR=true" .env 2>/dev/null; then
  systemctl --user enable --now tool-ocr.socket
fi

if grep -q "ENABLE_GPU_ACCELERATION=true" .env 2>/dev/null; then
  systemctl --user enable --now tool-gpu.socket
fi

echo "Warming up enabled tools..."

warmup() {
  local name=$1
  local port=$2
  local ok=0
  for _ in {1..10}; do
    if curl -s -f -m 3 "http://127.0.0.1:${port}/healthz" >/dev/null 2>&1; then
      ok=1
      break
    fi
    sleep 0.5
  done
  if [ "$ok" -eq 1 ]; then
    echo "  ${name} ready on :${port}"
  else
    echo "  ${name} not ready on :${port} (will start on first use)"
  fi
}

warmup "tool-office" "9102"
warmup "tool-archive" "9101"

if grep -q "ENABLE_OCR=true" .env 2>/dev/null; then
  warmup "tool-ocr" "9103"
fi

if grep -q "ENABLE_GPU_ACCELERATION=true" .env 2>/dev/null; then
  warmup "tool-gpu" "9104"
fi

echo "Done. Note: do not start tool-*.service directly; sockets will activate them on demand."
