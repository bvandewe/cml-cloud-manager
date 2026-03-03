# APScheduler Refactoring - Phase 2 Complete

**Status**: ✅ All recommendations implemented
**Date**: 2024
**Related**: [APSCHEDULER_REFACTORING_SUMMARY.md](./APSCHEDULER_REFACTORING_SUMMARY.md)

---

## Summary

This document tracks the completion of all APScheduler improvement recommendations from Phase 1. All 5 critical issues have been resolved.

---

## ✅ Completed Improvements

### 1. Job Serialization Fix

**Problem**: `WorkerMetricsCollectionJob.__dict__` included non-serializable dependencies (repositories, boto3 clients, observer callbacks).

**Solution**:

- Modified `WorkerMonitoringScheduler.start_monitoring_worker_async()` to serialize only `worker_id` in task descriptor
- Updated `BackgroundTaskScheduler` constructor to accept optional `service_provider` parameter
- Modified `BackgroundTaskScheduler.deserialize_task()` to call `task.configure(service_provider)` after deserialization
- Updated `WorkerMetricsCollectionJob.configure()` to inject dependencies from service provider

**Files Changed**:

- `application/services/worker_monitoring_scheduler.py` (line 169)
- `application/services/background_scheduler.py` (line 195-218, 283-317)
- `application/services/worker_metrics_collection_job.py` (line 45-81)
- `main.py` (line 69)

**Code**:

```python
# Before (serialized everything):
task_descriptor = RecurrentTaskDescriptor(
    id=job_id,
    name="WorkerMetricsCollectionJob",
    data=job.__dict__,  # ❌ Non-serializable
    interval=self._poll_interval,
)

# After (serialize only ID):
task_descriptor = RecurrentTaskDescriptor(
    id=job_id,
    name="WorkerMetricsCollectionJob",
    data={"worker_id": worker_id},  # ✅ Serializable
    interval=self._poll_interval,
)

# Dependency injection on deserialization:
def configure(self, service_provider=None, **kwargs):
    if service_provider:
        if not self.aws_ec2_client:
            self.aws_ec2_client = service_provider.get_required_service(AwsEc2Client)
        if not self.worker_repository:
            self.worker_repository = service_provider.get_required_service(CMLWorkerRepository)
```

---

### 2. Job Stop Implementation

**Problem**: `WorkerMonitoringScheduler.stop_monitoring_worker_async()` had TODO comment and didn't actually stop APScheduler jobs.

**Solution**:

- Added `background_task_scheduler` parameter to `WorkerMonitoringScheduler.__init__()`
- Implemented actual `scheduler.stop_task(job_id)` call in `stop_monitoring_worker_async()`
- Updated `main.py` to inject `BackgroundTaskScheduler` from service provider

**Files Changed**:

- `application/services/worker_monitoring_scheduler.py` (line 51-79, 192-216)
- `main.py` (line 69)

**Code**:

```python
# Before:
async def stop_monitoring_worker_async(self, worker_id: str) -> None:
    # TODO: Need to add stop_task method
    del self._active_jobs[worker_id]

# After:
async def stop_monitoring_worker_async(self, worker_id: str) -> None:
    job_id = self._active_jobs.get(worker_id)
    if not job_id:
        return

    try:
        success = self._background_task_scheduler.stop_task(job_id)
        if success:
            logger.info(f"🛑 Stopped monitoring worker: {worker_id}")
    except Exception as e:
        logger.error(f"❌ Error stopping job: {e}")
    finally:
        del self._active_jobs[worker_id]
```

---

### 3. Redis Job Store Configuration

**Problem**: No Redis configuration in settings for distributed job persistence.

**Solution**:

- Added `background_job_store` dict to `Settings` class with Redis configuration
- Configured for Redis DB 1 (separate from session storage DB 0)
- Alternative MongoDB configuration documented

**Files Changed**:

- `application/settings.py` (line 156-165)

**Code**:

