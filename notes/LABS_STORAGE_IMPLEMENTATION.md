# Labs Storage and Refresh Implementation

## Implementation Summary

This document outlines the labs storage and refresh system that was implemented to cache lab data in a separate MongoDB collection with operation history tracking.

## What Was Implemented

### 1. Domain Entities (`src/domain/entities/lab_record.py`)

✅ Created `LabRecord` aggregate following the AggregateRoot pattern
✅ `LabRecordState` with all lab fields and operation history
✅ `LabOperation` value object for tracking state changes
✅ Methods:

- `create()` - Factory method for new lab records
- `update_from_cml()` - Updates record with change detection and history tracking
- Maintains ring buffer of last 50 operations per lab

### 2. Domain Events (`src/domain/events/lab_record_events.py`)

✅ `LabRecordCreatedDomainEvent` - Raised when lab first discovered
✅ `LabRecordUpdatedDomainEvent` - Raised when lab data refreshed from CML
✅ `LabStateChangedDomainEvent` - Raised when lab state changes (e.g., STARTED → STOPPED)

### 3. Repository Interface (`src/domain/repositories/lab_record_repository.py`)

✅ Abstract `LabRecordRepository` interface with methods:

- `get_by_id_async()`
- `get_by_lab_id_async()` - Get by worker_id + lab_id
- `get_all_by_worker_async()` - All labs for a worker
- `get_all_async()`
- `add_async()`, `update_async()`, `remove_async()`
- `remove_by_id_async()`, `remove_by_worker_async()`

### 4. MongoDB Repository (`src/integration/repositories/motor_lab_record_repository.py`)

✅ `MongoLabRecordRepository` implementation using Neuroglia's MotorRepository
✅ Automatic tracing and domain event publishing via TracedRepositoryMixin
✅ Indexes:

- `worker_id` - Quick worker-specific queries
- `(worker_id, lab_id)` unique compound index
- `last_synced_at` - For cleanup operations
✅ `ensure_indexes_async()` method for index creation

### 5. Background Refresh Job (`src/application/services/labs_refresh_job.py`)

✅ `LabsRefreshJob` - RecurrentBackgroundJob for 30-minute refresh cycles
✅ Features:

- Fetches labs from all active workers
- Creates new lab records or updates existing ones
- Automatic change detection (compares state, title, node_count, link_count)
- Records state transitions in operation_history
- Error handling - continues on failure for individual workers/labs
- OpenTelemetry tracing with metrics (synced/created/updated counts)
- Datetime parsing for CML timestamp strings

### 6. Updated Commands

✅ Added `LabRecordRepository` import to `GetWorkerLabsCommand` (prepared for database queries)

## Architecture Benefits

1. **Performance** - Labs fetched from database instead of CML API on every UI request
2. **History Tracking** - Last 50 operations per lab recorded with timestamps and changed fields
3. **Separation of Concerns** - Labs in separate collection, doesn't bloat worker documents
4. **Reduced CML Load** - API called every 30 minutes instead of on-demand
5. **Reliability** - Cached data available even if CML temporarily unreachable
6. **Auditability** - Operation history provides audit trail of lab changes

## What Needs to Be Done

### 1. Repository Registration in DI Container

**File**: `src/main.py`

Add lab record repository registration:

```python
# After worker repository registration (~line 350)
from domain.repositories.lab_record_repository import LabRecordRepository
from integration.repositories.motor_lab_record_repository import MongoLabRecordRepository

# Register lab record repository
services.add_singleton(
    LabRecordRepository,
    lambda sp: MongoLabRecordRepository(
        client=sp.get_required_service(AsyncIOMotorClient),
        database_name=app_settings.mongodb_database_name,
        collection_name="lab_records",  # Separate collection
        serializer=sp.get_required_service(JsonSerializer),
        entity_type=LabRecord,
        mediator=sp.get_required_service(Mediator),
    ),
)
```

### 2. Create Indexes on Startup

**File**: `src/main.py` in `lifespan()` function

After worker repository index creation:

```python
# Create lab record indexes
lab_record_repo = service_provider.get_required_service(LabRecordRepository)
await lab_record_repo.ensure_indexes_async()
logger.info("✅ Lab record indexes created")
```

### 3. Schedule Labs Refresh Job

**File**: `src/main.py` in `lifespan()` function

After worker metrics jobs are scheduled:

```python
# Schedule labs refresh job (runs every 30 minutes for all workers)
from application.services.labs_refresh_job import LabsRefreshJob

labs_refresh_job = LabsRefreshJob(
    worker_repository=worker_repository,
    lab_record_repository=lab_record_repo,
)

# Schedule to run every 30 minutes
await background_scheduler.schedule_recurrent_job_async(
    task_id="labs-refresh-global",
    job=labs_refresh_job,
    interval_minutes=30,
    run_immediately=True,  # Run on startup
)

logger.info("✅ Scheduled labs refresh job (30-minute interval)")
```

### 4. Update GetWorkerLabsCommand to Use Database

**File**: `src/application/commands/get_worker_labs_command.py`

Update handler to fetch from database instead of CML API:

