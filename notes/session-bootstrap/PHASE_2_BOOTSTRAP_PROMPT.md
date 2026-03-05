# Phase 2 Bootstrap Prompt

**Purpose:** Context primer for AI agent to begin Phase 2 (Scheduling) implementation.
**Created:** 2026-01-16
**Phase 1 Status:** ✅ COMPLETE (445 tests passing)

---

## Session Start Instructions

Copy this prompt to start a new coding session for Phase 2:

---

### BOOTSTRAP PROMPT

```markdown
## Context

I'm implementing Phase 2 (Scheduling) of the Lablet Cloud Manager multi-service architecture.

**Project:** Lablet Cloud Manager
**Workspace ID:** lablet-cloud-manager
**Focus Hint:** "Phase 2 scheduling leader election scheduler service"

### Phase 1 Completion Status ✅

All Phase 1 tasks completed with 445 tests passing:

| Task | Description | Status |
|------|-------------|--------|
| 1.1 | LabletDefinition Aggregate | ✅ Complete |
| 1.2 | LabletDefinition Repository | ✅ Complete |
| 1.3 | LabletInstance Aggregate | ✅ Complete |
| 1.4 | LabletInstance Repository | ✅ Complete |
| 1.5 | CMLWorker Extensions | ✅ Complete |
| 1.6 | etcd Client | ✅ Complete |
| 1.7 | Port Allocation Service | ✅ Complete |
| 1.8 | WorkerTemplate Service | ✅ Complete (50 tests) |
| 1.9 | LabletDefinition CRUD | ✅ Complete |
| 1.10 | LabletInstance CRUD | ✅ Complete (22 tests) |
| 1.11 | REST API Controllers | ✅ Complete (15 tests) |

### Architecture Summary

Four microservices with dual storage (etcd + MongoDB) plus a shared core package:

| Component | Port | Description |
|-----------|------|-------------|
| control-plane-api | 8020 | Single writer to MongoDB/etcd |
| resource-scheduler | 8081 | Scheduling & placement decisions |
| lablet-controller | 8082 | Application Layer (CML Labs SPI) |
| worker-controller | 8083 | Infrastructure Layer (AWS EC2 + CloudWatch + CML System API) |
| **lcm-core** | N/A | Shared domain models, enums, API client (see ADR-009) |

### Key Documents

1. **Phase 2 Tasks:** `docs/implementation/phase-2-scheduling.md`
2. **Architecture:** `docs/architecture/lablet-resource-manager-architecture.md`
3. **Phase 1 Reference:** `docs/implementation/phase-1-foundation.md`
4. **Core Package:** `src/core/README.md` - Shared lcm-core package (ADR-009)
5. **Phase 3.5:** `docs/implementation/phase-3.5-runtime-jobs-migration.md` - Runtime job migration

### Phase 1 Assets Available for Phase 2

**Domain Entities (use as reference patterns):**
- `src/control-plane-api/domain/entities/lablet_definition.py` - LabletDefinition aggregate
- `src/control-plane-api/domain/entities/lablet_instance.py` - LabletInstance aggregate with state machine
- `src/control-plane-api/domain/enums/lablet_instance_state.py` - State enum: PENDING → SCHEDULED → INSTANTIATING → RUNNING → TERMINATING → TERMINATED

**Key Services (dependencies for Phase 2):**
- `src/control-plane-api/integration/services/etcd_client.py` - EtcdClient for key-value operations
- `src/control-plane-api/integration/services/etcd_state_store.py` - EtcdStateStore with leader election methods
- `src/control-plane-api/application/services/port_allocation_service.py` - PortAllocationService for port management
- `src/control-plane-api/application/services/worker_template_service.py` - WorkerTemplateService for worker matching

**Repositories:**
- `src/control-plane-api/integration/repositories/motor_lablet_definition_repository.py`
- `src/control-plane-api/integration/repositories/motor_lablet_instance_repository.py`

**CQRS Pattern (self-contained command/query files):**
- `src/control-plane-api/application/commands/lablet_instance/create_lablet_instance_command.py`
- `src/control-plane-api/application/commands/lablet_instance/terminate_lablet_instance_command.py`
- `src/control-plane-api/application/queries/get_lablet_instance_query.py`
- `src/control-plane-api/application/queries/list_lablet_instances_query.py`

### Phase 2 Deliverables (Week 5-8)

**Week 5: Scheduler Service Foundation**
- Task 2.1: Leader Election Service (etcd leases, 15s TTL)
- Task 2.2: Scheduler Service Core (reconciliation loop, PENDING instance processing)

**Week 6: Placement Algorithm & Timeslot Management**
- Task 2.3: Placement Engine (bin-packing algorithm, worker filtering)
- Task 2.4: Timeslot Manager (lead time calculation: 35 min = 20 min boot + 15 min instantiation)
- Task 2.5: Internal Scheduler Endpoints

**Week 7: Lab YAML Rewriting & Instantiation**
- Task 2.6: Artifact Storage Service (S3/MinIO)
- Task 2.7: Lab YAML Rewriting Service (ruamel-yaml, port placeholder replacement)
- Task 2.8: Instantiation Service (download → rewrite → import → start)

**Week 8: SSE Updates & Integration Testing**
- Task 2.9: SSE Instance State Updates
- Task 2.10: Scheduler Integration Tests
- Task 2.11: Scheduler Background Job Registration

### Starting Point

Begin with **Task 2.1: Leader Election Service**

Files to create:
- `src/control-plane-api/application/services/leader_election_service.py`
- `tests/integration/test_leader_election.py`

Reference existing patterns from:
- `src/control-plane-api/integration/services/etcd_state_store.py` - Has `try_acquire_leadership()` method already
- `src/control-plane-api/application/services/background_scheduler.py` - BackgroundTaskScheduler pattern

### etcd Leader Election (Already Implemented in Phase 1)

The `EtcdStateStore` class already has leader election primitives:

```python
# From etcd_state_store.py
async def try_acquire_leadership(
    self,
    service_name: str,
    instance_id: str,
    ttl: int = 10
) -> tuple[bool, EtcdLease | None]:
    """Try to acquire leadership for a service."""

