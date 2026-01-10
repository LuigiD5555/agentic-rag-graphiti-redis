"""Start script that runs both API and auto-scan scheduler."""
import os
import sys
import multiprocessing
from src.ingestion.auto_scan.scheduler import main as autoscan_main
import src.settings as settings


def start_api():
    """Start the API server."""
    import uvicorn

    port = int(os.getenv("API_PORT", "8001"))
    uvicorn.run(
        "src.api.app:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )


def start_autoscan():
    """Start the auto-scan scheduler."""
    autoscan_main()


if __name__ == "__main__":
    # Check if auto-scan is enabled
    auto_scan_enabled = settings.AUTO_SCAN_ENABLED

    if auto_scan_enabled:
        print("Starting auto-scan scheduler in background process...")
        scan_process = multiprocessing.Process(target=start_autoscan)
        scan_process.start()
        print(f"Auto-scan scheduler started with PID: {scan_process.pid}")

    # Start API server in foreground
    print("Starting API server...")
    start_api()
