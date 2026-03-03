# ADR-015: Control Plane API Must Not Make External Calls

- **Status**: Implemented ✅
- **Date**: 2026-02-06 (Expanded: 2026-02-06, Completed: 2026-02-07)
- **Deciders**: Platform Team
- **Related**: ADR-001 (API-Centric State Management), ADR-005 (Dual State Store), ADR-014 (Worker Orphan Detection), ADR-016 (License Operations), ADR-017 (Lab Operations)

## Context

The control-plane-api service was originally designed as both a state store AND an orchestration layer, making direct calls to:

- **AWS EC2** - Instance lifecycle (create, start, stop, terminate)
- **AWS CloudWatch** - Metrics collection (CPU, memory, storage)
- **CML REST API** - Health checks, license management, lab operations

This created several problems:

1. **Architectural Violation**: Control-plane-api's purpose is state management (per ADR-001), not infrastructure orchestration
2. **Credential Sprawl**: AWS and CML credentials needed in multiple services
3. **Inconsistent Behavior**: External operations could be triggered from multiple paths
4. **Testing Complexity**: Mocking AWS/CML in multiple services
5. **Orphan Detection Failure**: Commands couldn't update state when external resources were gone
6. **Tight Coupling**: Control-plane-api knowledge of EC2/CML implementation details

## Decision

**Control-plane-api MUST NOT make any external API calls.**

It ONLY:

1. Reads/writes to **MongoDB** (spec/desired state, document storage)
2. Reads/writes to **etcd** (state for controller watching, per ADR-005)
3. Exposes **REST API** for UI and internal controller services

All external integrations are delegated to specialized controllers.

### Responsibility Boundaries

| Service | Responsibility | External Calls | Watches |
|---------|----------------|----------------|---------|
| **control-plane-api** | State storage (MongoDB + etcd), API for UI & controllers | **NONE** | N/A |
| **worker-controller** | AWS EC2 lifecycle, CloudWatch metrics, orphan detection | AWS EC2, CloudWatch | etcd |
| **lablet-controller** | CML API interactions, lab lifecycle, CML health/metrics | CML REST API | etcd |
| **resource-scheduler** | Resource allocation, scheduling algorithms | **NONE** | etcd |

### Data Flow Pattern

```
                    ┌─────────────────────────────────────────┐
                    │                   UI                     │
                    └────────────────────┬────────────────────┘
                                         │ REST API
                                         ▼
                    ┌─────────────────────────────────────────┐
                    │           control-plane-api              │
                    │  (DB-only: MongoDB + etcd writes)        │
                    └──────┬─────────────────────┬─────────────┘
                           │                     │
              MongoDB ◄────┘                     └────► etcd
              (specs)                                   (state)
                                                          │
                         ┌────────────────┬───────────────┼───────────────┐
                         │                │               │               │
                    watch│           watch│          watch│          watch│
                         ▼                ▼               ▼               ▼
              ┌──────────────────┐ ┌──────────────┐ ┌──────────────┐
              │ worker-controller│ │lablet-controller│ │resource-scheduler│
              └────────┬─────────┘ └──────┬───────┘ └──────────────┘
                       │                  │
                       ▼                  ▼
                   AWS EC2            CML API
                   CloudWatch
```

### Spec vs State Pattern (Kubernetes-like Reconciliation)

| Field | Description | Written By | Read By |
|-------|-------------|------------|---------|
| `desired_status` | Spec: What user wants | control-plane-api | Controllers (via etcd watch) |
| `status` | State: Actual resource state | Controllers (via internal API) | UI, control-plane-api |

**Flow:**

1. User clicks "Stop Worker" in UI
2. control-plane-api sets `desired_status=STOPPED` in MongoDB AND etcd
3. worker-controller watches etcd, sees `desired_status != status`
4. worker-controller calls AWS EC2 to stop instance
5. worker-controller updates `status=STOPPED` via control-plane-api internal API
6. UI sees reconciled state

### Commands/Queries to Remove or Refactor

#### DELETE (Obsolete - functionality moved to controllers)

