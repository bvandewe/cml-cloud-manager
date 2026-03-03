# Background Task Scheduling

The Lablet Cloud Manager implements a distributed background task scheduling system using APScheduler, integrated with the Neuroglia framework's dependency injection and service provider patterns.

## Overview

The background scheduling system provides:

- **Distributed Job Management**: Redis/MongoDB-backed persistence for jobs that survive application restarts
- **Reactive Streams**: Integration with Neuroglia's reactive programming patterns
- **Dependency Injection**: Automatic resolution of service dependencies for deserialized jobs
- **Worker Monitoring**: Automated metrics collection and health monitoring for CML Workers

## Architecture

```mermaid
graph TB
    subgraph "Application Startup"
        A[main.py] --> B[BackgroundTaskScheduler.configure]
        B --> C[Scan for @backgroundjob classes]
        C --> D[Register as HostedService]
    end

    subgraph "Job Scheduling"
        E[WorkerMonitoringScheduler] --> F[BackgroundTasksBus]
        F --> G[BackgroundTaskScheduler]
        G --> H{Job Type}
        H -->|Scheduled| I[One-time execution]
        H -->|Recurrent| J[Periodic execution]
    end

    subgraph "Job Persistence"
        G --> K[(Redis/MongoDB)]
        K --> L[Job Recovery on Restart]
    end

    subgraph "Job Execution"
        I --> M[run_at method]
        J --> N[run_every method]
        M --> O[Dependency Injection]
        N --> O
    end
```

## Key Components

### BackgroundTaskScheduler

The core scheduler service that manages job lifecycle:

```python
from application.services import BackgroundTaskScheduler

# Configured automatically during application startup
BackgroundTaskScheduler.configure(
    builder,
    modules=["application.services"]  # Scans for @backgroundjob classes
)
```

**Features**:

- Automatic job discovery via `@backgroundjob` decorator
- Redis or MongoDB job store for persistence
- Graceful startup and shutdown
- Service provider integration for dependency injection

### BackgroundTasksBus

Message bus for scheduling tasks:

```python
from application.services import BackgroundTasksBus, RecurrentTaskDescriptor

# Schedule a recurrent job
task_descriptor = RecurrentTaskDescriptor(
    id="unique-job-id",
    name="WorkerMetricsCollectionJob",
    data={"worker_id": "worker-123"},
    interval=300  # seconds
)

background_task_bus.schedule_task(task_descriptor)
```

### Job Types

#### Recurrent Background Job

For periodic execution:

```python
from application.services import RecurrentBackgroundJob, backgroundjob

@backgroundjob(task_type="recurrent")
class MyPeriodicJob(RecurrentBackgroundJob):
    def __init__(self, resource_id: str):
        self.resource_id = resource_id

    def configure(self, service_provider=None, **kwargs):
        """Called after deserialization to inject dependencies"""
        if service_provider:
            self.repository = service_provider.get_required_service(MyRepository)

    async def run_every(self, *args, **kwargs):
        """Executed at each interval"""
        # Job logic here
        pass
```

#### Scheduled Background Job

For one-time execution:

```python
from application.services import ScheduledBackgroundJob, backgroundjob

@backgroundjob(task_type="scheduled")
class MyScheduledJob(ScheduledBackgroundJob):
    async def run_at(self, *args, **kwargs):
        """Executed at scheduled time"""
        # Job logic here
        pass
```

## Configuration

### Application Settings

```python
# src/application/settings.py

class Settings(ApplicationSettings):
    # Background Job Store Configuration
    background_job_store: dict[str, Any] = {
        # Redis configuration (recommended for production)
        "redis_host": "redis",
        "redis_port": 6379,
        "redis_db": 1,  # Separate from session storage (DB 0)

        # Alternative: MongoDB configuration
        # "mongo_uri": "mongodb://root:pass@mongodb:27017/?authSource=admin",  # pragma: allowlist secret
        # "mongo_db": "lablet_cloud_manager",
        # "mongo_collection": "background_jobs",
    }
```

### Dependencies

APScheduler with Redis support:

```toml
[tool.poetry.dependencies]
apscheduler = "^3.11.1"
redis = ">=7.0.1,<8.0.0"
```

