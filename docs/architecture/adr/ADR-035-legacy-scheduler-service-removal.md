# ADR-035: Legacy SchedulerService Removal

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-04 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-002](./ADR-002-separate-resource-scheduler-service.md), [ADR-006](./ADR-006-resource-scheduler-ha-coordination.md), [ADR-011](./ADR-011-apscheduler-removal.md) |

## Context

The resource-scheduler originally contained a standalone `SchedulerService` class (`application/services/scheduler_service.py`, 365 lines) that implemented:

- Its own leader election loop via etcd
- Its own scheduling reconciliation loop
- Direct API calls for session assignment (`schedule_instance`, `allocate_ports`)
- Port allocation during scheduling (now deferred to lablet-controller pipeline)

After the lcm-core `WatchTriggeredHostedService` was introduced (following ADR-011's APScheduler removal), a new `SchedulerHostedService` was built that:

- Extends `WatchTriggeredHostedService` for dual-mode scheduling (watch + poll)
- Uses the shared `LeaderElectionConfig` for consistent HA across all controllers
- Integrates etcd real-time capacity data for accurate placement
- Uses `ReconciliationResult` for structured retry/requeue/fail outcomes
- Includes OTel metrics instrumentation at every decision point
- Defers port allocation to the lablet-controller pipeline (ADR-031 Phase 4)

The original `SchedulerService` was **never removed** after this migration. It remained as dead code:

- Not imported by `main.py` (not registered in DI)
- Not imported by any controller or hosted service
- Only referenced by its own test file (`test_scheduler_service.py`)
- Used outdated API client method names (`get_pending_instances`, `schedule_instance`, `allocate_ports`) that no longer match the `ControlPlaneApiClient` interface

Additionally, the test file (`test_scheduler_service.py`, 459 lines) tested the legacy class and used obsolete mock setups.

## Decision

**Remove `SchedulerService` and its test file.** Replace with tests for `SchedulerHostedService`.

### Files Removed

| File | Reason |
|------|--------|
| `application/services/scheduler_service.py` | Superseded by `SchedulerHostedService` |
| `tests/unit/application/services/test_scheduler_service.py` | Tests legacy class only |

### Files Updated

| File | Change |
|------|--------|
| `README.md` | Updated to reference `SchedulerHostedService` |
| `docs/architecture/components/resource-scheduler/index.md` | Rewritten to v2.0.0 reflecting actual implementation |

### New Test Files

| File | Coverage |
|------|----------|
| `tests/unit/application/services/test_scheduler_hosted_service.py` | `SchedulerHostedService.reconcile()` flow |
| `tests/unit/application/services/test_cleanup_hosted_service.py` | `CleanupHostedService` lifecycle |
| `tests/unit/api/test_admin_controller.py` | Admin endpoints |
| `tests/unit/api/test_scheduling_controller.py` | Dry-run preview endpoint |

## Rationale

### Why Remove (Not Refactor)?

1. **Complete supersession**: `SchedulerHostedService` covers 100% of `SchedulerService` functionality and adds watch-mode, etcd capacity, retries, and metrics
2. **API drift**: The legacy service uses method names that no longer exist on `ControlPlaneApiClient`
3. **Maintenance burden**: Two scheduling implementations create confusion about which is canonical
4. **Test rot**: The legacy tests pass in isolation but test code paths that never execute in production

### Why Not Keep as Fallback?

- The legacy service uses `SchedulerService.start_async()` which creates its own asyncio tasks, conflicting with Neuroglia's `HostedService` lifecycle management
- Port allocation in the legacy service (allocating specific ports during scheduling) contradicts ADR-031/032 which defers port allocation to the lablet-controller pipeline

## Consequences

### Positive

- **Single source of truth**: One scheduling implementation (`SchedulerHostedService`)
- **Reduced code surface**: ~825 lines removed (365 service + 459 tests)
- **Documentation accuracy**: Architecture docs now match implementation
- **Test relevance**: All tests exercise production code paths

### Negative

- Loss of a simpler reference implementation (mitigated by architecture docs)

## Implementation Notes

The `application/services/` directory retains `placement_engine.py` which is actively used by both `SchedulerHostedService` and `SchedulingController`.