async def release_leadership(
    self,
    service_name: str,
    lease: EtcdLease | None = None
) -> bool:
    """Release leadership for a service."""

async def get_current_leader(self, service_name: str) -> str | None:
    """Get the current leader for a service."""
```

### CRITICAL Neuroglia Framework Patterns

**Handler Helper Methods (DO NOT use OperationResult.success/fail):**

```python
# ✅ CORRECT - Use inherited helper methods
return self.ok(data)           # 200
return self.created(data)       # 201
return self.not_found(EntityType, id)  # 404 - MUST pass type, not string!
return self.bad_request(message) # 400
return self.conflict(message)   # 409

# ❌ WRONG - These don't exist
return OperationResult.success(data)
return OperationResult.fail(message)
```

**Mediator Calls (single argument only):**

```python
# ✅ CORRECT
result = await self.mediator.execute_async(GetLabletInstanceQuery(id="..."))

# ❌ WRONG - No cancellation_token to mediator
result = await self.mediator.execute_async(query, cancellation_token)
```

**Result Checking:**

```python
# ✅ CORRECT
if result.is_success:
    data = result.data

# ❌ WRONG - These don't exist
if result.is_successful:
    content = result.content
```

### Test Configuration

**MongoDB:** `mongodb://root:password123@localhost:8032/?authSource=admin`
**etcd:** `localhost:2379`

Run tests with:

```bash
cd src/control-plane-api && source .venv/bin/activate && PYTHONPATH=. pytest tests/ -v
```

### Request

Please:

1. Recall session context via Knowledge Manager
2. Set focus to "Phase 2 Task 2.1 Leader Election Service"
3. Review the existing etcd_state_store.py implementation
4. Implement Task 2.1 following existing patterns exactly
5. Include integration tests with ≥85% coverage

