#!/bin/bash
set -euo pipefail

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not available. Run this on the host."
  exit 1
fi

echo "Stopping tool-archive socket and service..."
systemctl --user stop tool-archive.socket || true
systemctl --user stop tool-archive.service || true

echo "Reloading systemd user units..."
systemctl --user daemon-reload

echo "Starting tool-archive socket..."
systemctl --user start tool-archive.socket

echo "Activating socket (health check)..."
if curl -s -f http://127.0.0.1:9101/healthz >/dev/null 2>&1; then
  echo "  tool-archive ready"
else
  echo "  WARNING: tool-archive did not respond on :9101"
fi

echo "Done."
