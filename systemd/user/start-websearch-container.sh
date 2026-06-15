#!/bin/bash
# Wrapper script to start SearXNG container with correct paths

set -e

# Define paths (use real path, not symlink)
CONFIG_DIR="/mnt/Documents/Documents/Programacion/Proyectos_Programacion/RAG Project/rag-agentic-graphiti/config/searxng"
CACHE_DIR="$HOME/.cache/rag-tools/websearch"

# Generate secret
SEARXNG_SECRET=$(openssl rand -hex 32)

# Start container
/usr/bin/podman run -d --name rag-tool-websearch \
  --pull=never \
  -p 127.0.0.1:19105:8080 \
  --security-opt=no-new-privileges \
  --cap-drop=all \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /var/log/uwsgi \
  -v "${CACHE_DIR}:/var/cache/searxng:rw" \
  -v "${CONFIG_DIR}:/etc/searxng:ro" \
  -e SEARXNG_SECRET="${SEARXNG_SECRET}" \
  localhost/rag-tool-websearch:latest
