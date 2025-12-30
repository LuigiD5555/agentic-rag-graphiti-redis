# RAG Monitoring Container

Dedicated container for monitoring, diagnostics, and log analysis for the RAG system.

## Description

This container separates monitoring, log analysis, and diagnostic tasks from the main application container, following the separation of responsibilities principle.

## Included Components

### 1. Log Analysis (`src/utils/tools/analyze_logs.py`)
- Analyze systemd journal logs
- Detect error patterns
- Identify anomalies
- Generate JSON and text reports

### 2. Setup Verifier (`src/utils/tools/setup_verifier.py`)
- Verify system configuration
- Check required files
- Validate ports and services
- Verify dependencies

### 3. Volume Monitoring (`src/utils/volume_monitor.py`, `src/utils/volume_watcher.py`)
- Detect availability of external volumes
- Monitor reconnections
- Manage fallbacks

### 4. Monitoring Daemon (`src/monitor_daemon.py`)
- Continuous monitoring service
- Periodic health checks
- Automatic log analysis
- Report generation

### 5. Memory Monitoring (built into `src/monitor_daemon.py`)
- Continuous memory usage tracking
- Configurable warning/critical thresholds
- Supports `podman`, `cgroup`, or `system` modes (auto)

### 6. Dead Code Monitoring (vulture)
- Periodic dead-code scans for faster debugging
- Configurable targets and confidence thresholds
- Reports saved under `/app/reports`

## Usage

### Start the Container

```bash
# Start with the rest of the stack
podman-compose up -d monitoring

# View container logs
podman-compose logs -f monitoring
```

### Operation Modes

The container supports multiple modes:

#### 1. Daemon Mode (default)
Runs continuous monitoring in the background:

```bash
podman-compose exec monitoring /entrypoint.sh daemon
```

#### 2. Log Analysis
Analyze logs manually:

```bash
# Analyze last 24 hours
podman-compose exec monitoring /entrypoint.sh logs

# Analyze last week
podman-compose exec monitoring /entrypoint.sh logs --since "1 week ago"

# Analyze a specific tool
podman-compose exec monitoring /entrypoint.sh logs --tool office

# Export to JSON
podman-compose exec monitoring /entrypoint.sh logs --format json --output /app/reports/analysis.json
```

#### 3. Setup Verification
Verify system configuration:

```bash
# Full verification
podman-compose exec monitoring /entrypoint.sh verify

# JSON output
podman-compose exec monitoring /entrypoint.sh verify --json

# Quiet mode (exit code only)
podman-compose exec monitoring /entrypoint.sh verify --quiet
```

#### 4. Volume Monitoring
Monitor volume availability:

```bash
podman-compose exec monitoring /entrypoint.sh volumes
```

#### 5. Interactive Shell
Access the container:

```bash
podman-compose exec monitoring /entrypoint.sh shell
```

## Configuration

### Environment Variables

Configurable in `.env`:

```bash
# Monitoring interval (seconds)
MONITORING_INTERVAL=300

# Enable log analysis
ENABLE_LOG_ANALYSIS=true

# Enable volume monitoring
ENABLE_VOLUME_MONITORING=true

# Enable health checks
ENABLE_HEALTH_CHECKS=true

# Enable memory monitoring
ENABLE_MEMORY_MONITORING=true

# Enable dead-code monitoring (vulture)
ENABLE_VULTURE_MONITORING=false

# Vulture scan interval (seconds)
VULTURE_INTERVAL=3600

# Vulture min confidence (0-100)
VULTURE_MIN_CONFIDENCE=80

# Vulture scan targets (comma-separated)
VULTURE_TARGETS=/workspace/src

# Vulture exclude paths (comma-separated)
VULTURE_EXCLUDE=.git,.venv,venv,dist,build,__pycache__

# Memory monitor mode: auto | podman | cgroup | system
MEMORY_MONITOR_MODE=auto

# Sampling interval (seconds)
MEMORY_MONITOR_INTERVAL=10

# Alert thresholds (%)
MEMORY_WARNING_THRESHOLD=70
MEMORY_CRITICAL_THRESHOLD=85

# Target container (podman mode only)
MEMORY_MONITOR_CONTAINER=rag-graphiti-agentic_app_1

# Log level
MONITORING_LOG_LEVEL=INFO

# Dashboard port (optional)
MONITORING_DASHBOARD_PORT=8888

# Container resources
MONITORING_CPUS=0.5
MONITORING_MEMORY=512m
```

Note: `podman` mode requires `podman` to be available inside the container and access
`/run/podman/podman.sock`. In `auto` mode, if `podman` is unavailable, the daemon
falls back to `cgroup` or `system` stats.

Note: vulture scans require the workspace to be mounted read-only at `/workspace`.

### Service Endpoints

The container uses `host` network mode to access services:

- Redis: `127.0.0.1:6379`
- Weaviate: `http://127.0.0.1:8080`
- Neo4j: `bolt://127.0.0.1:7687`
- LM Studio: `http://127.0.0.1:1234`

## Reports

Reports are stored on persistent volumes:

```
/app/logs/          # Monitoring daemon logs
/app/reports/       # JSON analysis reports
/app/data/          # Persistent data
```

Access from the host:

```bash
# View generated reports
ls -la ./monitoring_reports/

# View latest health report
cat ./monitoring_reports/health_*.json | jq .

# View latest log report
cat ./monitoring_reports/logs_*.json | jq .
```

## Health Checks

The daemon runs periodic health checks:

### Redis
- Connectivity
- Memory usage
- Connected clients
- Total keys

### Weaviate
- Connectivity
- Version
- Number of collections

### Neo4j
- Connectivity
- Node count

## Project Structure

```
tools/monitoring/
├── Dockerfile              # Container image
├── requirements.txt        # Python dependencies
├── entrypoint.sh          # Entry script
├── README.md              # This documentation
├── config/                # Configurations
├── src/
│   ├── __init__.py
│   └── monitor_daemon.py  # Main daemon
```

The container copies shared utilities from `src/utils` (includes `volume_monitor.py`,
`volume_watcher.py`, and `src/utils/tools/*`).

## Development

### Adding New Checks

1. Edit `monitor_daemon.py` to add new checks
2. Update this README with the new feature
3. Rebuild the monitoring image

### Logs and Debugging

```bash
# View daemon logs
podman-compose logs -f monitoring

# View historical logs
journalctl --user -u rag-monitoring.service
```

### Dashboard Setup (Optional)

1. Uncomment the ports section in `podman-compose.yml`
2. Make sure the container uses `network_mode: "host"` and services are running:
   - Redis on 6379
   - Weaviate on 8080
   - Neo4j on 7687
