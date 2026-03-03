# API/Worker Process Separation - Implementation Guide

## Overview

This guide provides step-by-step instructions to separate the API server from background worker process to enable independent scaling as background job load grows.

## Why This Separation?

**Current Constraints:**

- In-memory SSE client registry (`self._clients: dict`) prevents horizontal scaling
- APScheduler jobs run in same process as API (no multi-worker support)
- Growing background job load (metrics collection, lab sync) competes with API requests

**Benefits of Separation:**

- API process handles HTTP requests + SSE without job overhead
- Worker process handles scheduled jobs without HTTP overhead
- Can monitor and scale each independently
- Graceful degradation (API up, worker down = read-only mode)

## Implementation Steps

### Step 1: Create API Server Entry Point

**File: `src/api_server.py`**

```python
"""API server with SSE support, WITHOUT background jobs."""
import os
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# CRITICAL: Disable background jobs BEFORE importing main
os.environ['WORKER_MONITORING_ENABLED'] = 'false'

from main import create_app
from application.settings import app_settings

app = create_app()

if __name__ == "__main__":
    import uvicorn

    print("🚀 Starting Lablet Cloud Manager API Server")
    print(f"   - API: http://{app_settings.app_host}:{app_settings.app_port}/api/docs")
    print(f"   - UI: http://{app_settings.app_host}:{app_settings.app_port}/")
    print(f"   - SSE: http://{app_settings.app_host}:{app_settings.app_port}/api/events/stream")
    print(f"   - Background jobs: DISABLED")

    uvicorn.run(
        "api_server:app",
        host=app_settings.app_host,
        port=app_settings.app_port,
        reload=app_settings.debug,
        log_level="info",
        access_log=True,
    )
```

### Step 2: Create Background Worker Entry Point

**File: `src/background_worker.py`**

```python
"""Background worker process - ONLY runs scheduled jobs.

This process does NOT serve HTTP requests.
Executes: WorkerMetricsCollectionJob, LabsRefreshJob, AutoImportWorkersJob
"""
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# CRITICAL: Enable background jobs BEFORE importing main
os.environ['WORKER_MONITORING_ENABLED'] = 'true'

from application.settings import configure_logging, app_settings
from main import create_app

configure_logging(log_level=app_settings.log_level)
log = logging.getLogger(__name__)

shutdown_event = asyncio.Event()

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    log.info(f"Received signal {signum}, initiating shutdown...")
    shutdown_event.set()

async def run_worker():
    """Run background worker with graceful shutdown."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create app (this starts lifespan and schedules jobs)
    log.info("🚀 Starting background worker process...")
    app = create_app()

    # Get scheduler from service provider
    from application.services.background_scheduler import BackgroundTaskScheduler
    scheduler = app.state.services.get_required_service(BackgroundTaskScheduler)

    log.info(f"✅ Background worker started with {scheduler.get_job_count()} jobs")
    log.info("📊 Running jobs:")
    for job in scheduler.get_jobs():
        log.info(f"   - {job.name} (next run: {job.next_run_time})")

    try:
        # Wait for shutdown signal
        await shutdown_event.wait()
    except Exception as e:
        log.error(f"Worker error: {e}", exc_info=True)
    finally:
        log.info("🛑 Shutting down background worker...")
        await scheduler.stop_async()
        log.info("✅ Background worker stopped cleanly")

if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    sys.exit(0)
```

### Step 3: Update Makefile Commands

Add new commands to `Makefile`:

```makefile
##@ Development (Separated Processes)

run-api: ## Run API server only (no background jobs)
 @echo "$(BLUE)Starting API server (no background jobs)...$(NC)"
 cd src && WORKER_MONITORING_ENABLED=false python api_server.py

run-worker: ## Run background worker only (no HTTP server)
 @echo "$(BLUE)Starting background worker...$(NC)"
 cd src && WORKER_MONITORING_ENABLED=true python background_worker.py

run-split: ## Run API and worker in separate terminals (requires tmux)
 @echo "$(BLUE)Starting split mode (API + Worker)...$(NC)"
 tmux new-session -d -s cml 'cd src && make run-api'
 tmux split-window -v -t cml 'cd src && make run-worker'
 tmux attach -t cml
```

