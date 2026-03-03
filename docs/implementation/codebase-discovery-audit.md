# Codebase Discovery Audit

| Attribute | Value |
|-----------|-------|
| **Document Version** | 1.0.0 |
| **Status** | Complete |
| **Created** | 2026-02-08 |
| **Author** | LCM Architecture Team |
| **Related** | [Requirements](../specs/lablet-resource-manager-requirements.md), [Implementation Status](./IMPLEMENTATION_STATUS.md) |

---

## 1. Executive Summary

This document provides a systematic inventory of the Lablet Cloud Manager codebase to enable accurate implementation planning. The audit covers:

- **lcm-core**: Shared library with read models, infrastructure patterns, and integration clients
- **control-plane-api**: Authoritative aggregates, CQRS commands/queries, REST API
- **resource-scheduler**: Scheduling reconciler with leader election
- **worker-controller**: EC2/CloudWatch/CML worker lifecycle management
- **lablet-controller**: Lab instance lifecycle management via CML Labs API

### Key Findings

| Aspect | Status | Notes |
|--------|--------|-------|
| **Domain Models** | ✅ Well-defined | 4 aggregates, 10+ value objects, comprehensive enums |
| **Read Model Sharing** | ✅ Implemented | lcm-core provides read-only models for controllers |
| **Reconciliation Pattern** | ✅ Mature | WatchTriggeredHostedService with leader election |
| **CQRS Layer** | ✅ Complete | Self-contained command/query handlers |
| **State Machines** | ✅ Defined | LabletInstanceStatus with 10 states, CMLWorkerStatus with 9 states |
| **LDS Integration** | 🔶 Partial | form_qualified_name added, provisioning not implemented |
| **Grading Integration** | 🔶 Partial | States exist, external API not connected |

---

## 2. lcm-core Shared Library

**Path**: `src/core/lcm_core/`

The shared library provides foundational components used by all microservices.

### 2.1 Domain Layer

```
lcm_core/domain/
├── __init__.py
├── entities/
│   ├── __init__.py
│   └── read_models/
│       ├── cml_worker_read_model.py
│       ├── lablet_definition_read_model.py
│       ├── lablet_instance_read_model.py
│       └── worker_template_read_model.py
├── enums/
│   └── __init__.py           # Empty - enums in control-plane-api
├── events/
│   └── __init__.py           # Empty - events in control-plane-api
└── value_objects/
    └── __init__.py           # Empty - VOs in control-plane-api
```

#### 2.1.1 Read Models (Shared DTOs)

| Read Model | Purpose | Key Attributes | Used By |
|------------|---------|----------------|---------|
| `CMLWorkerReadModel` | Worker state for controllers | id, name, status, desired_status, ec2_instance_id, ip_address, license (CMLLicenseReadModel) | worker-controller |
| `LabletInstanceReadModel` | Instance state for reconciliation | id, definition_id, status, worker_id, cml_lab_id, topology_yaml | lablet-controller, resource-scheduler |
| `LabletDefinitionReadModel` | Definition metadata | id, name, node_count, required_licenses | lablet-controller |
| `WorkerTemplateReadModel` | Template config | id, name, instance_type, ami_id | worker-controller |

!!! note "Read Model Pattern"
    These are **immutable DTOs**, not aggregates. Controllers use them for decision-making but mutations go through the Control Plane API. This follows ADR-009 (Shared Core Package).

### 2.2 Infrastructure Layer

```
lcm_core/infrastructure/
├── __init__.py
├── hosted_services/
│   ├── reconciliation_hosted_service.py
│   ├── leader_elected_hosted_service.py
│   └── watch_triggered_hosted_service.py
├── logging.py
├── mixins/
│   └── standard_endpoints_mixin.py
└── seeding/
    ├── database_seeder.py
    └── entity_seeder.py
```

#### 2.2.1 Hosted Services (Reconciliation Patterns)

| Service | Purpose | Key Features |
|---------|---------|--------------|
| `ReconciliationHostedService[T]` | Kubernetes-style reconciliation loop | Generic, configurable interval, metrics, backoff |
| `LeaderElectedHostedService[T]` | Reconciliation with etcd leader election | Extends ReconciliationHostedService, lease-based election |
| `WatchTriggeredHostedService[T]` | Reactive reconciliation with etcd watch | Dual-mode: watch + polling fallback |

**ReconciliationConfig Options:**