```python
def __init__(
    self,
    # ... existing parameters ...
    lab_record_repository: LabRecordRepository,  # Add this
):
    # ... existing initialization ...
    self._lab_record_repository = lab_record_repository

async def handle_async(self, request: GetWorkerLabsCommand) -> OperationResult[list[dict[str, Any]]]:
    """Handle the command - fetch labs from database."""
    with tracer.start_as_current_span("get_worker_labs_command.handle") as span:
        command = request
        span.set_attribute("worker.id", command.worker_id)

        try:
            # Fetch lab records from database
            lab_records = await self._lab_record_repository.get_all_by_worker_async(
                command.worker_id
            )

            # Convert to dict format for API response
            labs = []
            for record in lab_records:
                lab_dict = {
                    "id": record.state.lab_id,
                    "title": record.state.title,
                    "description": record.state.description,
                    "notes": record.state.notes,
                    "state": record.state.state,
                    "owner": record.state.owner_fullname,
                    "owner_username": record.state.owner_username,
                    "node_count": record.state.node_count,
                    "link_count": record.state.link_count,
                    "created": record.state.cml_created_at.isoformat() if record.state.cml_created_at else None,
                    "modified": record.state.modified_at.isoformat() if record.state.modified_at else None,
                    "groups": record.state.groups,
                    "last_synced": record.state.last_synced_at.isoformat() if record.state.last_synced_at else None,
                }
                labs.append(lab_dict)

            span.set_attribute("labs.count", len(labs))
            span.set_status(Status(StatusCode.OK))
            return self.ok(labs)

        except Exception as e:
            log.error(f"Failed to fetch labs for worker {command.worker_id}: {e}", exc_info=True)
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            return self.bad_request(str(e))
```

### 5. Optional: Add Force Refresh Endpoint

**File**: `src/api/controllers/workers_controller.py`

Add optional endpoint to force immediate refresh:

```python
@router.post(
    "/region/{region}/workers/{worker_id}/labs/refresh",
    tags=["Workers"],
    summary="Force refresh labs from CML",
    description="Triggers immediate lab refresh from CML API instead of waiting for background job",
)
async def force_refresh_worker_labs(
    region: str,
    worker_id: str,
    current_user=Depends(get_current_user_with_roles(["admin", "manager"])),
) -> dict:
    """Force refresh labs for a worker from CML API."""
    # Implementation would trigger immediate CML API fetch and database update
    pass
```

### 6. Optional: Add Cleanup for Deleted Labs

**File**: `src/application/services/labs_refresh_job.py`

Add to `_refresh_worker_labs()` method:

```python
# After syncing all labs, check for deleted labs
current_lab_ids = {lab.id for lab in labs}
existing_records = await self.lab_record_repository.get_all_by_worker_async(worker_id)

for record in existing_records:
    if record.state.lab_id not in current_lab_ids:
        # Lab no longer exists in CML - delete or mark as deleted
        await self.lab_record_repository.remove_async(record)
        logger.info(f"Removed lab record {record.state.lab_id} - no longer exists in CML")
```

## Testing the Implementation

### 1. Verify Repository Registration

```bash
# Check logs on startup for:
✅ Lab record indexes created
✅ Scheduled labs refresh job (30-minute interval)
```

### 2. Check Background Job Execution

```bash
# Watch logs for:
🔄 Starting labs refresh cycle
Worker <worker_id>: synced=X, created=Y, updated=Z
✅ Labs refresh complete: synced=X, created=Y, updated=Z
```

### 3. Query MongoDB Directly

```javascript
// Connect to MongoDB and check collection
use lablet_cloud_manager
db.lab_records.find().pretty()
db.lab_records.getIndexes()
```

### 4. Verify UI Still Works

- Open worker details modal
- Click "Labs" tab
- Labs should load from database (faster than before)
- Check browser network tab - should see GET request to `/api/v1/workers/region/{region}/workers/{worker_id}/labs`

### 5. Check Operation History

```javascript
// Find a lab that has changed state
db.lab_records.find({
  "operation_history": { $exists: true, $ne: [] }
}).pretty()

// Should see entries like:
{
  "timestamp": "2025-11-17T10:30:00Z",
  "previous_state": "STOPPED",
  "new_state": "STARTED",
  "changed_fields": {
    "node_count": {"old": 0, "new": 5}
  }
}
```

## Migration Notes

### Data Migration

- No migration needed - fresh collection
- First run will populate all existing labs from CML
- Run immediately on startup recommended (`run_immediately=True`)

### Rollback Plan

If issues arise:

1. Comment out lab refresh job scheduling
2. Revert GetWorkerLabsCommand to fetch from CML API directly (old behavior)
3. Drop `lab_records` collection if needed

### Performance Impact

- Positive: UI loads faster (database query vs CML API)
- Positive: Reduced load on CML API
- Minimal: Background job runs every 30 minutes (low frequency)
- Storage: ~5-10KB per lab record (with 50-entry history)

## Future Enhancements

1. **Configurable History Size** - Make max_history_size configurable per worker/environment
2. **Smart Refresh** - Only refresh labs for workers with recent activity
3. **Lab Metrics** - Track lab uptime, state transition frequency, resource usage over time
4. **Alerting** - Notify on unexpected lab state changes or failures
5. **Bulk Operations** - API endpoints for bulk lab operations (start all, stop all)
6. **Lab Templates** - Track common lab configurations for quick deployment

## Files Created

1. `src/domain/entities/lab_record.py` - Domain entity
2. `src/domain/events/lab_record_events.py` - Domain events
3. `src/domain/repositories/lab_record_repository.py` - Repository interface
4. `src/integration/repositories/motor_lab_record_repository.py` - MongoDB implementation
5. `src/application/services/labs_refresh_job.py` - Background job
6. `notes/LABS_STORAGE_IMPLEMENTATION.md` - This document

## Files Modified

1. `src/application/commands/get_worker_labs_command.py` - Added lab_record_repository import (ready for database queries)

## Next Steps

Follow the "What Needs to Be Done" section above to complete the integration:

1. Register repository in DI container
2. Create indexes on startup
3. Schedule background job
4. Update GetWorkerLabsCommand to use database
5. Test the implementation

Estimated time to complete: 30-45 minutes
