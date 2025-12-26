#!/bin/bash
set -euo pipefail

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not available. Run this on the host."
  exit 1
fi

echo "Stopping tool-office socket and service..."
systemctl --user stop tool-office.socket || true
systemctl --user stop tool-office.service || true

echo "Reloading systemd user units..."
systemctl --user daemon-reload

echo "Starting tool-office socket..."
systemctl --user start tool-office.socket

echo "Activating socket (health check)..."
if curl -s -f http://127.0.0.1:9102/healthz >/dev/null 2>&1; then
  echo "  tool-office ready"
else
  echo "  WARNING: tool-office did not respond on :9102"
fi

echo "Verifying /work permissions..."
if podman exec -it rag-tool-office sh -lc 'id; ls -ld /work; touch /work/_test' >/dev/null 2>&1; then
  echo "  /work is writable"
else
  echo "  WARNING: /work is not writable (check --userns=keep-id and :Z)"
fi

echo "Done."