```python
@dataclass
class ReconciliationConfig:
    interval_seconds: float = 30.0      # Polling interval
    initial_delay_seconds: float = 5.0  # Startup delay
    polling_enabled: bool = True        # ADR-015: Can disable for watch-only
    max_concurrent_reconciles: int = 10 # Parallel limit
    backoff_initial_seconds: float = 1.0
    backoff_max_seconds: float = 60.0
    service_name: str = "reconciliation" # Metric labels
```

**ReconciliationResult Pattern:**

```python
class ReconciliationStatus(Enum):
    SUCCESS = "success"   # Resource in desired state
    REQUEUE = "requeue"   # In progress, retry later
    FAILED = "failed"     # Error, backoff
    SKIP = "skip"         # Already being processed
```

#### 2.2.2 Infrastructure Utilities

| Utility | Purpose |
|---------|---------|
| `configure_logging()` | Centralized structured logging |
| `StandardEndpointsMixin` | /health, /ready, /metrics, /info endpoints |
| `DatabaseSeeder` | YAML-based aggregate seeding |

### 2.3 Integration Layer

```
lcm_core/integration/
├── __init__.py
└── clients/
    ├── control_plane_client.py
    └── etcd_client.py
```

#### 2.3.1 Control Plane API Client

**Key Methods:**

| Category | Methods |
|----------|---------|
| **Instances** | `get_lablet_instances()`, `get_lablet_instance()`, `schedule_instance()`, `transition_instance()` |
| **Workers** | `get_workers()`, `get_worker()`, `update_worker_status()`, `update_worker_metrics()` |
| **Definitions** | `get_lablet_definitions()`, `get_lablet_definition()` |
| **Templates** | `get_worker_templates()`, `get_worker_template()` |

**Features:**

- Automatic retry with exponential backoff
- Connection pooling via httpx.AsyncClient
- Internal API authentication (X-API-Key)

#### 2.3.2 etcd Client

**Key Capabilities:**

| Category | Methods |
|----------|---------|
| **Key-Value** | `get()`, `put()`, `delete()` |
| **Leases** | `grant_lease()`, `revoke_lease()`, `keep_alive()` |
| **Leader Election** | `put_if_not_exists()` (compare-and-swap) |
| **Watch** | `watch()` async iterator for key changes |

---

## 3. control-plane-api (Authoritative Aggregates)

**Path**: `src/control-plane-api/`

The Control Plane API owns all aggregates and is the single source of truth.

### 3.1 Domain Entities (Aggregates)

```
domain/entities/
├── cml_worker.py           # 2147 lines - Main worker aggregate
├── lablet_instance.py      # 680 lines - Instance lifecycle
├── lablet_definition.py    # 463 lines - Versioned templates
├── worker_template.py      # 265 lines - EC2 configuration templates
├── lab_record.py           # Legacy lab tracking
├── pending_lab_import.py   # Lab import queue
├── system_settings.py      # Global settings
└── task.py / task_entity.py # Generic task tracking
```

#### 3.1.1 CMLWorker Aggregate

**State Machine:**

```
PENDING → STARTING → RUNNING → STOPPING → STOPPED → SHUTTING_DOWN → TERMINATED
                 ↓                 ↓
              FAILED           FAILED
```

**Key State Attributes:**

| Attribute | Type | Purpose |
|-----------|------|---------|
| `status` | CMLWorkerStatus | Actual EC2 state |
| `desired_status` | CMLWorkerStatus | Reconciliation target (spec) |
| `service_status` | CMLServiceStatus | CML HTTPS availability |
| `license` | CMLLicense | License state with pending operations (ADR-016) |
| `metrics` | CMLMetrics | CML system telemetry |
| `declared_capacity` | WorkerCapacity | From template |
| `allocated_capacity` | WorkerCapacity | Sum of instance allocations |
| `port_allocations` | list[PortAllocation] | Ports assigned to instances |
| `instance_ids` | list[str] | LabletInstances on this worker |

**Activity Tracking (Idle Detection):**

- `last_activity_at`, `last_activity_check_at`
- `target_pause_at`, `is_idle_detection_enabled`
- Auto-pause/resume counters

#### 3.1.2 LabletInstance Aggregate

**State Machine (per FR-2.2.1):**

