#!/usr/bin/env python3
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
CONFIG_PATH = DATA_DIR / "power_manager.json"


DEFAULT_CONFIG = {
    "auto_suspend_enabled": True,
    "idle_seconds": 300,
    "action_cooldown_seconds": 30,
    "open_webui_port": 5555,
    "compose_file": "podman-compose.yml",
    "managed_services": ["app", "autoscan", "weaviate", "neo4j", "monitoring"],
    "poll_interval_seconds": 10,
}


PROFILE_SETTINGS = {
    "saver": {
        "WEAVIATE_CPUS": "0.5",
        "WEAVIATE_MEMORY": "1g",
        "NEO4J_CPUS": "0.4",
        "NEO4J_MEMORY": "1g",
        "APP_CPUS": "0.3",
        "APP_MEMORY": "400m",
        "API_CPUS": "0.1",
        "API_MEMORY": "200m",
        "OPEN_WEBUI_CPUS": "0.2",
        "OPEN_WEBUI_MEMORY": "500m",
        "AUTO_SCAN_CPUS": "0.1",
        "AUTO_SCAN_MEMORY": "256m",
        "MONITORING_CPUS": "0.05",
        "MONITORING_MEMORY": "128m",
        "AUTO_SCAN_INTERVAL": "1800",
        "AUTO_SCAN_MAX_FILES": "15",
        "AUTO_SCAN_INITIAL": "false",
        "RAG_EMBED_BATCH_SIZE": "8",
        "RAG_PARALLEL_WORKERS": "1",
        "RAG_PIPELINE_WORKERS": "1",
    },
    "balanced": {
        "WEAVIATE_CPUS": "0.5",
        "WEAVIATE_MEMORY": "1g",
        "NEO4J_CPUS": "0.4",
        "NEO4J_MEMORY": "1g",
        "APP_CPUS": "0.3",
        "APP_MEMORY": "400m",
        "API_CPUS": "0.1",
        "API_MEMORY": "200m",
        "OPEN_WEBUI_CPUS": "0.2",
        "OPEN_WEBUI_MEMORY": "500m",
        "AUTO_SCAN_CPUS": "0.15",
        "AUTO_SCAN_MEMORY": "384m",
        "MONITORING_CPUS": "0.05",
        "MONITORING_MEMORY": "128m",
        "AUTO_SCAN_INTERVAL": "1200",
        "AUTO_SCAN_MAX_FILES": "25",
        "AUTO_SCAN_INITIAL": "false",
        "RAG_EMBED_BATCH_SIZE": "12",
        "RAG_PARALLEL_WORKERS": "1",
        "RAG_PIPELINE_WORKERS": "2",
    },
    "performance": {
        "WEAVIATE_CPUS": "0.5",
        "WEAVIATE_MEMORY": "1g",
        "NEO4J_CPUS": "0.4",
        "NEO4J_MEMORY": "1g",
        "APP_CPUS": "0.3",
        "APP_MEMORY": "400m",
        "API_CPUS": "0.1",
        "API_MEMORY": "200m",
        "OPEN_WEBUI_CPUS": "0.2",
        "OPEN_WEBUI_MEMORY": "500m",
        "AUTO_SCAN_CPUS": "0.25",
        "AUTO_SCAN_MEMORY": "512m",
        "MONITORING_CPUS": "0.05",
        "MONITORING_MEMORY": "128m",
        "AUTO_SCAN_INTERVAL": "900",
        "AUTO_SCAN_MAX_FILES": "50",
        "AUTO_SCAN_INITIAL": "false",
        "RAG_EMBED_BATCH_SIZE": "16",
        "RAG_PARALLEL_WORKERS": "2",
        "RAG_PIPELINE_WORKERS": "2",
    },
}


def _load_config() -> dict:
    """Load power manager configuration from JSON file.
    
    Loads configuration from data/power_manager.json if it exists, otherwise
    returns default configuration. Merges existing config with defaults.
    
    Returns:
        dict: Configuration dictionary with defaults for missing values.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**DEFAULT_CONFIG, **data}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def _save_config(config: dict) -> None:
    """Save power manager configuration to JSON file.
    
    Saves configuration to data/power_manager.json. Creates directory if needed.
    
    Args:
        config: Configuration dictionary to save.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _env_path() -> Path:
    """Get path to .env file in repository root.
    
    Returns:
        Path: Absolute path to .env file.
    """
    return REPO_ROOT / ".env"