```python
# Background Job Store Configuration (APScheduler persistence)
background_job_store: dict[str, Any] = {
    # Redis configuration (recommended for production)
    "redis_host": "redis",
    "redis_port": 6379,
    "redis_db": 1,  # Use separate DB from session storage (DB 0)
    # Alternatively, use MongoDB (if Redis not available)
    # "mongo_uri": "mongodb://root:pass@mongodb:27017/?authSource=admin",  # pragma: allowlist secret
    # "mongo_db": "lablet_cloud_manager",
    # "mongo_collection": "background_jobs",
}
```

**Note**: The `BackgroundTaskScheduler.configure()` method already handles Redis/MongoDB jobstore initialization based on these settings (line 424-468 in background_scheduler.py).

---

### 4. Observer Pattern Serialization

**Problem**: `WorkerMetricsCollectionJob._observers` list with handler instances wouldn't serialize to Redis.

**Solution**: This was automatically resolved by fix #1 (job serialization). Since we now serialize only `worker_id`, the `_observers` list is not included in serialized data.

**Known Limitation**: In distributed environments where jobs deserialize on different nodes, observers won't be re-subscribed automatically. This is acceptable for the current single-instance deployment model.

**Future Enhancement**: If multi-instance deployment is needed, consider:

- Using a centralized event bus instead of observer pattern
- Implementing an observer registry that automatically re-subscribes on deserialization
- Using domain events + event handlers instead of direct observer callbacks

---

### 5. Job Termination Handling

**Problem**: Jobs continued running for terminated/deleted workers.

**Solution**:

- Added worker existence check at start of `run_every()` method
- Added worker status check for `TERMINATED` state
- Both checks raise exceptions to signal APScheduler to stop the job

**Files Changed**:

- `application/services/worker_metrics_collection_job.py` (line 120-138)

**Code**:

```python
async def run_every(self, *args, **kwargs) -> None:
    try:
        # 1. Load worker from repository
        worker = await self.worker_repository.get_by_id_async(self.worker_id)
        if not worker:
            logger.warning(f"⚠️ Worker {self.worker_id} not found - stopping job")
            # Raise exception to signal APScheduler to stop this job
            raise Exception(f"Worker {self.worker_id} not found - terminating job")

        # Check if worker is terminated
        if worker.state.status == CMLWorkerStatus.TERMINATED:
            logger.info(f"🛑 Worker {self.worker_id} is terminated - stopping job")
            raise Exception(f"Worker {self.worker_id} is terminated - stopping job")

        # Continue with metrics collection...
```

---

## Architecture Improvements

### Dependency Injection Pattern

The refactoring introduced a clean dependency injection pattern for background jobs:

1. **Job Registration**: Tasks are discovered and registered as transient services in DI container
2. **Serialization**: Only minimal data (IDs, config) is serialized to Redis
3. **Deserialization**: Service provider re-injects dependencies via `configure()` method
4. **Lifecycle**: Jobs can safely be persisted, moved between nodes, and restarted

### Benefits

1. **Redis Persistence**: Jobs survive application restarts
2. **Distributed Execution**: Jobs can run on any node with access to Redis
3. **Memory Efficiency**: Only job parameters stored, not entire object graphs
4. **Clean Separation**: Job logic separate from infrastructure concerns
5. **Testability**: Jobs can be tested in isolation with mock dependencies

---

## Testing Recommendations

### Unit Tests