### Step 4: Update Docker Compose

**File: `docker-compose.yml`**

Add separate services:

```yaml
services:
  # API Server - handles HTTP requests and SSE
  api:
    build: .
    container_name: cml-api
    command: python /app/src/api_server.py
    ports:
      - "${APP_PORT:-8020}:8000"
    environment:
      WORKER_MONITORING_ENABLED: "false"
      MONGODB_URL: "mongodb://mongodb:27017"
      REDIS_URL: "redis://redis:6379/0"
      REDIS_ENABLED: "true"
      KEYCLOAK_URL: "http://keycloak:8080"
      # ... other env vars
    depends_on:
      - mongodb
      - redis
      - keycloak
    restart: unless-stopped
    networks:
      - cml-network

  # Background Worker - runs scheduled jobs only
  worker:
    build: .
    container_name: cml-worker
    command: python /app/src/background_worker.py
    environment:
      WORKER_MONITORING_ENABLED: "true"
      MONGODB_URL: "mongodb://mongodb:27017"
      REDIS_URL: "redis://redis:6379/0"
      REDIS_ENABLED: "true"
      # AWS credentials for EC2 operations
      AWS_ACCESS_KEY_ID: "${AWS_ACCESS_KEY_ID}"
      AWS_SECRET_ACCESS_KEY: "${AWS_SECRET_ACCESS_KEY}"
      AWS_DEFAULT_REGION: "${AWS_DEFAULT_REGION:-us-west-2}"
      # ... other env vars
    depends_on:
      - mongodb
      - redis
      - api  # Start after API
    restart: unless-stopped
    networks:
      - cml-network

  # ... existing mongodb, redis, keycloak services ...
```

### Step 5: Create Systemd Service Files

For production VM deployments:

**File: `/etc/systemd/system/cml-api.service`**

```ini
[Unit]
Description=Lablet Cloud Manager API Server
After=network.target mongodb.service redis.service
Wants=mongodb.service redis.service

[Service]
Type=exec
User=cmluser
Group=cmluser
WorkingDirectory=/opt/lablet-cloud-manager/src
Environment="PYTHONPATH=/opt/lablet-cloud-manager/src"
Environment="WORKER_MONITORING_ENABLED=false"
EnvironmentFile=/opt/lablet-cloud-manager/.env
ExecStart=/opt/lablet-cloud-manager/.venv/bin/python api_server.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/lablet-cloud-manager/logs

[Install]
WantedBy=multi-user.target
```

**File: `/etc/systemd/system/cml-worker.service`**

```ini
[Unit]
Description=Lablet Cloud Manager Background Worker
After=network.target mongodb.service redis.service cml-api.service
Wants=mongodb.service redis.service cml-api.service

[Service]
Type=exec
User=cmluser
Group=cmluser
WorkingDirectory=/opt/lablet-cloud-manager/src
Environment="PYTHONPATH=/opt/lablet-cloud-manager/src"
Environment="WORKER_MONITORING_ENABLED=true"
EnvironmentFile=/opt/lablet-cloud-manager/.env
ExecStart=/opt/lablet-cloud-manager/.venv/bin/python background_worker.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/lablet-cloud-manager/logs

[Install]
WantedBy=multi-user.target
```

**Deployment commands:**

```bash
# Install services
sudo cp cml-api.service /etc/systemd/system/
sudo cp cml-worker.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable cml-api cml-worker

# Start services
sudo systemctl start cml-api
sudo systemctl start cml-worker

# Check status
sudo systemctl status cml-api cml-worker

# View logs
sudo journalctl -u cml-api -f
sudo journalctl -u cml-worker -f
```

### Step 6: Update Dockerfile (Optional)