## Job Serialization Pattern

The system uses a serialization pattern that stores only minimal data, with dependencies re-injected on deserialization:

1. **Serialization**: Only business data is stored (IDs, configuration)
2. **Deserialization**: Service provider re-injects dependencies via `configure()` method
3. **Execution**: Job runs with full dependencies available

**Example**:

```python
# When scheduling
task_descriptor = RecurrentTaskDescriptor(
    id="job-123",
    name="WorkerMetricsCollectionJob",
    data={"worker_id": "worker-456"},  # Only ID serialized
    interval=300
)

# On deserialization
task = deserialize_task(task_type, task_descriptor)
task.configure(service_provider=service_provider)  # Dependencies injected
```

## Worker Monitoring Use Case

The background scheduling system is used to implement worker monitoring:

```python
# WorkerMonitoringScheduler starts monitoring jobs
await scheduler.start_monitoring_worker_async(worker_id)

# Creates and schedules WorkerMetricsCollectionJob
job = WorkerMetricsCollectionJob(
    worker_id=worker_id,
    # Dependencies injected via configure()
)

# Job runs every 5 minutes (default)
# - Polls AWS EC2 for instance status
# - Collects CloudWatch metrics
# - Updates worker state
# - Emits events to observers
```

## Lifecycle Management

### Startup

1. `BackgroundTaskScheduler.configure()` scans for `@backgroundjob` classes
2. Scheduler registered as `HostedService` (auto-starts)
3. Jobs persisted in Redis/MongoDB are restored
4. Worker monitoring discovers active workers and schedules jobs

### Shutdown

1. `HostedService` shutdown hook triggered
2. Scheduler gracefully stops (waits for running jobs)
3. Job state persisted to Redis/MongoDB
4. Clean shutdown completed

### Job Recovery

Jobs automatically resume after application restart:

1. Scheduler starts and connects to Redis/MongoDB
2. Previously scheduled jobs are restored
3. Missed executions handled according to `misfire_grace_time`
4. Normal execution resumes

## Error Handling

### Job Failures

Jobs that raise exceptions are logged but don't stop the scheduler:

```python
async def run_every(self, *args, **kwargs):
    try:
        # Job logic
        pass
    except Exception as e:
        logger.error(f"Job failed: {e}")
        raise  # APScheduler handles retry logic
```

### Worker Termination

Jobs check for worker state and terminate gracefully:

```python
async def run_every(self, *args, **kwargs):
    worker = await self.worker_repository.get_by_id_async(self.worker_id)

    if not worker or worker.state.status == CMLWorkerStatus.TERMINATED:
        raise Exception(f"Worker terminated - stopping job")
```

## Best Practices

1. **Minimal Serialization**: Store only IDs and configuration, not service instances
2. **Dependency Injection**: Use `configure()` method for service resolution
3. **Graceful Termination**: Check for resource existence before processing
4. **Error Handling**: Let jobs fail cleanly to enable retry logic
5. **Observability**: Use OpenTelemetry spans in job execution

## Monitoring

### Job Status

Check scheduled jobs:

```python
jobs = background_task_scheduler.list_tasks()
for job in jobs:
    print(f"Job: {job.id}, Next run: {job.next_run_time}")
```

### Metrics

The system emits OpenTelemetry metrics:

- Job execution duration
- Job success/failure counts
- Active job count

## Troubleshooting

### Jobs Not Persisting

Check Redis/MongoDB connection:

```bash
# Redis
redis-cli ping

# Check job keys
redis-cli KEYS "apscheduler.*"
```

### Jobs Not Resuming After Restart

1. Verify job store configuration in settings
2. Check Redis/MongoDB connectivity
3. Review scheduler startup logs

### High Memory Usage

Monitor job count and interval:

```python
# Adjust poll interval
worker_metrics_poll_interval: int = 600  # 10 minutes instead of 5
```

## References

- [APScheduler Documentation](https://apscheduler.readthedocs.io/)
- [Neuroglia Background Tasks](https://bvandewe.github.io/pyneuro/features/background-task-scheduling/)
- [Worker Monitoring Architecture](worker-monitoring.md)