```
PENDING → SCHEDULED → INSTANTIATING → RUNNING → COLLECTING → GRADING → STOPPING → STOPPED → ARCHIVED → TERMINATED
                                            ↓
                                    TERMINATED (from any state)
```

**Key State Attributes:**

| Attribute | Type | Purpose |
|-----------|------|---------|
| `definition_id` | str | Reference to LabletDefinition |
| `definition_version` | str | Pinned version |
| `worker_id` | str | Assigned worker |
| `allocated_ports` | dict[str, int] | Port mappings |
| `cml_lab_id` | str | Lab ID in CML |
| `state_history` | list[StateTransition] | Audit trail |
| `grading_score` | GradingScore | Assessment result |
| `timeslot_start/end` | datetime | Scheduling window |

!!! info "Missing LDS Fields (FR-2.2.5)"
    The spec requires `lds_session_id` and `lds_login_url` but these are **not yet implemented** in the aggregate.

#### 3.1.3 LabletDefinition Aggregate

**Key State Attributes:**

| Attribute | Type | Requirement Status |
|-----------|------|-------------------|
| `id`, `name`, `version` | str | ✅ FR-2.1.1a-c |
| `lab_artifact_uri`, `lab_yaml_hash` | str | ✅ FR-2.1.1d |
| `resource_requirements` | ResourceRequirements | ✅ FR-2.1.1e |
| `license_affinity` | list[LicenseType] | ✅ FR-2.1.1f |
| `node_count` | int | ✅ FR-2.1.1i |
| `port_template` | PortTemplate | ✅ FR-2.1.1j |
| `warm_pool_depth` | int | ✅ FR-2.1.1 (optional) |
| `form_qualified_name` | str | ❌ **NOT IMPLEMENTED** (FR-2.1.6) |
| `content_bucket_name` | str | ❌ **NOT IMPLEMENTED** |
| `grading_rules_uri` | str | ✅ FR-2.1.1 (optional) |
| `max_duration_minutes` | int | ✅ FR-2.1.1 |

#### 3.1.4 WorkerTemplate Aggregate

**Key State Attributes:**

| Attribute | Type | Purpose |
|-----------|------|---------|
| `name` | str | Unique template identifier |
| `instance_type` | Ec2InstanceType | AWS EC2 instance type |
| `capacity` | WorkerCapacity | Compute limits |
| `ami_name_pattern` | str | AMI lookup pattern |
| `cost_per_hour_usd` | float | Cost optimization |

### 3.2 Value Objects

```
domain/value_objects/
├── cml_license.py          # License state + pending ops
├── cml_metrics.py          # System telemetry (nested VOs)
├── grading_score.py        # Assessment results
├── port_allocation.py      # Instance port mappings
├── port_template.py        # Definition port placeholders
├── resource_requirements.py # CPU/Memory/Storage requirements
├── state_transition.py     # State history entry
└── worker_capacity.py      # Capacity tracking
```

| Value Object | Frozen | Key Methods |
|--------------|--------|-------------|
| `CMLLicense` | No (mutable) | Status + pending token/operation (ADR-016) |
| `CMLMetrics` | No | Nested: CMLSystemInfo, CMLSystemHealth |
| `GradingScore` | Yes | `score`, `max_score`, `checks[]` |
| `PortAllocation` | Yes | `instance_id`, `ports: dict[str, int]` |
| `PortTemplate` | Yes | `port_definitions[]` with placeholders |
| `ResourceRequirements` | Yes | `fits_capacity()`, `to_dict()` |
| `StateTransition` | Yes | `from_state`, `to_state`, `triggered_by`, `reason` |
| `WorkerCapacity` | Yes | `can_fit()`, `subtract()`, `add()` |

### 3.3 Enumerations

```python
# domain/enums.py

class CMLWorkerStatus(str, Enum):
    PENDING, STARTING, RUNNING, STOPPING, STOPPED, SHUTTING_DOWN, TERMINATED, FAILED, UNKNOWN

class CMLServiceStatus(str, Enum):
    UNAVAILABLE, STARTING, AVAILABLE, ERROR

class LicenseStatus(str, Enum):
    UNREGISTERED, REGISTERED, EVALUATION, EXPIRED, INVALID

class LicenseType(str, Enum):
    PERSONAL, ENTERPRISE, EVALUATION

class LabletDefinitionStatus(str, Enum):
    ACTIVE, DEPRECATED, ARCHIVED

class LabletInstanceStatus(str, Enum):
    PENDING, SCHEDULED, INSTANTIATING, RUNNING, COLLECTING, GRADING, STOPPING, STOPPED, ARCHIVED, TERMINATED

# Valid transitions table
LABLET_INSTANCE_VALID_TRANSITIONS: dict[LabletInstanceStatus, list[LabletInstanceStatus]]
```

