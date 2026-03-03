# Summary: CloudEvent Publishing Fix and Repository Enhancement

## Issues Resolved

### 1. UserLoggedIn CloudEvent Publishing Error

**Problem**: `object of type 'int' has no len()` error when publishing CloudEvents

**Root Cause**:

- neuroglia's `JsonSerializer.serialize()` returns `bytearray`
- httpx library's `client.post(content=...)` doesn't handle `bytearray` properly (treats it as streaming)
- httpx expects `bytes` or `str` for the content parameter

**Solution**:
Monkey-patched `CloudEventPublisher.on_publish_cloud_event_async()` to convert `bytearray` to `bytes`:

```python
serialized = self._json_serializer.serialize(e)
content = bytes(serialized) if isinstance(serialized, bytearray) else serialized
```

**Location**: `src/main.py` lines 115-147

---

### 2. Task Domain Events Not Published as CloudEvents

**Problem**: Task creation/update events were not being emitted as CloudEvents, only UserLoggedIn events worked

**Root Cause**:

- `MotorRepository.configure()` registered `MotorRepository[Task, str]` **with mediator injected**
- Separate manual registration: `services.add_scoped(TaskRepository, MongoTaskRepository)` **without mediator injection**
- Command handlers used `TaskRepository`, which resolved to `MongoTaskRepository` without mediator
- Without mediator, repository's `_publish_domain_events()` returned early without publishing
- UserLoggedIn worked because it was published directly via `mediator.publish_async()` in auth controller

**Solution**:
Changed `TaskRepository` registration to use a factory that properly instantiates `MongoTaskRepository` with mediator:

```python
def create_mongo_task_repository(sp) -> TaskRepository:
    from motor.motor_asyncio import AsyncIOMotorClient

    return MongoTaskRepository(
        mongo_client=sp.get_required_service(AsyncIOMotorClient),
        serializer=sp.get_required_service(JsonSerializer),
        mediator=sp.get_required_service(Mediator),
    )

services.add_scoped(TaskRepository, implementation_factory=create_mongo_task_repository)
```

**Why MongoTaskRepository instead of MotorRepository**:

- `MongoTaskRepository` extends `MotorRepository` with custom methods (`get_by_id_async`, `get_all_async`, `get_by_assignee_async`, `get_by_department_async`)
- These methods are part of the `TaskRepository` interface contract
- Must use `MongoTaskRepository` to satisfy the interface while ensuring mediator is injected

**Location**: `src/main.py` lines 165-177


---

## Current Implementation

### Fixed Type Hints

```python
# Type-annotated factory function for clarity
def get_task_repository(sp) -> TaskRepository:
    return sp.get_required_service(MotorRepository[Task, str])

services.add_scoped(TaskRepository, implementation_factory=get_task_repository)
```

### Verification

✅ TaskCreatedDomainEvent now publishes as CloudEvent `io.lablet-cloud-manager.task.created.v1`
✅ All task update events (title, priority, status, etc.) publish properly
✅ Events go through full mediation pipeline with all behaviors
✅ CloudEvents successfully published to event-player service

---

## Recommendation for Neuroglia Framework

### Proposed Enhancement: `domain_repository_type` Parameter

**Goal**: Simplify repository configuration by automatically registering domain layer interfaces

**Current Workaround** (what we need now):

```python
MotorRepository.configure(builder, Task, str, "lablet_cloud_manager", "tasks")

def get_task_repository(sp) -> TaskRepository:
    return sp.get_required_service(MotorRepository[Task, str])

services.add_scoped(TaskRepository, implementation_factory=get_task_repository)
```

**Proposed Enhancement** (ideal future API):

```python
# Single line - automatically registers both framework and domain interfaces
MotorRepository.configure(
    builder,
    entity_type=Task,
    key_type=str,
    database_name="lablet_cloud_manager",
    collection_name="tasks",
    domain_repository_type=TaskRepository,  # NEW: Domain layer interface
)
```

### Implementation Details

Add optional `domain_repository_type` parameter to `MotorRepository.configure()`:

```python
if domain_repository_type is not None:
    def get_domain_repository(sp):
        return sp.get_required_service(MotorRepository[entity_type, key_type])

    builder.services.add_scoped(
        domain_repository_type,
        implementation_factory=get_domain_repository,
    )
```

**Benefits**:

- ✅ Cleaner, more intuitive API
- ✅ Supports DDD separation of concerns
- ✅ Eliminates boilerplate factory functions
- ✅ Ensures domain interface gets mediator-enabled instance
- ✅ Backward compatible (optional parameter)

**Full Specification**: See `notes/NEUROGLIA_REPOSITORY_ENHANCEMENT.md`

---

## Files Modified

1. `src/main.py`:
   - Added monkey-patch for CloudEventPublisher (bytearray→bytes conversion)
   - Fixed TaskRepository registration to use properly-configured MotorRepository
   - Added type hints to factory function

2. `src/domain/events/user.py`:
   - Changed `login_at` from `datetime` to `str` (ISO8601)
   - Convert datetime in constructor for CloudEvent compatibility

3. `src/api/controllers/auth_controller.py`:
   - Wrapped aggregate_id in `str()` to ensure string type

---

## Testing

Both CloudEvent types now successfully publish:

```
✅ io.lablet-cloud-manager.user.loggedin.v1
✅ io.lablet-cloud-manager.task.created.v1
✅ io.lablet-cloud-manager.task.title.updated.v1
✅ io.lablet-cloud-manager.task.status.updated.v1
✅ io.lablet-cloud-manager.task.priority.updated.v1
✅ io.lablet-cloud-manager.task.assignee.updated.v1
✅ io.lablet-cloud-manager.task.department.updated.v1
```

All events properly flow through:

1. Domain aggregate → Repository
2. Repository → Mediator.publish_async()
3. Mediator → DomainEventCloudEventBehavior
4. CloudEventBehavior → CloudEventBus
5. CloudEventBus → CloudEventPublisher
6. CloudEventPublisher → event-player service ✅
