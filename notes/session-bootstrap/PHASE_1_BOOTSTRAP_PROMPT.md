# Phase 1 Bootstrap Prompt

**Purpose:** Context primer for AI agent to begin Phase 1 (Foundation) implementation.

---

## Session Start Instructions

Copy this prompt to start a new coding session for Phase 1:

---

### BOOTSTRAP PROMPT

```markdown
## Context

I'm implementing Phase 1 (Foundation) of the Lablet Cloud Manager multi-service architecture refactoring.

**Project:** Lablet Cloud Manager
**Workspace ID:** lablet-cloud-manager
**Focus Hint:** "Phase 1 foundation domain models control-plane-api"

### Architecture Summary (AD-7: Controller Domain Separation)

Four microservices with dual storage (etcd + MongoDB):

| Service | Port | Domain | SPI |
|---------|------|--------|-----|
| control-plane-api | 8020 | Single writer to MongoDB | N/A |
| resource-scheduler | 8081 | Scheduling & matching | N/A |
| lablet-controller | 8082 | Application Layer (Workloads) | CML Labs API |
| worker-controller | 8083 | Infrastructure Layer (Compute) | AWS EC2 + CloudWatch + CML System API |

**Reconciliation Pattern (both controllers):**
```

SPEC (from MongoDB) ←→ OBSERVE (actual state) → ACT (reconcile)

```

### Key Documents

1. **Architecture:** `docs/architecture/lablet-resource-manager-architecture.md`
2. **Phase 1 Tasks:** `docs/implementation/phase-1-foundation.md`
3. **Domain Patterns:** `src/domain/entities/cml_worker.py` (reference for aggregates)
4. **Repository Pattern:** `src/integration/repositories/mongo_cml_worker_repository.py`

### Phase 1 Deliverables (Week 1-4)

**Week 1: LabletDefinition Aggregate**
- Task 1.1: `src/domain/entities/lablet_definition.py`
- Task 1.2: `src/integration/repositories/mongo_lablet_definition_repository.py`

**Week 2: LabletInstance Aggregate + CMLWorker Extensions**
- Task 1.3: `src/domain/entities/lablet_instance.py`
- Task 1.4: `src/integration/repositories/mongo_lablet_instance_repository.py`
- Task 1.5: Extend `src/domain/entities/cml_worker.py` with capacity tracking

**Week 3: etcd Integration & Services**
- Task 1.6: `src/integration/services/etcd_client.py`
- Task 1.7: `src/application/services/port_allocation_service.py`
- Task 1.8: `src/domain/entities/worker_template.py`

**Week 4: CRUD APIs & Tests**
- Task 1.9-1.12: Controllers, queries, commands for definitions and instances

### Starting Point

Begin with **Task 1.1: LabletDefinition Aggregate**

Files to create:
- `src/domain/entities/lablet_definition.py`
- `src/domain/events/lablet_definition_events.py`
- `src/domain/value_objects/resource_requirements.py`
- `src/domain/value_objects/port_template.py`
- `src/domain/enums/license_type.py`

Reference patterns from:
- `src/domain/entities/cml_worker.py` (AggregateRoot with @dispatch)
- `src/domain/entities/lab_record.py` (simpler entity pattern)

### Request

Please:
1. Recall session context via Knowledge Manager
2. Set focus to "Phase 1 Task 1.1 LabletDefinition Aggregate"
3. Review the architecture doc and existing domain patterns
4. Implement Task 1.1 following existing patterns exactly
5. Include unit tests with ≥90% coverage
```

---

## Reference Links

- [Architecture Documentation](../docs/architecture/lablet-resource-manager-architecture.md)
- [Phase 1 Implementation Plan](../docs/implementation/phase-1-foundation.md)
- [Multi-Service Architecture Refactoring](./MULTI_SERVICE_ARCHITECTURE_REFACTORING.md)

## Key Decisions Made (Pre-Phase 1)

| Decision | Description |
|----------|-------------|
| AD-7 | Controller Domain Separation: Lablet Controller = Application Layer, Worker Controller = Infrastructure Layer |
| ADR-001 | All mutations go through Control Plane API |
| Reconciliation | Both controllers use SPEC ←→ OBSERVE → ACT pattern |

## Scaffold Status (Ready for Phase 1)

| Service | Scaffold | Status |
|---------|----------|--------|
| control-plane-api | `src/control-plane-api/` | ✅ Ready (main codebase) |
| resource-scheduler | `src/resource-scheduler/` | ✅ Scaffold complete |
| lablet-controller | `src/lablet-controller/` | ✅ Fixed - Uses CML Labs SPI |
| worker-controller | `src/worker-controller/` | ✅ Fixed - Uses AWS EC2 + CloudWatch + CML System API |

## Files Updated in Preparation Session

1. `docs/implementation/phase-3-autoscaling.md` - Renamed to Worker Controller domain
2. `src/lablet-controller/main.py` - Updated to use CmlLabsSpiClient
3. `src/lablet-controller/application/services/lablet_controller_service.py` - Replaced cloud provider ops with CML Labs SPI ops
4. `src/worker-controller/main.py` - Added AWS EC2, CloudWatch, CML System clients
5. `src/worker-controller/application/services/worker_controller_service.py` - Added full reconciliation loop
