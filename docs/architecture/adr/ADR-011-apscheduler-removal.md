# ADR-011: Removal of APScheduler and Migration to Controller-Based Job Execution

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-01-19 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-001](./ADR-001-api-centric-state-management.md), [ADR-010](./ADR-010-service-unification-neuroglia.md) |

## Context

The control-plane-api originally used APScheduler for background job execution:

| Job | Purpose | APScheduler Pattern |
|-----|---------|---------------------|
| `AutoImportWorkersJob` | Discover EC2 instances | Recurrent (interval-based) |
| `WorkerMetricsCollectionJob` | Collect worker metrics | Recurrent (interval-based) |
| `ActivityDetectionJob` | Detect idle workers | Recurrent (interval-based) |
| `LabsRefreshJob` | Sync lab records | Recurrent (interval-based) |
| `LicenseRegistrationJob` | Register CML licenses | Scheduled (on-demand) |
| `LicenseDeregistrationJob` | Deregister licenses | Scheduled (on-demand) |
| `OnDemandWorkerDataRefreshJob` | Refresh single worker | Scheduled (on-demand) |

With the refactoring to declarative resource management (ADR-010), controllers now use reconciliation loops (HostedService pattern) for continuous operations:

- **worker-controller**: `WorkerReconciler` (includes discovery loop per AD-020)
- **lablet-controller**: `LabletReconciler`, `LabsRefreshService`

This creates architectural tension:

1. **Dual scheduling systems**: APScheduler in control-plane-api + HostedService in controllers
2. **Violation of ADR-001**: APScheduler jobs access repositories directly
3. **Complexity**: `background_worker.py` process runs separately from main API
4. **Redundancy**: Controller reconcilers now handle what APScheduler jobs did

## Decision

**Remove APScheduler from control-plane-api entirely.** All background operations are handled by:

1. **Reconciliation loops in controllers** (worker-controller, lablet-controller)
2. **On-demand mediator commands** triggered by API requests

### Migration Strategy

| Original Job | Migration Target | Trigger |
|--------------|------------------|---------|
| `AutoImportWorkersJob` | `WorkerReconciler._run_discovery_loop()` (worker-controller) | Leader-elected asyncio task |
| `WorkerMetricsCollectionJob` | `WorkerReconciler._collect_and_report_metrics()` | Reconciliation loop |
| `ActivityDetectionJob` | `WorkerReconciler._detect_activity()` | Reconciliation loop |
| `LabsRefreshJob` | `LabsRefreshService` (lablet-controller) | Continuous (interval-based HostedService) |
| `LicenseRegistrationJob` | `RegisterWorkerLicenseCommand` | On-demand via API |
| `LicenseDeregistrationJob` | `DeregisterWorkerLicenseCommand` | On-demand via API |
| `OnDemandWorkerDataRefreshJob` | `RefreshWorkerDataCommand` → worker-controller | On-demand via API |

### On-Demand Pattern

For user-triggered operations (license registration, data refresh):

```
User → POST /api/workers/{id}/register-license
     → RegisterWorkerLicenseCommand (mediator)
     → Handler calls worker-controller via ControlPlaneApiClient
     → Worker-controller executes license operation
     → Reports result to control-plane-api via internal API
     → Control-plane-api persists state and broadcasts SSE
```

## Rationale

### Benefits

1. **Single scheduling paradigm**: All continuous operations use HostedService reconciliation
2. **ADR-001 compliance**: Controllers never access repositories directly
3. **Simplified deployment**: No separate `background_worker.py` process
4. **Better observability**: All operations flow through reconcilers with consistent logging/tracing
5. **Cleaner codebase**: Remove ~900 lines of APScheduler infrastructure

### Trade-offs

- On-demand operations require API round-trip through controller
- Controllers must handle both reconciliation and on-demand requests

## Consequences

### Files to Delete

| File | Reason |
|------|--------|
| `control-plane-api/background_worker.py` | APScheduler process entry point |
| `control-plane-api/application/services/background_scheduler.py` | APScheduler wrapper (~900 lines) |
| `control-plane-api/application/jobs/auto_import_workers_job.py` | Replaced by WorkerReconciler._run_discovery_loop() |
| `control-plane-api/application/jobs/worker_metrics_collection_job.py` | Replaced by WorkerReconciler |
| `control-plane-api/application/jobs/activity_detection_job.py` | Replaced by WorkerReconciler |
| `control-plane-api/application/jobs/labs_refresh_job.py` | Replaced by LabsRefreshService |
| `control-plane-api/application/jobs/license_registration_job.py` | Replaced by command |
| `control-plane-api/application/jobs/license_deregistration_job.py` | Replaced by command |
| `control-plane-api/application/jobs/on_demand_worker_data_refresh_job.py` | Replaced by command |
| `control-plane-api/application/jobs/__init__.py` | Empty module |

### Code Changes Required

1. **control-plane-api/main.py**: Remove `BackgroundTaskScheduler.configure()` call
2. **control-plane-api/pyproject.toml**: Remove `apscheduler` dependency
3. **docker-compose.yml**: Remove `background-worker` service if present
4. **Create new commands**: `RegisterWorkerLicenseCommand`, `DeregisterWorkerLicenseCommand`, `RefreshWorkerDataCommand`

### New Commands in control-plane-api

| Command | Purpose | Delegates To |
|---------|---------|--------------|
| `RegisterWorkerLicenseCommand` | Initiate license registration | worker-controller |
| `DeregisterWorkerLicenseCommand` | Initiate license deregistration | worker-controller |
| `RefreshWorkerDataCommand` | Trigger on-demand data refresh | worker-controller |

### New Endpoints in worker-controller

| Endpoint | Purpose |
|----------|---------|
| `POST /internal/workers/{id}/register-license` | Execute license registration |
| `POST /internal/workers/{id}/deregister-license` | Execute license deregistration |
| `POST /internal/workers/{id}/refresh-data` | Execute data refresh |

## Implementation Phases

### Phase 1: Create New Commands (control-plane-api)

- [ ] Create `RegisterWorkerLicenseCommand` and handler
- [ ] Create `DeregisterWorkerLicenseCommand` and handler
- [ ] Create `RefreshWorkerDataCommand` and handler
- [ ] Update API endpoints to use new commands

### Phase 2: Create New Endpoints (worker-controller)

- [ ] Add `POST /internal/workers/{id}/register-license`
- [ ] Add `POST /internal/workers/{id}/deregister-license`
- [ ] Add `POST /internal/workers/{id}/refresh-data`
- [ ] Implement license registration via CML System API
- [ ] Implement data refresh via EC2 + CloudWatch + CML APIs

### Phase 3: Verify Migration (Integration Testing)

- [ ] Test license registration flow end-to-end
- [ ] Test license deregistration flow end-to-end
- [ ] Test on-demand data refresh flow
- [ ] Verify SSE events are broadcast correctly

### Phase 4: Cleanup (After Verification)

- [ ] Delete deprecated files (listed above)
- [ ] Remove APScheduler dependency
- [ ] Update documentation
