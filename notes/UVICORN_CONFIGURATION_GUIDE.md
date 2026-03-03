# Uvicorn Configuration Guide for Background Jobs + Web API

## Overview

This application combines **recurrent background jobs** (APScheduler) with a **live web API** (FastAPI) and **Server-Sent Events (SSE)** for real-time updates. This creates special constraints for Uvicorn deployment.

## Critical Constraints: NOT Multi-Worker or Multi-Instance Safe

**⚠️ WARNING**: Running `uvicorn --workers=N` where N > 1 OR horizontal scaling with multiple pods will cause problems:

### 1. Background Jobs (APScheduler)

- Jobs run N times (once per worker/pod)
- Race conditions on shared resources (MongoDB, AWS API)
- Optimistic concurrency conflicts
- **Why?** Each process has its own APScheduler instance

### 2. SSE Client Registry (In-Memory)

- SSE clients stored in `self._clients: dict[str, SSEClientSubscription]` (in-memory)
- Client connected to Pod A won't receive events broadcast from Pod B
- Sticky sessions required (complex, brittle)
- **Why?** No shared event bus - each process has its own client registry

## Architectural Constraints Summary

```
❌ Multiple Uvicorn workers (--workers > 1)
   → Duplicate background jobs + SSE clients isolated per worker

❌ Horizontal scaling (multiple pods/containers)
   → Duplicate background jobs + SSE clients isolated per pod
   → Events from Pod A don't reach clients on Pod B

✅ Single worker deployment ONLY
   → All clients connect to same process
   → Background jobs run once
   → SSE events reach all clients
```

## Deployment Strategies

### Strategy 1: Separate API and Background Worker Processes (RECOMMENDED)

**Best for**: Small to medium deployments with growing background job load

**This is your best option** given the constraints:

- ✅ API can use multiple Uvicorn workers for request handling
- ✅ SSE clients all connect to same API process
- ✅ Background jobs run in isolated process (no HTTP overhead)
- ✅ Can scale each component independently
- ✅ No orchestration platform required

Split into two processes:

**File: `src/api_server.py`**

```python
"""API server with SSE support, WITHOUT background jobs."""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# CRITICAL: Disable background jobs BEFORE importing
os.environ['WORKER_MONITORING_ENABLED'] = 'false'

from main import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    # Multiple workers OK here - no background jobs, SSE clients in each worker
    # NOTE: SSE sticky sessions required if using multiple workers
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8000,
        workers=1,  # Start with 1, can increase with sticky sessions
        log_level="info"
    )
```

**File: `src/background_worker.py`**

```python
"""Background worker process - ONLY runs scheduled jobs.

This process does NOT serve HTTP requests. It only executes:
- WorkerMetricsCollectionJob (EC2 + CML metrics)
- LabsRefreshJob (lab data refresh)
- AutoImportWorkersJob (discover EC2 instances)
- Any future background jobs

SSE events are published via CloudEvents, which will be delivered to
the API process through the shared MongoDB event store.
"""
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# CRITICAL: Enable background jobs BEFORE importing
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

**Deployment (Development):**

```bash
# Terminal 1: API server with SSE
cd src && python api_server.py

# Terminal 2: Background worker
cd src && python background_worker.py
```

**Deployment (Production with systemd):**

```ini
# /etc/systemd/system/cml-api.service
[Unit]
Description=Lablet Cloud Manager API
After=network.target mongodb.service redis.service

[Service]
Type=exec
User=cmluser
WorkingDirectory=/opt/lablet-cloud-manager/src
Environment="PYTHONPATH=/opt/lablet-cloud-manager/src"
Environment="WORKER_MONITORING_ENABLED=false"
ExecStart=/opt/lablet-cloud-manager/.venv/bin/python api_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

---
# /etc/systemd/system/cml-worker.service
[Unit]
Description=Lablet Cloud Manager Background Worker
After=network.target mongodb.service redis.service cml-api.service

[Service]
Type=exec
User=cmluser
WorkingDirectory=/opt/lablet-cloud-manager/src
Environment="PYTHONPATH=/opt/lablet-cloud-manager/src"
Environment="WORKER_MONITORING_ENABLED=true"
ExecStart=/opt/lablet-cloud-manager/.venv/bin/python background_worker.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Deployment (Docker Compose):**

```yaml
services:
  api:
    build: .
    command: python /app/src/api_server.py
    ports:
      - "8000:8000"
    environment:
      WORKER_MONITORING_ENABLED: "false"
    depends_on:
      - mongodb
      - redis

  worker:
    build: .
    command: python /app/src/background_worker.py
    environment:
      WORKER_MONITORING_ENABLED: "true"
    depends_on:
      - mongodb
      - redis
      - api  # Start after API
```

**Pros:**

- ✅ API process can handle high request load (single worker with async)
- ✅ Background jobs isolated (no HTTP overhead)
- ✅ Can scale workers independently (add more jobs without affecting API)
- ✅ SSE clients all connect to same API process
- ✅ No orchestration platform required
- ✅ Easy to monitor (two separate processes)
- ✅ Graceful shutdown supported

**Cons:**