### 3.4 CQRS Commands

```
application/commands/
├── worker/                 # 21 command files
├── lablet_instance/        # 7 command files
├── lablet_definition/      # (not audited, similar pattern)
├── lab/                    # Lab record commands
├── settings/               # System settings
└── task/                   # Task tracking
```

#### Worker Commands

| Command | Purpose |
|---------|---------|
| `CreateCMLWorkerCommand` | Provision new worker from template |
| `StartCMLWorkerCommand` | Start stopped worker |
| `StopCMLWorkerCommand` | Stop running worker |
| `TerminateCMLWorkerCommand` | Terminate and cleanup |
| `UpdateCMLWorkerStatusCommand` | Sync actual status |
| `UpdateCMLWorkerMetricsCommand` | Update telemetry |
| `RegisterCMLWorkerLicenseCommand` | License registration (ADR-016) |
| `DeregisterCMLWorkerLicenseCommand` | License deregistration |
| `DetectWorkerIdleCommand` | Idle detection check |
| `PauseWorkerCommand` | Trigger pause (idle or manual) |

#### LabletInstance Commands

| Command | Purpose | Requirement |
|---------|---------|-------------|
| `CreateLabletInstanceCommand` | Create instance from definition | FR-2.2.3a |
| `ScheduleLabletInstanceCommand` | Assign to worker with ports | FR-2.2.3b-c |
| `AllocateInstancePortsCommand` | Port allocation on worker | FR-2.2.4 |
| `TransitionLabletInstanceCommand` | Generic state transition | FR-2.2.1 |
| `StartCollectionCommand` | Trigger COLLECTING state | FR-2.2.7 |
| `StartGradingCommand` | Trigger GRADING state | FR-2.2.7 |
| `TerminateLabletInstanceCommand` | Terminate and release resources | FR-2.2.1 |

### 3.5 CQRS Queries

```
application/queries/
├── get_cml_worker_by_id_query.py
├── get_cml_workers_query.py
├── list_cml_workers_internal_query.py  # Internal API
├── get_lablet_instance_query.py
├── list_lablet_instances_query.py
├── get_lablet_definition_query.py
├── list_lablet_definitions_query.py
├── search_lablet_definitions_query.py
├── get_worker_labs_query.py
├── get_worker_telemetry_events_query.py
└── ...
```

---

## 4. Service-Specific Domains

### 4.1 resource-scheduler

**Path**: `src/resource-scheduler/`

**Domain Layer:** Minimal - uses lcm-core read models

```
domain/
├── entities/
│   └── __init__.py  # Empty
├── events/
│   └── __init__.py  # Empty
└── repositories/
    └── __init__.py  # Empty
```

**Hosted Services:**

| Service | Purpose |
|---------|---------|
| `SchedulerHostedService` | Leader-elected scheduling reconciler |
| `CleanupHostedService` | Terminated worker cleanup |

**Key Scheduling Logic:**

- Fetches PENDING instances from Control Plane API
- Evaluates worker capacity, license affinity, resource requirements
- Calls `schedule_instance()` to assign worker
- Uses leader election for HA

### 4.2 worker-controller

**Path**: `src/worker-controller/`

**Domain Layer:** Minimal - uses lcm-core read models

```
domain/
└── __init__.py  # Empty
```

**Hosted Services:**

| Service | Purpose |
|---------|---------|
| `WorkerReconciler` | WatchTriggeredHostedService for worker lifecycle + EC2 instance discovery (via `_run_discovery_loop()`) |

**SPI Clients:**

| Client | Purpose |
|--------|---------|
| `AwsEc2SpiClient` | EC2 lifecycle operations |
| `AwsCloudWatchSpiClient` | CloudWatch metrics |
| `CmlSystemSpiClient` | CML System API (/api/v0/system_*) |

**Reconciliation Pattern:**

```
SPEC (desired_status from API) ←→ OBSERVE (EC2 + CML state) → ACT (start/stop/terminate)
```

### 4.3 lablet-controller

**Path**: `src/lablet-controller/`

