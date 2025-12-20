#!/bin/bash
# Install systemd units to user directory

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "Installing RAG tool systemd units..."

# Create systemd user directory if it doesn't exist
mkdir -p "$SYSTEMD_USER_DIR"

# Copy socket and service files
for tool in office archive ocr gpu; do
    echo "Installing tool-$tool units..."
    cp "$PROJECT_ROOT/systemd/user/tool-$tool.socket" "$SYSTEMD_USER_DIR/"
    cp "$PROJECT_ROOT/systemd/user/tool-$tool.service" "$SYSTEMD_USER_DIR/"
done

# Create cache directories
echo ""
echo "Creating cache directories..."
mkdir -p "$HOME/.cache/rag-tools"/{office,archive,ocr,gpu}

# Reload systemd
echo ""
echo "Reloading systemd daemon..."
systemctl --user daemon-reload

echo ""
echo "==== Installation complete ===="
echo ""
echo "To enable and start the sockets:"
echo "  systemctl --user enable --now tool-office.socket"
echo "  systemctl --user enable --now tool-archive.socket"
echo "  systemctl --user enable --now tool-ocr.socket"
echo "  systemctl --user enable --now tool-gpu.socket"
echo ""
echo "To check status:"
echo "  systemctl --user status tool-office.socket"
echo "  systemctl --user list-sockets"
echo ""
echo "To test:"
echo "  curl http://127.0.0.1:9102/healthz  # office"
echo "  curl http://127.0.0.1:9101/healthz  # archive"
echo "  curl http://127.0.0.1:9103/healthz  # ocr"
echo "  curl http://127.0.0.1:9104/healthz  # gpu"
