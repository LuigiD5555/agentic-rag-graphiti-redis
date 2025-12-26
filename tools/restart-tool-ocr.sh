#!/bin/bash
set -euo pipefail

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not available. Run this on the host."
  exit 1
fi

echo "Stopping tool-ocr socket and service..."
systemctl --user stop tool-ocr.socket || true
systemctl --user stop tool-ocr.service || true

echo "Reloading systemd user units..."
systemctl --user daemon-reload

echo "Starting tool-ocr socket..."
systemctl --user start tool-ocr.socket

echo "Activating socket (health check)..."
if curl -s -f http://127.0.0.1:9103/healthz >/dev/null 2>&1; then
  echo "  tool-ocr ready"
else
  echo "  WARNING: tool-ocr did not respond on :9103"
fi

echo "Done."