- ❌ Two processes to manage (mitigated by systemd/Docker Compose)
- ❌ Slightly more complex deployment than single process

---

### Strategy 2: Single Process (Current - Simple but Limited)

**Best for**: Small deployments, MVP, testing

```dockerfile
# Dockerfile
CMD ["uvicorn", "main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

**Or use Gunicorn with Uvicorn worker:**

```bash
gunicorn main:create_app \
    --factory \
    --workers 1 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --graceful-timeout 30 \
    --keep-alive 5
```

**Pros:**

- ✅ Simple deployment
- ✅ Production-ready ASGI server
- ✅ Graceful shutdown

**Cons:**

- ❌ No horizontal scaling (single process)
- ❌ Limited concurrency (async helps, but still one worker)

### Strategy 3: Future Option - Distributed Event Bus (Not Implemented)

**Would enable**: Horizontal scaling with multiple API pods

**Requirements:**

- Replace in-memory SSE registry with Redis Pub/Sub or RabbitMQ
- All API pods subscribe to event bus
- Background worker publishes events to bus
- API pods relay events to their connected SSE clients

**Not recommended for small deployments** - adds significant complexity

---

## Current Configuration Assessment

### Development (`main.py` with `uvicorn.run`)

```python
uvicorn.run(
    "main:create_app",
    factory=True,
    host=app_settings.app_host,
    port=app_settings.app_port,
    reload=app_settings.debug,  # ✅ Single worker, auto-reload
)
```

**Status**: ✅ **CORRECT** - Single worker with reload is fine for development

### Production (Dockerfile)

```dockerfile
CMD ["sh", "-c", "cd /app/src && uvicorn main:create_app --factory --host 0.0.0.0 --port 8000"]
```

**Status**: ⚠️ **MISSING EXPLICIT `--workers 1`** - Should add for clarity

**Recommended change:**

```dockerfile
CMD ["sh", "-c", "cd /app/src && uvicorn main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1"]
```

Or use Gunicorn for better production features:

```dockerfile
CMD ["sh", "-c", "cd /app/src && gunicorn main:create_app --factory --workers 1 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120 --graceful-timeout 30"]
```

---

## Recommended Production Configuration

### For Small to Medium Deployments (< 10K requests/hour)

**Use Strategy 1: Separate API + Worker processes**

```yaml
# docker-compose.yml
services:
  api:
    build: .
    command: python /app/src/api_server.py
    ports:
      - "8000:8000"
    environment:
      WORKER_MONITORING_ENABLED: "false"
    restart: always

  worker:
    build: .
    command: python /app/src/background_worker.py
    environment:
      WORKER_MONITORING_ENABLED: "true"
    restart: always
```

### For Large Deployments (> 10K requests/hour)

**Implement distributed event bus** (requires architecture changes):

- Redis Pub/Sub for SSE events
- Multiple API pods (horizontal scaling)
- Single background worker pod
- Sticky sessions on load balancer

---

## Key Takeaways

1. **In-memory SSE + APScheduler = Single Process Only** - No multi-worker OR horizontal scaling
2. **Best solution for small deployments**: Separate API and background worker processes (Strategy 1)
3. **Development**: Current single-worker with reload is perfect (no changes needed)
4. **Production**: Implement separate processes to isolate concerns and enable independent scaling
5. **Future scaling**: Requires distributed event bus (Redis Pub/Sub) for SSE - significant architecture change

## Decision Guide

**Current deployment size: Small (MVP, < 1000 users)**
→ **Keep single process** (Strategy 2) - simplest, works fine

**Growing deployment: Background jobs taking > 30% CPU**
→ **Separate API/Worker** (Strategy 1) - isolate workloads

**Large deployment: > 10K requests/hour, many SSE clients**
→ **Need distributed event bus** (Strategy 3) - major refactoring required

---

## Action Items

### Immediate (For Growth Path)

- [ ] Create `src/api_server.py` (API without background jobs)
- [ ] Create `src/background_worker.py` (jobs without HTTP server)
- [ ] Update `docker-compose.yml` to run both services
- [ ] Add systemd service files for production VM deployment
- [ ] Document process separation in deployment guide

### Short-term (Monitoring)

- [ ] Add metrics for background job execution time
- [ ] Monitor API response times separately from job execution
- [ ] Alert on worker process crashes
- [ ] Health check endpoints for both processes

### Long-term (If Needed)

- [ ] Implement Redis Pub/Sub for SSE events
- [ ] Refactor SSEEventRelay to use distributed event bus
- [ ] Add sticky sessions configuration for load balancer
- [ ] Horizontal scaling tests with multiple API pods

---

## Testing Multi-Worker Behavior

**DO NOT run this in production:**

```bash
# Test to see duplicate jobs (for demonstration only)
uvicorn main:create_app --factory --workers 3

# Monitor logs - you'll see 3x background jobs running!
# This proves why --workers=1 is required
```

## References

- [Uvicorn Deployment](https://www.uvicorn.org/deployment/)
- [APScheduler Multiple Processes](https://apscheduler.readthedocs.io/en/stable/userguide.html#running-the-scheduler-in-multiple-processes)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/concepts/)
