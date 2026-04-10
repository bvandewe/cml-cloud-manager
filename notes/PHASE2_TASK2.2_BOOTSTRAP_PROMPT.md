# Phase 2 Task 2.2: Scheduler Service Core - Bootstrap Prompt

**Use this prompt to start a new AI coding session for implementing Task 2.2**

---

## Session Bootstrap Prompt

```
I'm continuing work on the Lablet Cloud Manager project, implementing Phase 2 Task 2.2: Scheduler Service Core.

Please start by recalling the session context:
- Workspace ID: lablet-cloud-manager
- Focus hint: "Phase 2 Task 2.2 Scheduler Service Core reconciliation loop placement engine"

## Task Overview

Implement the SchedulerService with reconciliation loop for the resource-scheduler microservice.

### Acceptance Criteria

- [ ] SchedulerService with reconciliation loop (30s default)
- [ ] Watch for PENDING instances via etcd
- [ ] Delegate placement decisions to PlacementEngine
- [ ] Call Control Plane API for state transitions
- [ ] Only run loop when leader
- [ ] Comprehensive unit tests with mocks

### Files to Create/Modify

**Create:**
- `src/resource-scheduler/application/services/placement_engine.py`
- `tests/unit/application/services/test_scheduler_service.py`
- `tests/unit/application/services/test_placement_engine.py`

**Modify:**
- `src/resource-scheduler/application/services/scheduler_service.py` (complete the _reconcile() method)

### Dependencies (Already Implemented)

- Task 2.1 Leader Election: Basic leader election already in scheduler_service.py
- EtcdStateStore: `src/resource-scheduler/integration/services/etcd_client.py`
- ControlPlaneApiClient: `src/resource-scheduler/integration/services/control_plane_client.py`
- Settings: `src/resource-scheduler/application/settings.py`

### Key Reference Files to Read

1. **Current scheduler implementation:**
   - `src/resource-scheduler/application/services/scheduler_service.py` (lines 1-158)
   - `src/resource-scheduler/main.py` (lines 1-102)

2. **Control Plane domain models (for understanding what we're scheduling):**
   - `src/control-plane-api/domain/entities/lablet_instance.py` (LabletInstance aggregate)
   - `src/control-plane-api/domain/entities/cml_worker.py` (CMLWorker aggregate)
   - `src/control-plane-api/domain/entities/lablet_definition.py` (resource requirements)
   - `src/control-plane-api/domain/enums.py` (LabletInstanceStatus states)

3. **Integration clients:**
   - `src/resource-scheduler/integration/services/control_plane_client.py`
   - `src/resource-scheduler/integration/services/etcd_client.py`

4. **Implementation plan:**
   - `docs/implementation/phase-2-scheduling.md`

## Implementation Details

### PlacementEngine Requirements

```python
@dataclass
class SchedulingDecision:
    action: Literal["assign", "scale_up", "wait"]
    worker_id: str | None = None
    worker_template: str | None = None
    reason: str = ""


class PlacementEngine:
    """Placement algorithm for LabletInstances."""

    def schedule(
        self,
        instance: dict,  # Instance data from Control Plane API
        definition: dict,  # Definition data from Control Plane API
        workers: list[dict]  # Available workers from Control Plane API
    ) -> SchedulingDecision:
        # Phase 1: Filter eligible workers
        # - License affinity (license_type matches)
        # - Resource requirements (cpu, memory, storage)
        # - AMI requirements (ami_name, node_definitions)
        # - Available capacity (not exceeding max_labs)
        # - Available ports (enough for port_template)
        # - Exclude DRAINING workers

        # Phase 2: Score candidates (bin-packing)
        # - Prefer workers with higher utilization (fill workers)
        # - Consider remaining capacity as tiebreaker

        # Phase 3: Return decision
        # - assign: worker_id selected
        # - scale_up: no suitable worker, return template name
        # - wait: temporary condition, retry later
```

### Scheduler Reconciliation Loop

The `_reconcile()` method in SchedulerService should:

1. **Get PENDING instances** from Control Plane API
2. **Get SCHEDULED instances** approaching timeslot (for future Task 2.4)
3. **For each PENDING instance:**
   a. Fetch the LabletDefinition
   b. Get available workers
   c. Run PlacementEngine.schedule()
   d. If "assign": Call schedule_instance() API, then allocate_ports()
   e. If "scale_up": Log/emit event (actual scaling in Phase 3)
   f. If "wait": Skip, retry next cycle

### Testing Requirements

- Unit tests with mocked etcd and Control Plane API
- Test scenarios:
  - No PENDING instances (no-op)
  - Single PENDING instance, single suitable worker
  - Multiple PENDING instances, multiple workers (bin-packing)
  - No suitable workers (scale_up decision)
  - Placement failure handling
  - Only runs when leader

## Additional Context

- The resource-scheduler is a standalone Python service (not using Neuroglia/FastAPI)
- It uses plain asyncio with httpx for HTTP calls
- Settings use dataclass with os.getenv (no Pydantic)
- Leader election uses etcd leases with 15s TTL
- Reconcile interval is 30s by default

## Questions to Consider Before Implementing

1. Should PlacementEngine fetch definition/workers or receive them as parameters?
2. How to handle partial failures (instance scheduled but port allocation fails)?
3. Should we batch API calls (get all pending + definitions) or fetch per-instance?
4. What metrics/logs should be emitted during scheduling?
```

---

## Quick Context Lookup

### Directory Structure

```
src/resource-scheduler/
├── application/
│   ├── commands/          # CQRS commands (if any)
│   ├── dtos/              # Data transfer objects
│   ├── queries/           # CQRS queries (if any)
│   ├── services/
│   │   └── scheduler_service.py  # MODIFY - add reconciliation
│   └── settings.py        # Settings dataclass
├── domain/
│   ├── entities/          # Domain entities (currently empty)
│   ├── events/            # Domain events (if any)
│   └── repositories/      # Repository interfaces
├── integration/
│   ├── repositories/      # Repository implementations
│   └── services/
│       ├── control_plane_client.py  # HTTP client for Control Plane API
│       └── etcd_client.py           # etcd state store client
├── main.py               # Application entry point
└── tests/                # Test directory
```

### Key API Endpoints (Control Plane API)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/v1/instances?state=PENDING` | Get pending instances |
| GET | `/api/v1/instances?state=SCHEDULED` | Get scheduled instances |
| GET | `/api/v1/workers?status=RUNNING` | Get active workers |
| GET | `/api/v1/definitions/{id}` | Get lablet definition |
| POST | `/api/internal/instances/{id}/schedule` | Assign worker to instance |
| POST | `/api/internal/instances/{id}/allocate-ports` | Allocate ports |
| POST | `/api/internal/instances/{id}/transition` | Transition state |

### Instance States (LabletInstanceStatus)

```
PENDING → SCHEDULED → INSTANTIATING → RUNNING → STOPPING → STOPPED → TERMINATED
                                    ↓
                                 GRADING → GRADED → COLLECTING → ARCHIVED
```

---

## Session Workflow Reminder

1. **Recall session** with workspace_id and focus_hint
2. **Read key reference files** listed above
3. **Ask clarifying questions** if needed
4. **Implement PlacementEngine** first (stateless, testable)
5. **Complete scheduler_service.py** _reconcile() method
6. **Write unit tests** with mocks
7. **Store decisions/insights** discovered
8. **Update task status** as you complete

---

*Generated: 2026-01-16*
*Phase: 2 - Scheduling*
*Task: 2.2 - Scheduler Service Core*
*Estimated Effort: 3 days*