| File | Reason |
|------|--------|
| `sync_worker_ec2_status_command.py` | EC2 → worker-controller |
| `bulk_sync_worker_ec2_status_command.py` | EC2 → worker-controller |
| `collect_worker_cloudwatch_metrics_command.py` | CloudWatch → worker-controller |
| `provision_cml_worker_event_handler.py` | EC2 provisioning → worker-controller |
| `sync_worker_cml_data_command.py` | CML API → lablet-controller |
| `bulk_sync_worker_cml_data_command.py` | CML API → lablet-controller |
| `refresh_worker_metrics_command.py` | Orchestrates deleted commands |
| `refresh_worker_labs_command.py` | CML API → lablet-controller |
| `request_worker_data_refresh_command.py` | Orchestrates deleted commands |

#### REFACTOR (Keep but remove external calls)

| File | Change |
|------|--------|
| `create_cml_worker_command.py` | DB-only: create with status=PENDING, desired_status=RUNNING |
| `start_cml_worker_command.py` | DB-only: set desired_status=RUNNING |
| `stop_cml_worker_command.py` | DB-only: set desired_status=STOPPED |
| `terminate_cml_worker_command.py` | DB-only: set desired_status=TERMINATED |
| `delete_cml_worker_command.py` | DB-only: set desired_status=TERMINATED (same as terminate) |
| `update_cml_worker_status_command.py` | DB-only: return current status from DB |
| `update_cml_worker_tags_command.py` | DB-only: store tags in MongoDB, worker-controller syncs to EC2 |
| `enable_worker_detailed_monitoring_command.py` | DB-only: store setting, worker-controller applies to EC2 |
| `import_cml_worker_command.py` | DB-only: store import request, worker-controller discovers from EC2 |
| `bulk_import_cml_workers_command.py` | DB-only: store import request, worker-controller discovers from EC2 |
| `register_cml_worker_license_command.py` | DB-only: store license info, lablet-controller registers with CML |
| `deregister_cml_worker_license_command.py` | DB-only: remove license info, lablet-controller deregisters |
| `get_cml_worker_resources_query.py` | DB-only: return cached metrics from MongoDB |

#### SERVICES TO REMOVE

| Service | Reason |
|---------|--------|
| `CMLHealthService` | CML API → lablet-controller |
| `AwsEc2Client` registration | EC2 → worker-controller |
| `CMLApiClient` registration | CML API → lablet-controller |

## Consequences

### Positive

1. **Clear Separation of Concerns**: control-plane-api is a pure state store
2. **Single Responsibility**: Each controller owns its external integration
3. **Simpler Testing**: control-plane-api tests need no AWS/CML mocks
4. **Reduced Credential Exposure**: AWS creds only in worker-controller, CML creds only in lablet-controller
5. **Consistent Behavior**: All external operations go through dedicated controllers
6. **Reactive Architecture**: Controllers watch etcd (per ADR-005) for efficient state sync

### Negative

1. **Migration Effort**: Significant refactoring of control-plane-api
2. **Controller Complexity**: Controllers must implement reconciliation loops
3. **Eventual Consistency**: UI sees desired_status immediately, status updates async

### Neutral

1. **Network Hops**: Controllers call internal API to update state (correct flow)
2. **etcd Dependency**: Controllers depend on etcd watch (already required by ADR-005)

## Implementation Checklist

### Phase 1: Core Lifecycle Commands ✅

- [x] Create `MarkWorkerTerminatedCommand` (database-only)
- [x] Refactor `StartCMLWorkerCommand` to set desired_status only
- [x] Refactor `StopCMLWorkerCommand` to set desired_status only
- [x] Refactor `TerminateCMLWorkerCommand` to set desired_status only
- [x] Refactor `CreateCMLWorkerCommand` to DB-only (no EC2 provisioning)
- [x] Add `desired_status` field to CMLWorkerState
- [x] Remove `SyncWorkerEC2StatusCommand`
- [x] Remove `BulkSyncWorkerEC2StatusCommand`
- [x] Remove `CollectWorkerCloudWatchMetricsCommand`

### Phase 2: Complete External Call Removal ✅

