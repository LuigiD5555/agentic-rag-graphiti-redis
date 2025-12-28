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

        logger.info("Monitoring daemon initialized")
        logger.info(f"Check interval: {self.check_interval}s")
        logger.info(f"Log analysis: {self.enable_log_analysis}")
        logger.info(f"Volume monitoring: {self.enable_volume_monitoring}")
        logger.info(f"Health checks: {self.enable_health_checks}")

    def check_redis_health(self) -> Dict[str, Any]:
        """Check Redis connectivity and stats."""
        try:
            import redis

            redis_host = os.environ.get("REDIS_HOST", "127.0.0.1")
            redis_port = int(os.environ.get("REDIS_PORT", 6379))

            client = redis.Redis(
                host=redis_host,
                port=redis_port,
                socket_connect_timeout=5,
                socket_timeout=5
            )

            # Ping test
            client.ping()

            # Get info
            info = client.info()
            memory_used = info.get("used_memory_human", "unknown")
            connected_clients = info.get("connected_clients", 0)
            total_keys = client.dbsize()

            return {
                "status": "healthy",
                "memory_used": memory_used,
                "connected_clients": connected_clients,
                "total_keys": total_keys
            }

        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e)
            }

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
            results["services"]["redis"] = self.check_redis_health()
            results["services"]["weaviate"] = self.check_weaviate_health()
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

    def run_monitoring_cycle(self):
        """Run one complete monitoring cycle."""
        logger.info("=" * 70)
        logger.info("Starting monitoring cycle")
        logger.info("=" * 70)

        try:
            self.run_health_checks()
            self.run_log_analysis()
            self.run_volume_checks()

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
