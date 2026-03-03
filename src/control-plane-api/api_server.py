"""API server with SSE support, WITHOUT background jobs."""

import os
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# CRITICAL: Disable background jobs BEFORE importing main
os.environ["WORKER_MONITORING_ENABLED"] = "false"

from application.settings import app_settings  # noqa: E402
from main import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    import uvicorn

    print("🚀 Starting Lablet Cloud Manager API Server")
    print(f"   - API: http://{app_settings.app_host}:{app_settings.app_port}/api/docs")
    print(f"   - UI: http://{app_settings.app_host}:{app_settings.app_port}/")
    print(f"   - SSE: http://{app_settings.app_host}:{app_settings.app_port}/api/events/stream")
    print("   - Background jobs: DISABLED")

    uvicorn.run(
        "api_server:app",
        host=app_settings.app_host,
        port=app_settings.app_port,
        reload=app_settings.debug,
        log_level="info",
        access_log=True,
    )