```

---

## Reference Links

- [Phase 2 Implementation Plan](../docs/implementation/phase-2-scheduling.md)
- [Architecture Documentation](../docs/architecture/lablet-resource-manager-architecture.md)
- [Phase 1 Reference](../docs/implementation/phase-1-foundation.md)

## Phase 1 Completion Summary

| Metric | Value |
|--------|-------|
| Total Tests | 445 |
| Passed | 445 |
| Failed | 0 (1 branding housekeeping issue excluded) |
| Coverage Target | ≥85% achieved |

## Key Phase 1 Decisions to Carry Forward

| Decision | Description |
|----------|-------------|
| AD-7 | Controller Domain Separation: Lablet Controller = Application Layer |
| Self-contained CQRS | Command/Query + Handler in same file |
| not_found() Gotcha | Must pass entity TYPE, not string |
| etcd Leader Election | Already implemented in EtcdStateStore |

## Phase 2 Task Dependencies

```

Week 5                  Week 6                  Week 7                  Week 8
┌─────────┐            ┌─────────┐            ┌─────────┐            ┌─────────┐
│ Task 2.1│──────────▶│ Task 2.3│            │ Task 2.6│──────────▶│ Task 2.9│
│ Leader  │            │ Placement│            │ Artifact│            │ SSE     │
│ Election│            │ Engine   │            │ Storage │            │ Updates │
└────┬────┘            └────┬────┘            └────┬────┘            └─────────┘
     │                      │                      │                      │
     ▼                      │                      ▼                      │
┌─────────┐            ┌────┴────┐            ┌─────────┐            ┌─────────┐
│ Task 2.2│──────────▶│ Task 2.4│            │ Task 2.7│            │Task 2.10│
│Scheduler│            │ Timeslot│            │ YAML    │            │ Integ   │
│ Service │            │ Manager │            │ Rewrite │            │ Tests   │
└────┬────┘            └────┬────┘            └────┬────┘            └────┬────┘
     │                      │                      │                      │
     │                      ▼                      ▼                      │
     │                 ┌─────────┐            ┌─────────┐            ┌────┴────┐
     │                 │ Task 2.5│◀───────────│ Task 2.8│            │Task 2.11│
     └────────────────▶│ Internal│            │ Instant-│            │ Startup │
                       │ Endpoints            │ iation  │            │ Job     │
                       └─────────┘            └─────────┘            └─────────┘

```

## Files Created in Phase 1 (Reference for Patterns)

### Domain Layer
- `src/control-plane-api/domain/entities/lablet_definition.py`
- `src/control-plane-api/domain/entities/lablet_instance.py`
- `src/control-plane-api/domain/entities/worker_template.py`
- `src/control-plane-api/domain/enums/lablet_instance_state.py`
- `src/control-plane-api/domain/enums/license_type.py`
- `src/control-plane-api/domain/value_objects/resource_requirements.py`
- `src/control-plane-api/domain/value_objects/port_template.py`

### Application Layer
- `src/control-plane-api/application/commands/lablet_definition/*.py`
- `src/control-plane-api/application/commands/lablet_instance/*.py`
- `src/control-plane-api/application/queries/get_lablet_definition_query.py`
- `src/control-plane-api/application/queries/list_lablet_definitions_query.py`
- `src/control-plane-api/application/queries/get_lablet_instance_query.py`
- `src/control-plane-api/application/queries/list_lablet_instances_query.py`
- `src/control-plane-api/application/dtos/lablet_definition_dto.py`
- `src/control-plane-api/application/dtos/lablet_instance_dto.py`
- `src/control-plane-api/application/services/port_allocation_service.py`
- `src/control-plane-api/application/services/worker_template_service.py`

### Integration Layer
- `src/control-plane-api/integration/services/etcd_client.py`
- `src/control-plane-api/integration/services/etcd_state_store.py`
- `src/control-plane-api/integration/repositories/motor_lablet_definition_repository.py`
- `src/control-plane-api/integration/repositories/motor_lablet_instance_repository.py`

### API Layer
- `src/control-plane-api/api/controllers/lablet_definitions_controller.py`
- `src/control-plane-api/api/controllers/lablet_instances_controller.py`

### Tests (99 integration + 346 unit = 445 total)
- `tests/integration/test_etcd_client.py`
- `tests/integration/test_mongo_lablet_definition_repository.py`
- `tests/integration/test_mongo_lablet_instance_repository.py`
- `tests/integration/test_lablet_controllers.py`
- `tests/application/test_port_allocation_service.py`
- `tests/application/test_worker_template_service.py`
- `tests/application/test_lablet_definition_crud.py`
- `tests/application/test_lablet_instance_crud.py`
