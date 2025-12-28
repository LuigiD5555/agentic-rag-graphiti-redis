#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/podman-compose.yml}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-rag-graphiti-agentic}"

DATE_DIR="$(date +%F)"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="$ROOT_DIR/logs/$DATE_DIR/$RUN_ID"

mkdir -p "$OUT_DIR/containers"
ln -sfn "$OUT_DIR" "$ROOT_DIR/logs/latest" 2>/dev/null || true

if ! command -v journalctl >/dev/null 2>&1; then
  echo "ERROR: 'journalctl' is not installed or not in PATH." >&2
  exit 1
fi

if ! command -v podman >/dev/null 2>&1; then
  echo "ERROR: 'podman' is not installed or not in PATH." >&2
  exit 1
fi

{
  echo "run_id=$RUN_ID"
  echo "date=$DATE_DIR"
  echo "project_name=$PROJECT_NAME"
  echo "compose_file=$COMPOSE_FILE"
  echo "pwd=$(pwd)"
  echo "host=$(hostname 2>/dev/null || true)"
  echo "user=$(id -un 2>/dev/null || true)"
} >"$OUT_DIR/meta.txt"

podman --version >"$OUT_DIR/podman_version.txt" 2>&1 || true
podman ps -a --no-trunc >"$OUT_DIR/podman_ps_a.txt" 2>&1 || true

if command -v podman-compose >/dev/null 2>&1; then
  podman-compose -f "$COMPOSE_FILE" ps >"$OUT_DIR/podman_compose_ps.txt" 2>&1 || true
fi

# Capture a time "window" for this export so results are reproducible.
SINCE="${SINCE:-24 hours ago}"
UNTIL="${UNTIL:-now}"
{
  echo "since=$SINCE"
  echo "until=$UNTIL"
} >"$OUT_DIR/window.txt"

CONTAINERS_TSV="$OUT_DIR/containers/list.tsv"
podman ps -a \
  --filter "label=io.podman.compose.project=$PROJECT_NAME" \
  --format '{{.Names}}\t{{.ID}}\t{{.Status}}' >"$CONTAINERS_TSV" 2>/dev/null || true

if [[ ! -s "$CONTAINERS_TSV" ]]; then
  echo "WARN: No containers found with compose project label '$PROJECT_NAME'." >"$OUT_DIR/no_containers_found.txt"
  echo "$OUT_DIR"
  exit 0
fi

dump_one() {
  local container_name="$1"
  local out_file="$2"
  local inspect_file="$3"
  local meta_file="$4"

  podman inspect "$container_name" >"$inspect_file" 2>&1 || true

  {
    echo "container_name=$container_name"
    echo "since=$SINCE"
    echo "until=$UNTIL"
  } >"$meta_file"

  # Try the system journal first; if empty, fall back to --user (rootless).
  journalctl \
    -o short-iso \
    "CONTAINER_NAME=$container_name" \
    --since "$SINCE" --until "$UNTIL" >"$out_file" 2>/dev/null || true

  if [[ ! -s "$out_file" ]]; then
    journalctl --user \
      -o short-iso \
      "CONTAINER_NAME=$container_name" \
      --since "$SINCE" --until "$UNTIL" >"$out_file" 2>/dev/null || true
  fi
}

COMBINED="$OUT_DIR/all_containers.log"
: >"$COMBINED"

while IFS=$'\t' read -r name cid status; do
  safe_name="${name//\//_}"
  dump_one \
    "$name" \
    "$OUT_DIR/containers/$safe_name.journal.log" \
    "$OUT_DIR/containers/$safe_name.podman.inspect.json" \
    "$OUT_DIR/containers/$safe_name.meta.txt"

  {
    echo "===== $name ($cid) ====="
    cat "$OUT_DIR/containers/$safe_name.journal.log" 2>/dev/null || true
    echo
  } >>"$COMBINED"
done <"$CONTAINERS_TSV"

echo "$OUT_DIR"
