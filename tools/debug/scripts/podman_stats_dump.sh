#!/usr/bin/env bash
set -euo pipefail

# Dump podman stats for all containers over a time window.
# Usage: ./podman_stats_dump.sh [duration_seconds] [interval_seconds] [output_file]
# Example: ./podman_stats_dump.sh 300 5 ./podman_stats_5min.tsv

duration="${1:-300}"
interval="${2:-5}"
out_file="${3:-podman_stats_$(date '+%Y%m%d_%H%M%S').tsv}"

if ! command -v podman >/dev/null 2>&1; then
  echo "ERROR: podman is not available in PATH"
  exit 1
fi

echo -e "timestamp\tname\tcpu_percent\tmem_usage" > "$out_file"

end_time=$((SECONDS + duration))
while [ "$SECONDS" -lt "$end_time" ]; do
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  podman stats --no-stream --format "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" \
    | sed "s/^/${ts}\t/" >> "$out_file"
  sleep "$interval"
done

echo "Saved stats to: $out_file"
