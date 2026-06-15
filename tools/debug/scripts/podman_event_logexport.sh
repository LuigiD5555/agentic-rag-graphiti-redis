#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-rag-graphiti-agentic}"
ENABLE_LOG_EXPORT="${ENABLE_LOG_EXPORT:-1}"

DEBOUNCE_SECONDS="${DEBOUNCE_SECONDS:-3}"
DEFAULT_SINCE="${DEFAULT_SINCE:-24 hours ago}"

if [[ "$ENABLE_LOG_EXPORT" == "0" ]]; then
  exit 0
fi

if ! command -v podman >/dev/null 2>&1; then
  echo "ERROR: 'podman' is not installed or not in PATH." >&2
  exit 1
fi

STATE_DIR="$ROOT_DIR/logs/.state"
mkdir -p "$STATE_DIR"

LAST_DUMP_FILE="$STATE_DIR/last_dump_epoch"
LAST_EVENT_FILE="$STATE_DIR/last_event_epoch"

now_epoch() { date +%s; }

read_epoch_or_empty() {
  local file="$1"
  if [[ -f "$file" ]]; then
    tr -d ' \t\r\n' <"$file" || true
  fi
}

since_arg_from_last_dump() {
  local last_dump
  last_dump="$(read_epoch_or_empty "$LAST_DUMP_FILE")"
  if [[ -n "${last_dump:-}" && "$last_dump" =~ ^[0-9]+$ ]]; then
    echo "@$last_dump"
    return 0
  fi

  local earliest=""
  while IFS= read -r cname; do
    [[ -z "${cname:-}" ]] && continue
    local started_at
    started_at="$(podman inspect -f '{{.State.StartedAt}}' "$cname" 2>/dev/null || true)"
    [[ -z "${started_at:-}" || "$started_at" == "<no value>" ]] && continue
    if [[ -z "$earliest" || "$started_at" < "$earliest" ]]; then
      earliest="$started_at"
    fi
  done < <(podman ps -a --filter "label=io.podman.compose.project=$PROJECT_NAME" --format '{{.Names}}' 2>/dev/null || true)

  if [[ -n "$earliest" ]]; then
    echo "$earliest"
  else
    echo "$DEFAULT_SINCE"
  fi
}

set_last_dump_now() {
  now_epoch >"$LAST_DUMP_FILE"
}

trigger_dump_worker() {
  local worker_pid_file="$STATE_DIR/worker.pid"
  local existing
  existing="$(read_epoch_or_empty "$worker_pid_file")"
  if [[ -n "${existing:-}" && "$existing" =~ ^[0-9]+$ ]] && kill -0 "$existing" >/dev/null 2>&1; then
    return 0
  fi

  (
    echo "$$" >"$worker_pid_file"
    while :; do
      local last_event
      last_event="$(read_epoch_or_empty "$LAST_EVENT_FILE")"
      if [[ -z "${last_event:-}" || ! "$last_event" =~ ^[0-9]+$ ]]; then
        sleep 1
        continue
      fi
      local elapsed
      elapsed="$(( $(now_epoch) - last_event ))"
      if (( elapsed >= DEBOUNCE_SECONDS )); then
        break
      fi
      sleep 1
    done

    local since until
    since="$(since_arg_from_last_dump)"
    until="now"

    SINCE="$since" UNTIL="$until" COMPOSE_PROJECT_NAME="$PROJECT_NAME" "$ROOT_DIR/scripts/journal_dump.sh" >/dev/null 2>&1 || true
    set_last_dump_now
    rm -f "$worker_pid_file" >/dev/null 2>&1 || true
  ) &
}

echo "Watching podman events for project: $PROJECT_NAME" >&2

podman events \
  --filter type=container \
  --filter "label=io.podman.compose.project=$PROJECT_NAME" \
  --format '{{.Status}}\t{{.Name}}' \
  --stream \
  | while IFS=$'\t' read -r status name; do
      case "$status" in
        die|stop|kill)
          now_epoch >"$LAST_EVENT_FILE"
          trigger_dump_worker
          ;;
      esac
    done