def _update_env(updates: dict) -> None:
    """Update .env file with new key-value pairs.
    
    Updates existing keys and adds new ones. Preserves comments and formatting.
    
    Args:
        updates: Dictionary of key-value pairs to update in .env file.
    """
    env_path = _env_path()
    lines = []
    existing = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                lines.append(line)
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            existing[key] = value
            lines.append(line)
    merged = {**existing, **updates}

    out_lines = []
    seen = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out_lines.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in merged:
            out_lines.append(f"{key}={merged[key]}")
            seen.add(key)
        else:
            out_lines.append(line)
    for key, value in merged.items():
        if key not in seen:
            out_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def _run_compose(args: list[str]) -> subprocess.CompletedProcess:
    """Run podman-compose command with configured compose file.
    
    Args:
        args: List of arguments to pass to podman-compose.
        
    Returns:
        CompletedProcess: Result of the subprocess run.
    """
    config = _load_config()
    cmd = ["podman-compose", "-f", str(REPO_ROOT / config["compose_file"])] + args
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def _stop_services(services: list[str]) -> dict:
    """Stop specified services using podman-compose.
    
    Args:
        services: List of service names to stop.
        
    Returns:
        dict: Result dictionary with 'ok' boolean and stdout/stderr.
    """
    result = _run_compose(["stop"] + services)
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


def _start_services(services: list[str]) -> dict:
    """Start specified services using podman-compose in detached mode.
    
    Args:
        services: List of service names to start.
        
    Returns:
        dict: Result dictionary with 'ok' boolean and stdout/stderr.
    """
    result = _run_compose(["up", "-d"] + services)
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


def _recreate_services(services: list[str]) -> dict:
    """Recreate specified services using podman-compose.
    
    Forces recreation of containers with updated environment variables.
    
    Args:
        services: List of service names to recreate.
        
    Returns:
        dict: Result dictionary with 'ok' boolean and stdout/stderr.
    """
    result = _run_compose(["up", "-d", "--force-recreate"] + services)
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


def _get_active_connections(port: int) -> int:
    """Get number of active TCP connections on specified port.
    
    Uses 'ss' command to count established connections on the given port.
    
    Args:
        port: Port number to check for active connections.
        
    Returns:
        int: Number of active connections, 0 if command fails.
    """
    cmd = f"ss -Htn state established '( sport = :{port} )'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        return 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return len(lines)


class PowerState:
    """Thread-safe state manager for power management operations.
    
    Tracks configuration, activity timestamps, and service states with
    proper locking for concurrent access.
    """
    
    def __init__(self) -> None:
        """Initialize power state with current configuration."""
        self.config = _load_config()
        self.last_active = time.time()
        self.last_action = 0.0
        self.services_stopped = False
        self.lock = threading.Lock()

    def refresh_config(self) -> None:
        """Reload configuration from disk (thread-safe)."""
        with self.lock:
            self.config = _load_config()

    def set_config(self, updates: dict) -> None:
        """Update configuration and save to disk (thread-safe).
        
        Args:
            updates: Dictionary of configuration updates to apply.
        """
        with self.lock:
            self.config.update(updates)
            _save_config(self.config)

    def record_activity(self) -> None:
        """Record current time as last activity (thread-safe)."""
        with self.lock:
            self.last_active = time.time()

    def should_suspend(self) -> bool:
        """Check if services should be suspended due to inactivity.
        
        Returns:
            bool: True if auto-suspend is enabled and idle time exceeds threshold.
        """
        with self.lock:
            if not self.config.get("auto_suspend_enabled", True):
                return False
            idle_seconds = int(self.config.get("idle_seconds", 300))
            return (time.time() - self.last_active) >= idle_seconds

    def set_services_stopped(self, stopped: bool) -> None:
        """Set whether services are currently stopped (thread-safe).
        
        Args:
            stopped: True if services are stopped, False if running.
        """
        with self.lock:
            self.services_stopped = stopped

    def get_services_stopped(self) -> bool:
        """Get whether services are currently stopped (thread-safe).
        
        Returns:
            bool: True if services are stopped, False if running.
        """
        with self.lock:
            return self.services_stopped

    def can_run_action(self) -> bool:
        """Check if an action can be run (respects cooldown).
        
        Returns:
            bool: True if enough time has passed since last action.
        """
        with self.lock:
            cooldown = int(self.config.get("action_cooldown_seconds", 30))
            return (time.time() - self.last_action) >= cooldown

    def mark_action(self) -> None:
        """Record that an action was just performed (thread-safe)."""
        with self.lock:
            self.last_action = time.time()


