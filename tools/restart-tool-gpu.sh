#!/bin/bash
set -euo pipefail

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not available. Run this on the host."
  exit 1
fi

echo "Stopping tool-gpu socket and service..."
systemctl --user stop tool-gpu.socket || true
systemctl --user stop tool-gpu.service || true

echo "Reloading systemd user units..."
systemctl --user daemon-reload

echo "Starting tool-gpu socket..."
systemctl --user start tool-gpu.socket

echo "Activating socket (health check)..."
if curl -s -f http://127.0.0.1:9104/healthz >/dev/null 2>&1; then
  echo "  tool-gpu ready"
else
  echo "  WARNING: tool-gpu did not respond on :9104"
fi

echo "Done."