**Domain Layer:** Minimal - uses lcm-core read models

```
domain/
├── entities/
│   └── __init__.py  # Empty
├── events/
│   └── __init__.py  # Empty
└── repositories/
    └── __init__.py  # Empty
```

**Hosted Services:**

| Service | Purpose |
|---------|---------|
| `LabletReconciler` | WatchTriggeredHostedService for lab lifecycle |
| `LabsRefreshService` | Periodic lab data refresh |

**SPI Client:**

| Client | Purpose |
|--------|---------|
| `CmlLabsSpiClient` | CML Labs API (import, start, stop, wipe, delete) |

**Reconciliation Pattern:**

```
SPEC (instance status from API) ←→ OBSERVE (CML lab state) → ACT (import/start/stop)
```

---

## 5. Gap Analysis vs. Requirements

### 5.1 LabletDefinition Gaps

| Requirement | Status | Gap Description |
|-------------|--------|-----------------|
| FR-2.1.1 form_qualified_name | ❌ Missing | Key attribute for LDS/S3 content identification |
| FR-2.1.1 content_bucket_name | ❌ Missing | Derived from form_qualified_name |
| FR-2.1.5 Artifact Sync (hash compare) | ❌ Missing | lab_yaml_hash exists but sync not implemented |
| FR-2.1.6 LDS Content Refresh | ❌ Missing | No LDS integration |

### 5.2 LabletInstance Gaps

| Requirement | Status | Gap Description |
|-------------|--------|-----------------|
| FR-2.2.1 READY state | ❌ Missing | State not in LabletInstanceStatus enum |
| FR-2.2.5 lds_session_id | ❌ Missing | Not in aggregate state |
| FR-2.2.5 lds_login_url | ❌ Missing | Not in aggregate state |
| FR-2.2.5 LabSession Provisioning | ❌ Missing | No LDS client |
| FR-2.2.6 CloudEvent Handler | ❌ Missing | No session.started handling |
| FR-2.2.7 CollectAndGrade flow | 🔶 Partial | Commands exist, external integration missing |

### 5.3 Scheduling Gaps

| Requirement | Status | Gap Description |
|-------------|--------|-----------------|
| FR-2.3.2a "ASAP" scheduling | 🔶 Partial | Basic scheduling works, optimization TBD |
| FR-2.3.2e AMI requirements | 🔶 Partial | AmiRequirement VO exists, matching not verified |

### 5.4 Auto-Scaling Gaps

| Requirement | Status | Gap Description |
|-------------|--------|-----------------|
| FR-2.5.1a Scale-up triggers | ✅ Implemented | Worker provisioning works |
| FR-2.5.1d Startup time accounting | ❓ Unclear | Need to verify 15-minute buffer logic |

### 5.5 Warm Pool Gaps

| Requirement | Status | Gap Description |
|-------------|--------|-----------------|
| FR-2.7.1 Warm Pool Management | ❌ Not Started | warm_pool_depth attribute exists, logic not implemented |

---

## 6. Integration Points Summary

### 6.1 Implemented Integrations

| Integration | Client Location | Status |
|-------------|-----------------|--------|
| Control Plane API | lcm-core | ✅ Complete |
| etcd (leader election) | lcm-core | ✅ Complete |
| AWS EC2 | worker-controller | ✅ Complete |
| AWS CloudWatch | worker-controller | ✅ Complete |
| CML System API | worker-controller | ✅ Complete |
| CML Labs API | lablet-controller | ✅ Complete |
| MongoDB | control-plane-api | ✅ Complete |

### 6.2 Missing Integrations (per Requirements)

| Integration | Requirement | Status |
|-------------|-------------|--------|
| LDS (Lab Delivery System) | FR-2.2.5, FR-2.2.6, FR-2.1.6 | ❌ Not Started |
| Grading Engine | FR-2.2.7, FR-2.6.2 | ❌ Not Started |
| S3/MinIO (Artifacts) | FR-2.1.5 | ❌ Not Started |
| CloudEvents Bus | FR-2.6.3 | 🔶 Partial (events defined, bus not connected) |

---

## 7. Test Coverage Summary

### 7.1 Per-Service Test Status