STATE = PowerState()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def _json_response(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        data = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json_response(200, {"ok": True})
            return
        if self.path == "/status":
            cfg = _load_config()
            self._json_response(
                200,
                {
                    "auto_suspend_enabled": cfg.get("auto_suspend_enabled", True),
                    "idle_seconds": cfg.get("idle_seconds", 300),
                    "services_stopped": STATE.get_services_stopped(),
                },
            )
            return
        self._json_response(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path == "/apply-profile":
            if not STATE.can_run_action():
                self._json_response(429, {"error": "cooldown_active"})
                return
            payload = self._read_json()
            profile = payload.get("profile")
            if profile not in PROFILE_SETTINGS:
                self._json_response(400, {"error": "invalid_profile"})
                return
            _update_env(PROFILE_SETTINGS[profile])
            config = _load_config()
            services = config.get("managed_services", [])
            result = _recreate_services(services)
            if result["ok"]:
                STATE.set_services_stopped(False)
                STATE.mark_action()
            self._json_response(200, {"ok": result["ok"], "result": result})
            return
        if self.path == "/set-config":
            if not STATE.can_run_action():
                self._json_response(429, {"error": "cooldown_active"})
                return
            payload = self._read_json()
            updates = {}
            if "auto_suspend_enabled" in payload:
                updates["auto_suspend_enabled"] = bool(payload["auto_suspend_enabled"])
            if "idle_seconds" in payload:
                updates["idle_seconds"] = int(payload["idle_seconds"])
            if updates:
                STATE.set_config(updates)
                STATE.mark_action()
            self._json_response(200, {"ok": True})
            return
        if self.path == "/suspend":
            if not STATE.can_run_action():
                self._json_response(429, {"error": "cooldown_active"})
                return
            config = _load_config()
            services = config.get("managed_services", [])
            result = _stop_services(services)
            if result["ok"]:
                STATE.set_services_stopped(True)
                STATE.mark_action()
            self._json_response(200, {"ok": result["ok"], "result": result})
            return
        if self.path == "/resume":
            if not STATE.can_run_action():
                self._json_response(429, {"error": "cooldown_active"})
                return
            config = _load_config()
            services = config.get("managed_services", [])
            result = _start_services(services)
            if result["ok"]:
                STATE.set_services_stopped(False)
                STATE.mark_action()
            self._json_response(200, {"ok": result["ok"], "result": result})
            return
        self._json_response(404, {"error": "not_found"})


def _monitor_loop() -> None:
    """Background monitoring loop for power management.
    
    Continuously checks for active connections and manages service
    suspension/resumption based on activity and configuration.
    """
    while True:
        cfg = _load_config()
        STATE.refresh_config()
        port = int(cfg.get("open_webui_port", 5555))
        active = _get_active_connections(port)
        if active > 0:
            STATE.record_activity()
            if STATE.get_services_stopped():
                _start_services(cfg.get("managed_services", []))
                STATE.set_services_stopped(False)
        else:
            if STATE.should_suspend() and not STATE.get_services_stopped():
                _stop_services(cfg.get("managed_services", []))
                STATE.set_services_stopped(True)
        time.sleep(int(cfg.get("poll_interval_seconds", 10)))


def main() -> None:
    """Main entry point for power manager daemon.
    
    Starts background monitoring thread and HTTP server for API control.
    """
    STATE.refresh_config()
    monitor_thread = threading.Thread(target=_monitor_loop, daemon=True)
    monitor_thread.start()

    port = int(os.environ.get("POWER_DAEMON_PORT", "9009"))
    server = ThreadedHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
