# Power Manager Daemon

Runs on the host to apply performance profiles and auto-suspend unused services.

## Run

```bash
python tools/power_manager/daemon.py
```

## Config

Configuration is stored in `data/power_manager.json` and can be updated via the daemon API.

Defaults:
- Port: `9009`
- Open WebUI port: `5555`
- Idle timeout: `300s`
- Managed services: `app`, `autoscan`, `weaviate`, `neo4j`, `redis`, `monitoring`

## API

- `GET /health`
- `GET /status`
- `POST /apply-profile` `{ "profile": "saver" | "balanced" | "performance" }`
- `POST /set-config` `{ "auto_suspend_enabled": true|false, "idle_seconds": 300 }`
- `POST /suspend`
- `POST /resume`
