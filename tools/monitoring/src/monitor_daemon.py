#!/usr/bin/env python3
"""
Monitoring Daemon - Continuous monitoring service

Runs periodic checks:
- Log analysis
- System health
- Volume availability
- Service connectivity
"""

import os
import sys
import time
import logging
import signal
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/app/logs/monitor.log")
    ]
)

logger = logging.getLogger(__name__)


class MonitoringDaemon:
    """Main monitoring daemon orchestrator."""

    def __init__(self):
        """Initialize the monitoring daemon."""
        self.running = False
        self.check_interval = int(os.environ.get("MONITORING_INTERVAL", "300"))  # 5 minutes default
        self.enable_log_analysis = os.environ.get("ENABLE_LOG_ANALYSIS", "true").lower() == "true"
        self.enable_volume_monitoring = os.environ.get("ENABLE_VOLUME_MONITORING", "true").lower() == "true"
        self.enable_health_checks = os.environ.get("ENABLE_HEALTH_CHECKS", "true").lower() == "true"
        self.enable_memory_monitoring = os.environ.get("ENABLE_MEMORY_MONITORING", "true").lower() == "true"
        self.enable_vulture_monitoring = os.environ.get("ENABLE_VULTURE_MONITORING", "false").lower() == "true"
        self.enable_neo4j = os.environ.get("ENABLE_NEO4J", "false").lower() == "true"
        self.memory_monitor_mode = os.environ.get("MEMORY_MONITOR_MODE", "auto").lower()
        self.memory_monitor_interval = int(os.environ.get("MEMORY_MONITOR_INTERVAL", "10"))
        self.memory_warning_threshold = float(os.environ.get("MEMORY_WARNING_THRESHOLD", "70"))
        self.memory_critical_threshold = float(os.environ.get("MEMORY_CRITICAL_THRESHOLD", "85"))
        self.memory_container_name = (
            os.environ.get("MEMORY_MONITOR_CONTAINER") or self._default_app_container_name()
        )
        self.vulture_interval = int(os.environ.get("VULTURE_INTERVAL", "3600"))
        self.vulture_min_confidence = int(os.environ.get("VULTURE_MIN_CONFIDENCE", "80"))
        self.vulture_targets = self._split_env_list(
            os.environ.get("VULTURE_TARGETS", "/workspace/src")
        )
        self.vulture_exclude = self._split_env_list(
            os.environ.get("VULTURE_EXCLUDE", ".git,.venv,venv,dist,build,__pycache__")
        )
        self._last_vulture_run = 0.0
        self._memory_thread = None
        self._memory_warned_no_source = False

        logger.info("Monitoring daemon initialized")
        logger.info(f"Check interval: {self.check_interval}s")
        logger.info(f"Log analysis: {self.enable_log_analysis}")
        logger.info(f"Volume monitoring: {self.enable_volume_monitoring}")
        logger.info(f"Health checks: {self.enable_health_checks}")
        logger.info(f"Memory monitoring: {self.enable_memory_monitoring}")
        logger.info(f"Vulture monitoring: {self.enable_vulture_monitoring}")
        logger.info(f"Neo4j monitoring: {self.enable_neo4j}")
        if self.enable_memory_monitoring:
            logger.info(
                "Memory monitor: mode=%s interval=%ss warning=%s%% critical=%s%% target=%s",
                self.memory_monitor_mode,
                self.memory_monitor_interval,
                self.memory_warning_threshold,
                self.memory_critical_threshold,
                self.memory_container_name,
            )
        if self.enable_vulture_monitoring:
            logger.info(
                "Vulture: interval=%ss min_confidence=%s targets=%s exclude=%s",
                self.vulture_interval,
                self.vulture_min_confidence,
                ",".join(self.vulture_targets),
                ",".join(self.vulture_exclude),
            )

    def _default_app_container_name(self) -> str:
        project_name = os.environ.get("COMPOSE_PROJECT_NAME", "rag-graphiti-agentic")
        return f"{project_name}_app_1"

    def _split_env_list(self, value: str) -> list[str]:
        items = [item.strip() for item in value.split(",")]
        return [item for item in items if item]

    def _format_bytes(self, value: int) -> str:
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f}{unit}"
            size /= 1024

    def _get_podman_memory_stats(self) -> Dict[str, Any] | None:
        if not shutil.which("podman"):
            return None

        try:
            result = subprocess.run(
                [
                    "podman",
                    "stats",
                    self.memory_container_name,
                    "--no-stream",
                    "--format",
                    "{{.MemUsage}}\t{{.MemPerc}}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                logger.debug("podman stats failed: %s", result.stderr.strip())
                return None

            lines = result.stdout.strip().splitlines()
            if not lines:
                return None

            parts = lines[-1].split("\t")
            if len(parts) < 2:
                return None

            usage = parts[0].strip()
            percent_raw = parts[1].strip().rstrip("%")
            percent = float(percent_raw) if percent_raw else None
            if percent is None:
                return None

            return {"source": "podman", "usage": usage, "percent": percent}
        except Exception as exc:
            logger.debug("podman stats error: %s", exc)
            return None

    def _get_cgroup_memory_stats(self) -> Dict[str, Any] | None:
        current_path = Path("/sys/fs/cgroup/memory.current")
        max_path = Path("/sys/fs/cgroup/memory.max")
        if not current_path.exists() or not max_path.exists():
            return None

        try:
            current = int(current_path.read_text().strip())
            max_raw = max_path.read_text().strip()
            if max_raw == "max":
                return None
            max_bytes = int(max_raw)
            if max_bytes <= 0:
                return None
            percent = (current / max_bytes) * 100
            usage = f"{self._format_bytes(current)} / {self._format_bytes(max_bytes)}"
            return {"source": "cgroup", "usage": usage, "percent": percent}
        except Exception as exc:
            logger.debug("cgroup memory error: %s", exc)
            return None

    def _get_system_memory_stats(self) -> Dict[str, Any] | None:
        meminfo_path = Path("/proc/meminfo")
        if not meminfo_path.exists():
            return None

        try:
            meminfo = {}
            for line in meminfo_path.read_text().splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                parts = value.strip().split()
                if not parts:
                    continue
                meminfo[key] = int(parts[0])  # kB

            total_kb = meminfo.get("MemTotal")
            available_kb = meminfo.get("MemAvailable")
            if available_kb is None:
                available_kb = (
                    meminfo.get("MemFree", 0)
                    + meminfo.get("Buffers", 0)
                    + meminfo.get("Cached", 0)
                )

            if not total_kb or not available_kb:
                return None

            used_kb = total_kb - available_kb
            percent = (used_kb / total_kb) * 100
            usage = f"{self._format_bytes(used_kb * 1024)} / {self._format_bytes(total_kb * 1024)}"
            return {"source": "system", "usage": usage, "percent": percent}
        except Exception as exc:
            logger.debug("system memory error: %s", exc)
            return None

    def _get_memory_stats(self) -> Dict[str, Any] | None:
        mode = self.memory_monitor_mode
        if mode not in ("auto", "podman", "cgroup", "system"):
            logger.warning("Unknown MEMORY_MONITOR_MODE=%s (using auto)", mode)
            mode = "auto"

        if mode in ("auto", "podman"):
            stats = self._get_podman_memory_stats()
            if stats or mode == "podman":
                return stats

        if mode in ("auto", "cgroup"):
            stats = self._get_cgroup_memory_stats()
            if stats or mode == "cgroup":
                return stats

        return self._get_system_memory_stats()

    def _memory_monitor_loop(self):
        logger.info("Memory monitor started")
        while self.running:
            stats = self._get_memory_stats()
            if not stats:
                if not self._memory_warned_no_source:
                    logger.warning("Memory monitor disabled: no usable stats source found")
                    self._memory_warned_no_source = True
                time.sleep(self.memory_monitor_interval)
                continue

            percent = stats["percent"]
            usage = stats["usage"]
            source = stats["source"]
            if percent >= self.memory_critical_threshold:
                logger.error(
                    "Memory critical (%s): %s (%.1f%%)",
                    source,
                    usage,
                    percent,
                )
            elif percent >= self.memory_warning_threshold:
                logger.warning(
                    "Memory high (%s): %s (%.1f%%)",
                    source,
                    usage,
                    percent,
                )
            else:
                logger.debug(
                    "Memory OK (%s): %s (%.1f%%)",
                    source,
                    usage,
                    percent,
                )

            time.sleep(self.memory_monitor_interval)

    def check_weaviate_health(self) -> Dict[str, Any]:
        """Check Weaviate connectivity and stats."""
        try:
            import requests

            weaviate_url = os.environ.get("WEAVIATE_URL", "http://127.0.0.1:8080")

            # Meta endpoint
            response = requests.get(f"{weaviate_url}/v1/meta", timeout=10)
            response.raise_for_status()

            meta = response.json()
            version = meta.get("version", "unknown")

            # Schema check
            schema_response = requests.get(f"{weaviate_url}/v1/schema", timeout=10)
            schema_response.raise_for_status()
            schema = schema_response.json()

            classes = len(schema.get("classes", []))

            return {
                "status": "healthy",
                "version": version,
                "classes": classes
            }

        except Exception as e:
            logger.error(f"Weaviate health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e)
            }

    def check_neo4j_health(self) -> Dict[str, Any]:
        """Check Neo4j connectivity."""
        try:
            from neo4j import GraphDatabase

            neo4j_uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
            neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
            neo4j_password = os.environ.get("NEO4J_PASSWORD", "neo4j123")

            driver = GraphDatabase.driver(
                neo4j_uri,
                auth=(neo4j_user, neo4j_password)
            )

            # Verify connectivity
            driver.verify_connectivity()

            # Get node count
            with driver.session() as session:
                result = session.run("MATCH (n) RETURN count(n) as count")
                node_count = result.single()["count"]

            driver.close()

            return {
                "status": "healthy",
                "node_count": node_count
            }

        except Exception as e:
            logger.error(f"Neo4j health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e)
            }

    def run_health_checks(self):
        """Run all health checks."""
        logger.info("Running health checks...")

        results = {
            "timestamp": datetime.now().isoformat(),
            "services": {}
        }

        if self.enable_health_checks:
            results["services"]["weaviate"] = self.check_weaviate_health()

            # Only check Neo4j if explicitly enabled
            if self.enable_neo4j:
                results["services"]["neo4j"] = self.check_neo4j_health()

        # Log results
        for service, status in results["services"].items():
            if status.get("status") == "healthy":
                logger.info(f"✓ {service}: healthy")
            else:
                logger.warning(f"✗ {service}: {status.get('error', 'unhealthy')}")

        # Save to file
        report_dir = Path("/app/reports")
        report_dir.mkdir(parents=True, exist_ok=True)

        report_file = report_dir / f"health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        import json
        with open(report_file, "w") as f:
            json.dump(results, f, indent=2)

        logger.info(f"Health report saved to {report_file}")

    def run_log_analysis(self):
        """Run log analysis."""
        if not self.enable_log_analysis:
            return

        logger.info("Running log analysis...")

        try:
            # Import from local tools module
            sys.path.insert(0, "/app/src")
            from utils.tools.analyze_logs import LogAnalyzer

            analyzer = LogAnalyzer(since="1 hour ago")
            results = analyzer.analyze_all()

            # Check for anomalies
            for tool, data in results.items():
                if data.get("anomalies"):
                    logger.warning(f"Anomalies detected in {tool}: {data['anomalies']}")

            # Save report
            report_dir = Path("/app/reports")
            report_dir.mkdir(parents=True, exist_ok=True)

            analyzer.export_json(
                results,
                report_dir / f"logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )

        except Exception as e:
            logger.error(f"Log analysis failed: {e}", exc_info=True)

    def run_volume_checks(self):
        """Run volume availability checks."""
        if not self.enable_volume_monitoring:
            return

        logger.info("Checking volumes...")

        try:
            from utils.volume_monitor import get_monitor

            monitor = get_monitor()
            statuses = monitor.get_all_statuses()

            for name, status in statuses.items():
                if status.is_fallback:
                    logger.warning(f"Volume '{name}' using fallback: {status.path}")
                else:
                    logger.info(f"Volume '{name}' available: {status.path}")

        except Exception as e:
            logger.error(f"Volume check failed: {e}", exc_info=True)

    def run_vulture_scan(self):
        """Run dead-code detection with vulture."""
        if not self.enable_vulture_monitoring:
            return

        now = time.time()
        if now - self._last_vulture_run < self.vulture_interval:
            return

        self._last_vulture_run = now

        if not shutil.which("vulture"):
            logger.warning("Vulture monitoring enabled but vulture is not installed")
            return

        report_dir = Path("/app/reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / f"vulture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        cmd = ["vulture", *self.vulture_targets, "--min-confidence", str(self.vulture_min_confidence)]
        if self.vulture_exclude:
            cmd.extend(["--exclude", ",".join(self.vulture_exclude)])

        logger.info("Running vulture scan...")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=900,
            )
            output = result.stdout.strip()
            errors = result.stderr.strip()

            with report_file.open("w") as f:
                f.write("Command:\n")
                f.write(" ".join(cmd) + "\n\n")
                f.write("Exit code:\n")
                f.write(str(result.returncode) + "\n\n")
                if output:
                    f.write("Output:\n")
                    f.write(output + "\n")
                if errors:
                    f.write("\nErrors:\n")
                    f.write(errors + "\n")

            if result.returncode == 0:
                if output:
                    logger.warning("Vulture findings detected (see report)")
                else:
                    logger.info("Vulture scan completed with no findings")
            elif result.returncode == 3:
                logger.warning("Vulture scan detected dead code (see report)")
            else:
                logger.warning("Vulture scan finished with errors (see report)")

        except subprocess.TimeoutExpired:
            logger.warning("Vulture scan timed out")
        except Exception as e:
            logger.error(f"Vulture scan failed: {e}", exc_info=True)

    def run_monitoring_cycle(self):
        """Run one complete monitoring cycle."""
        logger.info("=" * 70)
        logger.info("Starting monitoring cycle")
        logger.info("=" * 70)

        try:
            self.run_health_checks()
            self.run_log_analysis()
            self.run_volume_checks()
            self.run_vulture_scan()

            logger.info("Monitoring cycle completed successfully")

        except Exception as e:
            logger.error(f"Monitoring cycle failed: {e}", exc_info=True)

        logger.info("=" * 70)

    def start(self):
        """Start the monitoring daemon."""
        logger.info("Starting monitoring daemon...")
        self.running = True

        # Set up signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        if self.enable_memory_monitoring:
            self._memory_thread = threading.Thread(
                target=self._memory_monitor_loop,
                name="memory-monitor",
                daemon=True,
            )
            self._memory_thread.start()

        # Run initial check
        self.run_monitoring_cycle()

        # Main loop
        while self.running:
            try:
                time.sleep(self.check_interval)
                self.run_monitoring_cycle()

            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
                break

            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(60)  # Wait before retrying

        logger.info("Monitoring daemon stopped")
        if self._memory_thread:
            self._memory_thread.join(timeout=2)

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False


def main():
    """Entry point for monitoring daemon."""
    logger.info("Monitoring Daemon starting up")

    daemon = MonitoringDaemon()

    try:
        daemon.start()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
