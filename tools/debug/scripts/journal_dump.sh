#!/usr/bin/env bash
set -euo pipefail

# journal_dump.sh
#
# Exports logs for every Podman container that belongs to a `podman-compose`
# project, using journald as the source of truth.
#
# What it does:
# - Discovers containers by the `io.podman.compose.project` label.
# - Captures a reproducible time window (`SINCE` -> `UNTIL`) per container.
# - Tries the system journal first and falls back to `journalctl --user`
#   for rootless setups when needed.
# - Writes per-container logs, `podman inspect` output, metadata, and a merged
#   `all_containers.log`.
# - Updates the `tools/debug/logs/latest` symlink to point at the newest dump.
#
# Output layout:
#   tools/debug/logs/YYYY-MM-DD/HHMMSS/
#     meta.txt
#     window.txt
#     all_containers.log
#     containers/
#       <container>.journal.log
#       <container>.podman.inspect.json
#       <container>.meta.txt
#
# Environment variables:
# - `COMPOSE_PROJECT_NAME`: compose project name. Default: `rag-graphiti-agentic`.
# - `COMPOSE_FILE`: compose file path stored in metadata for traceability.
# - `SINCE`: `journalctl` start window. Default: `24 hours ago`.
# - `UNTIL`: `journalctl` end window. Default: `now`.
#
# Examples:
#   # Export the last 24 hours for the default project
#   tools/debug/scripts/journal_dump.sh
#
#   # Export only the last hour for a different compose project
#   COMPOSE_PROJECT_NAME=my-stack SINCE="1 hour ago" tools/debug/scripts/journal_dump.sh
#
#   # Export an absolute time range and inspect the latest merged log
#   SINCE="2026-03-06 08:00:00" UNTIL="2026-03-06 10:00:00" \
#     tools/debug/scripts/journal_dump.sh
#   less tools/debug/logs/latest/all_containers.log
#
# Integration:
# - `tools/debug/scripts/podman_event_logexport.sh` calls this script
#   automatically after `die|stop|kill` events to preserve post-mortem logs.
#
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

  # Query the system journal first. If the dump is empty, retry against
  # the user journal for rootless installations.
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

# Useful merged log for quick grep/attachments without opening one file per container.
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