```python
class TestWorkerMetricsCollectionJob:
    async def test_terminated_worker_stops_job(self):
        # Arrange
        worker = create_terminated_worker()
        repository = Mock(get_by_id_async=AsyncMock(return_value=worker))
        job = WorkerMetricsCollectionJob(worker.id(), repository=repository, ...)

        # Act & Assert
        with pytest.raises(Exception, match="terminated"):
            await job.run_every()

    async def test_missing_worker_stops_job(self):
        # Arrange
        repository = Mock(get_by_id_async=AsyncMock(return_value=None))
        job = WorkerMetricsCollectionJob("missing-id", repository=repository, ...)

        # Act & Assert
        with pytest.raises(Exception, match="not found"):
            await job.run_every()

    async def test_job_serialization(self):
        # Arrange
        job = WorkerMetricsCollectionJob(worker_id="test-123")

        # Act
        descriptor = RecurrentTaskDescriptor(
            id="job-1",
            name="WorkerMetricsCollectionJob",
            data={"worker_id": job.worker_id},
            interval=300
        )

        # Assert
        assert descriptor.data == {"worker_id": "test-123"}  # Only ID serialized
        assert "aws_ec2_client" not in descriptor.data
        assert "_observers" not in descriptor.data
```

### Integration Tests

```python
class TestBackgroundSchedulerIntegration:
    async def test_job_persists_to_redis(self):
        # Start scheduler with Redis
        # Schedule job
        # Stop scheduler
        # Start new scheduler
        # Verify job is restored from Redis
        pass

    async def test_job_stop_removes_from_scheduler(self):
        # Schedule job
        # Stop job via WorkerMonitoringScheduler
        # Verify job no longer in APScheduler
        pass

    async def test_dependency_injection_on_deserialization(self):
        # Create task descriptor with only worker_id
        # Deserialize with service provider
        # Verify dependencies are injected
        pass
```

---

## Deployment Checklist

- [ ] Ensure Redis is running and accessible
- [ ] Update `.env` with Redis connection details:

  ```env
  REDIS_ENABLED=true
  REDIS_URL=redis://redis:6379/0
  ```

- [ ] Verify `background_job_store` settings in application settings
- [ ] Test job persistence across restarts:
  1. Start application
  2. Create workers (jobs scheduled)
  3. Stop application
  4. Verify jobs persisted in Redis (`redis-cli KEYS "apscheduler.*"`)
  5. Restart application
  6. Verify jobs resumed
- [ ] Monitor for exceptions in job execution logs
- [ ] Verify terminated workers stop monitoring jobs

---

## Performance Considerations

1. **Redis Memory**: Each job descriptor is ~1KB. With 1000 workers, expect ~1MB Redis usage for job storage.
2. **Job Execution**: Each job runs every 5 minutes by default. Adjust `worker_metrics_poll_interval` as needed.
3. **Dependency Injection Overhead**: Negligible - dependencies resolved once during deserialization.
4. **Observer Pattern**: Current implementation doesn't persist observers. For distributed deployments, consider event bus pattern.

---

## Known Limitations

1. **Observer Re-subscription**: Observers not automatically re-subscribed after deserialization. Current workaround: Single-instance deployment where jobs don't cross node boundaries.
2. **Job Failure Handling**: Jobs that raise exceptions are stopped. Consider implementing retry logic for transient failures.
3. **Monitoring Dashboard**: No built-in UI for viewing scheduled jobs. Consider adding admin endpoint: `GET /admin/jobs`.

---

## Future Enhancements

### High Priority

- [ ] Implement observer registry for automatic re-subscription
- [ ] Add retry logic for transient failures
- [ ] Add admin API for job monitoring

### Medium Priority

- [ ] Implement circuit breaker for failing jobs
- [ ] Add metrics collection for job execution
- [ ] Create job execution history tracking

### Low Priority

- [ ] Build admin dashboard for job management
- [ ] Implement job priority system
- [ ] Add support for job dependencies

---

## Related Documentation

- [APScheduler Refactoring Summary](./APSCHEDULER_REFACTORING_SUMMARY.md) - Phase 1 summary
- [Background Task Scheduling](https://bvandewe.github.io/pyneuro/features/background-task-scheduling/) - Neuroglia framework docs
- [ROA Migration Plan](./ROA_MIGRATION_PLAN.md) - Next phase planning

---

**Next Steps**: Proceed with Resource-Oriented Architecture (ROA) implementation as outlined in ROA_MIGRATION_PLAN.md.
