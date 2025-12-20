#!/bin/bash
# Build all tool images

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Building RAG tool images..."

# Build each tool
for tool in office archive ocr gpu; do
    echo ""
    echo "==== Building tool-$tool ===="
    cd "$tool"
    podman build -t "rag-tool-$tool:latest" .
    cd ..
    echo "OK tool-$tool built successfully"
done

echo ""
echo "==== All tools built successfully ===="
echo ""
echo "Images:"
podman images | grep rag-tool