- [x] Remove `ProvisionCMLWorkerEventHandler` (EC2 provisioning)
- [x] Remove `SyncWorkerCMLDataCommand` (CML API)
- [x] Remove `BulkSyncWorkerCMLDataCommand` (CML API)
- [x] Remove `RefreshWorkerMetricsCommand` (orchestrates deleted commands)
- [x] Remove `RefreshWorkerLabsCommand` (CML API)
- [x] Remove `RequestWorkerDataRefreshCommand` (orchestrates deleted commands)
- [x] Refactor `DeleteCMLWorkerCommand` to DB-only
- [x] Refactor `UpdateCMLWorkerTagsCommand` to DB-only
- [x] Refactor `EnableWorkerDetailedMonitoringCommand` to DB-only
- [x] Remove `ImportCMLWorkerCommand` (no longer needed - workers created via CreateCMLWorkerCommand)
- [x] Remove `BulkImportCMLWorkersCommand` (no longer needed)
- [x] Refactor `RegisterCMLWorkerLicenseCommand` to DB-only (ADR-016: stores intent, worker-controller reconciles)
- [x] Refactor `DeregisterCMLWorkerLicenseCommand` to DB-only (ADR-016: stores intent, worker-controller reconciles)
- [x] Refactor `GetCMLWorkerResourcesQuery` to return cached DB data (returns `CachedResourcesUtilization` from worker state)

### Phase 2b: Lab Operations (ADR-017) ✅

- [x] Refactor `ControlLabCommand` to DB-only (ADR-017: sets pending_action, lablet-controller reconciles)
- [x] Refactor `DeleteLabCommand` to DB-only (ADR-017: sets pending_action=delete, lablet-controller reconciles)
- [x] Refactor `ImportLabCommand` to DB-only (ADR-017: stores YAML in PendingLabImport, lablet-controller reconciles)
- [x] Refactor `DownloadLabCommand` to BFF via lablet-controller (ADR-017: read-only passthrough via LabletControllerClient)

### Phase 3: Dependency Cleanup ✅

- [x] Remove `AwsEc2Client` registration from control-plane-api DI
- [x] Remove `CMLApiClient` registration from control-plane-api DI
- [x] Remove `CMLHealthService` from control-plane-api (already removed)
- [x] Remove AWS/CML integration imports from control-plane-api
- [x] Update `__init__.py` files to remove deleted exports

### Phase 4: Validate ADR-005 (etcd watch) ✅

- [x] Verify control-plane-api writes to etcd on desired_status changes (EtcdStateStore configured, set_instance_state/set_worker_state available)
- [x] Verify worker-controller watches etcd for worker state changes (WorkerReconciler watches /workers/ prefix)
- [x] Verify lablet-controller watches etcd for lab/license state changes (LabletReconciler watches /instances/ prefix)
- [x] Verify resource-scheduler watches etcd for scheduling triggers (uses leader election + polling pattern)

### Phase 5: etcd State Publishing for desired_status ✅

Implemented reactive reconciliation via etcd watch by publishing `desired_status` changes:

- [x] Add `WORKER_DESIRED_STATE_KEY` to EtcdStateStore (`/workers/{id}/desired_state`)
- [x] Add `set_worker_desired_state()` method to EtcdStateStore
- [x] Add `get_worker_desired_state()` method to EtcdStateStore
- [x] Update `delete_worker_state()` to also clean up `desired_state` key
- [x] Create `CMLWorkerDesiredStatusUpdatedEtcdProjector` domain event handler
- [x] Update `CMLWorkerCreatedEtcdProjector` to publish both `status` and `desired_status` on creation
- [x] Export new projector in `application/events/domain/__init__.py`
- [x] Add unit tests for etcd state projectors (`test_etcd_state_projectors.py`)
- [x] Update WorkerReconciler docstrings to document watch pattern

**etcd Key Structure:**

```
/lcm/workers/{worker_id}/state          # Actual EC2 state (updated by worker-controller)
/lcm/workers/{worker_id}/desired_state  # User-requested state (updated by control-plane-api)
```

**Flow:**

1. User clicks "Stop Worker" in UI
2. control-plane-api updates `desired_status=STOPPED` in MongoDB
3. Domain event `CMLWorkerDesiredStatusUpdatedDomainEvent` is published
4. `CMLWorkerDesiredStatusUpdatedEtcdProjector` writes to etcd `/workers/{id}/desired_state`
5. worker-controller watching `/workers/` prefix receives event immediately
6. worker-controller fetches worker from API, sees `desired_status != status`
7. worker-controller calls AWS EC2 to stop instance
8. worker-controller updates `status=STOPPED` via control-plane-api

## References

- ADR-001: API-Centric State Management (control-plane-api as state store)
- ADR-005: Dual State Store Architecture (etcd + MongoDB)
- ADR-014: Worker Orphan Detection (triggered this discovery)
- [Kubernetes Controller Pattern](https://kubernetes.io/docs/concepts/architecture/controller/)
- [12-Factor App: Backing Services](https://12factor.net/backing-services)