If you want to support both modes from same image:

```dockerfile
# ... existing build steps ...

# Create entrypoint script
COPY <<'EOF' /app/entrypoint.sh
#!/bin/bash
set -e

if [ "$WORKER_MODE" = "worker" ]; then
    echo "Starting background worker..."
    exec python /app/src/background_worker.py
else
    echo "Starting API server..."
    exec python /app/src/api_server.py
fi
EOF

RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
```

Then in docker-compose:

```yaml
api:
  environment:
    WORKER_MODE: "api"

worker:
  environment:
    WORKER_MODE: "worker"
```

## Testing the Separation

### Local Development Test

```bash
# Terminal 1: Start API
cd src && python api_server.py

# Terminal 2: Start worker
cd src && python background_worker.py

# Terminal 3: Test API
curl http://localhost:8000/api/health

# Terminal 4: Monitor logs
tail -f logs/debug.log | grep -E "API|Worker|Job"
```

### Verify Behavior

**API Server logs should show:**

- ✅ HTTP requests being handled
- ✅ SSE client connections
- ✅ "Background jobs: DISABLED" on startup
- ❌ NO job execution logs

**Worker logs should show:**

- ✅ "Background worker started with N jobs"
- ✅ Job execution logs (WorkerMetricsCollectionJob, etc.)
- ✅ CloudEvent publications
- ❌ NO HTTP request logs

### Docker Test

```bash
# Build and start
docker-compose up --build

# Verify both containers running
docker-compose ps

# Check API logs
docker-compose logs -f api

# Check worker logs
docker-compose logs -f worker

# Test API responds
curl http://localhost:8020/api/health

# Verify SSE works
curl -N http://localhost:8020/api/events/stream
```

## Monitoring and Observability

### Health Checks

Add health endpoints that report component status:

**API Health (`GET /api/health`):**

```json
{
  "status": "healthy",
  "components": {
    "mongodb": "up",
    "redis": "up",
    "sse_clients": 5,
    "background_jobs": "disabled"
  }
}
```

**Worker Health (add endpoint or log metric):**

```json
{
  "status": "healthy",
  "scheduler": "running",
  "jobs": {
    "total": 3,
    "running": 1,
    "next_run": "2025-11-21T10:30:00Z"
  }
}
```

### Prometheus Metrics (Future)

```python
# Add to api_server.py
from prometheus_client import Counter, Histogram

http_requests_total = Counter('http_requests_total', 'Total HTTP requests')
sse_clients_active = Gauge('sse_clients_active', 'Active SSE connections')

# Add to background_worker.py
job_executions_total = Counter('job_executions_total', 'Total job executions', ['job_name'])
job_duration_seconds = Histogram('job_duration_seconds', 'Job execution time', ['job_name'])
```

## Rollback Plan

If separation causes issues, revert to single process:

```bash
# Use original main.py entry point
cd src && python -m main

# Or Docker
docker-compose -f docker-compose.original.yml up
```

## Performance Expectations

**Before separation (single process):**

- API latency: p50=50ms, p99=500ms (affected by job execution)
- Background jobs: Run every 5 minutes, take 30-60s
- CPU usage: Spiky (jobs compete with requests)

**After separation:**

- API latency: p50=20ms, p99=100ms (no job interference)
- Background jobs: Consistent execution, no HTTP overhead
- CPU usage: Smooth (workloads isolated)

## Next Steps

1. ✅ Create `api_server.py` and `background_worker.py`
2. ✅ Update `docker-compose.yml`
3. ✅ Test locally with both processes
4. ✅ Monitor logs for proper separation
5. ✅ Deploy to staging environment
6. ✅ Monitor metrics for 24 hours
7. ✅ Roll out to production

## References

- See `notes/UVICORN_CONFIGURATION_GUIDE.md` for deployment strategies
- See `application/services/background_scheduler.py` for job configuration
- See `application/services/sse_event_relay.py` for SSE architecture