| Service | Unit Tests | Integration Tests | Notes |
|---------|------------|-------------------|-------|
| control-plane-api | ✅ Present | 🔶 Partial | Command handlers covered |
| resource-scheduler | ✅ Present | 🔶 Partial | Scheduling logic tested |
| worker-controller | ✅ Present | 🔶 Partial | Reconciler tested |
| lablet-controller | ✅ Present | 🔶 Partial | Lab lifecycle tested |
| lcm-core | ✅ Present | ➖ | Read models + hosted services |

### 7.2 Critical Test Gaps

1. **End-to-end flow tests** - No full reservation → execution → grading flow
2. **LDS integration tests** - Cannot test without LDS client
3. **CloudEvents tests** - Event emission tested, consumption not
4. **Failure recovery tests** - Partial testing of failure scenarios

---

## 8. MVP Scope Definition

Based on stakeholder clarification (2026-02-08):

### 8.1 MVP Requirements (Must Have)

| Capability | Requirement | Rationale |
|------------|-------------|-----------|
| **LDS Integration** | FR-2.2.5, FR-2.2.6, FR-2.1.6 | End-users access labs via LDS UI; no LDS = no user access |
| **Session Provisioning** | FR-2.2.5a-h | Create LabSession, set devices, get login URL |
| **Start Detection** | FR-2.2.6 | CloudEvent `session.started` triggers READY → RUNNING |
| **Session Archival** | FR-2.2.5i | Archive LabSession on TERMINATED |
| **Grading Process** | FR-2.2.7, FR-2.6.1-2 | Collection + grading completes assessment workflow |
| **CloudEvents Bus** | FR-2.6.3 | Infrastructure exists; connect LCM to emit/consume |

### 8.2 Deferred (Post-MVP)

| Capability | Requirement | Status |
|------------|-------------|--------|
| **Warm Pool** | FR-2.7.1 | Deferred - optimization, not blocking |
| **S3/MinIO Artifact Sync** | FR-2.1.5 | Deferred - manual artifact management acceptable initially |
| **Multi-region** | N/A | Out of scope |

### 8.3 Infrastructure Assumptions

- **CloudEvents Bus**: Exists (not in local docker-compose for brevity, but available in staging/prod)
- **LDS API**: Available for integration
- **Grading Engine**: API spec exists ([grading-engine_openapi.json](../grading-engine_openapi.json))

---

## 9. Implementation Path

!!! info "Authoritative Implementation Plan"
    For detailed implementation phases, tasks, and acceptance criteria, see the **[MVP Implementation Plan](./mvp-implementation-plan.md)**.

This discovery audit informed the creation of the MVP Implementation Plan v2.0.0, which establishes a **foundation-first** approach:

| Phase | Focus | Derived From |
|-------|-------|--------------|
| Phase 0 | Domain Prerequisites | Gap analysis (§5.2) |
| Phase 1 | Worker Foundation | Finding: `allocated_capacity` not updated |
| Phase 2 | Resource Scheduling | Finding: PlacementEngine uses stale data |
| Phase 3 | Auto-Scaling | Finding: Worker provisioning stubbed |
| Phase 4 | LDS Integration | Gap: No LDS client (§6.2) |
| Phase 5 | Grading Integration | Gap: No grading client (§6.2) |

### Key Gaps Driving Implementation Order

1. **Capacity Tracking** (Phase 1): `ScheduleLabletInstanceCommand` has `TODO: Check worker capacity` - must fix before scheduling is reliable
2. **Worker Provisioning** (Phase 3): `_handle_pending` returns "Template provisioning not yet implemented"
3. **LDS Client** (Phase 4): No client exists for session provisioning
4. **Grading Client** (Phase 5): No client exists for artifact submission

---

## 10. Appendix: File Counts

| Component | Python Files | Lines (approx) |
|-----------|--------------|----------------|
| lcm-core | 15 | ~2,500 |
| control-plane-api/domain | 35+ | ~8,000 |
| control-plane-api/application | 40+ | ~6,000 |
| resource-scheduler | 20 | ~2,000 |
| worker-controller | 25 | ~4,000 |
| lablet-controller | 25 | ~3,500 |

**Total estimated**: ~26,000 lines of Python

---

## 11. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-02-08 | LCM Architecture Team | Initial discovery audit |
| 1.1.0 | 2026-02-08 | LCM Architecture Team | Added MVP scope (§8), phase recommendations (§9) |
| 1.2.0 | 2026-02-08 | LCM Architecture Team | Consolidated §9 to reference authoritative MVP Implementation Plan |
