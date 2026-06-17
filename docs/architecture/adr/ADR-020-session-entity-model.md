# ADR-020: Session Entity Model Redesign

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted (Partially Superseded) |
| **Date** | 2026-02-18 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-018](./ADR-018-lds-integration.md) (LDS Integration), [ADR-019](./ADR-019-labrecord-independent-aggregate.md) (LabRecord — partially superseded), [ADR-021](./ADR-021-child-entity-architecture.md) (Child Entities), [ADR-003](./ADR-003-cloudevents-for-integration.md) (CloudEvents) |
| **Supersedes** | ADR-019 §LabletLabBinding (binding model only) |
| **Partially Superseded by** | [ADR-045](./ADR-045-multi-part-session-part-model.md) (the rich session state machine is re-homed to the **SessionPart** level) |
| **Knowledge Refs** | AD-38, AD-39, AD-42, AD-43, AD-44 |

## Context

The original domain model had several entities whose responsibilities overlapped:

- **LabletInstance**: Represented a CML lab reservation + running session, but the name implied infrastructure rather than user-facing session semantics.
- **LabletRecordRun**: A join entity tracking the operational relationship between a LabletInstance and a LabRecord, with fields like `allocated_ports`, `started_at`, `ended_at`, and `duration_seconds`.
- **LabletLabBinding**: A join entity managing the many-to-many relationship between LabletInstance and LabRecord over time.

This three-entity model introduced:

1. **Naming confusion**: "Instance" implied infrastructure; the actual concept is a user-facing session combining CML lab + LDS session + grading.
2. **Unnecessary indirection**: LabletLabBinding managed many-to-many bindings, but the actual relationship is 1:1 at any point in time.
3. **Split state**: Operational fields (ports, timing) lived in LabletRecordRun, forcing cross-entity lookups for common operations.
4. **Lifecycle fragmentation**: LabletInstance and LabletRecordRun had separate status enums that had to be kept in sync.

With the introduction of LDS sessions, GradingEngine integration, and the Sessions UI, the model needed simplification.

## Decision

### 1. Rename LabletInstance → LabletSession (AD-38)

`LabletInstance` is renamed to **`LabletSession`**. The session IS the top-level aggregate — there is no separate "Session" entity wrapping it. `LabletSession` represents the complete user experience: CML lab + LDS session + grading, all managed through a single lifecycle.

### 2. Eliminate LabletRecordRun and LabletLabBinding (AD-39, AD-42)

Both entities are eliminated entirely:

| Eliminated Entity | Absorbed By | Fields Moved |
|-------------------|-------------|--------------|
| **LabletRecordRun** | LabletSession | `allocated_ports`, `started_at`, `ended_at`, `duration_seconds` |
| **LabletLabBinding** | LabletSession | `lab_record_id` (direct field) |

The `lablet_lab_bindings` MongoDB collection is dropped. The `lablet_record_runs` collection is dropped.

### 3. LabletSession-to-LabRecord: 1:1 Active Binding (AD-43)

`LabletSession` has a direct `lab_record_id` field — no join entity needed:

- A LabletSession references **exactly one** LabRecord at a time (1:1)
- Multiple LabletSessions may reference the **same** LabRecord over time (reuse via wipe-for-reuse pattern, ADR-024)
- The binding is set during SCHEDULING and is immutable for the session lifetime
- LabRecord remains an independent AggregateRoot (ADR-019) with its own lifecycle

```python
@dataclass
class LabletSessionState:
    # ... other fields
    lab_record_id: str | None = None        # Direct binding (was LabletLabBinding)
    allocated_ports: dict[str, int] = field(default_factory=dict)  # Absorbed from LabletRecordRun
    started_at: datetime | None = None      # Absorbed from LabletRecordRun
    ended_at: datetime | None = None        # Absorbed from LabletRecordRun
    duration_seconds: float | None = None   # Absorbed from LabletRecordRun
```

### 4. Consolidated Lifecycle (AD-44)

The LabletSession lifecycle merges the previous LabletInstanceStatus and LabletRecordRunStatus into a single enum:

```
PENDING → SCHEDULED → INSTANTIATING → READY → RUNNING → COLLECTING → GRADING → STOPPING → STOPPED → ARCHIVED
                                                                                                       ↑
TERMINATED ← (from any state, on explicit termination or error)
```

| Status | Description | Trigger |
|--------|-------------|---------|
| `PENDING` | Created, awaiting scheduling | User request |
| `SCHEDULED` | Worker assigned, ports allocated | resource-scheduler |
| `INSTANTIATING` | CML lab importing + LDS provisioning | lablet-controller |
| `READY` | Infrastructure ready, awaiting user login | lablet-controller |
| `RUNNING` | User actively using the lab session | LDS CloudEvent (`lds.session.started`) |
| `COLLECTING` | Assessment data collection in progress | Collect command or LDS CloudEvent (`lds.session.ended`) |
| `GRADING` | GradingEngine scoring in progress | lablet-controller → GradingSPI |
| `STOPPING` | Lab stopping + LDS archiving | lablet-controller |
| `STOPPED` | Lab stopped, resources partially released | lablet-controller |
| `ARCHIVED` | Session archived, score report finalized | lablet-controller |
| `TERMINATED` | Emergency/manual termination from any state | Admin action or error |

**Key change**: The `READY` state (between INSTANTIATING and RUNNING) explicitly tracks when infrastructure is fully provisioned but the user has not yet logged in. This enables user engagement metrics and no-show detection.

## Rationale

### Why rename to "Session"?

- The concept represents a **user session** (lab time + LDS + grading), not just an infrastructure instance.
- Aligns with LDS terminology (LabSession) and user-facing UI ("Sessions" page).
- Eliminates the confusion between "instance" (AWS EC2) and "instance" (lab reservation).

### Why eliminate join entities?

- The actual relationship is 1:1 at runtime — many-to-many was over-engineered.
- Operational fields (ports, timing) belong on the session aggregate, not a satellite entity.
- Reduces the number of MongoDB collections from 5 to 3 (lablet_sessions, lab_records, lablet_definitions).
- Simplifies query patterns — no cross-collection joins needed for common operations.

### Why a consolidated lifecycle?

- Users see a single session with one status, not separate infrastructure and operational states.
- Reduces state synchronization bugs between formerly separate entities.
- The READY state enables explicit tracking of the "infrastructure ready, waiting for user" window.

## Consequences

### Positive

- **Simpler domain model**: 1 aggregate instead of 3 entities for the core session concept
- **Fewer collections**: 2 collections dropped (`lablet_lab_bindings`, `lablet_record_runs`)
- **Unified lifecycle**: Single status enum replaces 2 separate status enums
- **Better naming**: "Session" aligns with user-facing semantics and LDS terminology
- **Simpler queries**: No cross-collection joins for session + ports + timing data

### Negative

- **Migration required**: Existing data must be migrated from 3 collections to 1
- **Breaking API changes**: All `/api/lablet-instances` endpoints rename to `/api/v1/sessions`
- **CloudEvent type changes**: `ccm.lablet.instance.*` → `ccm.lablet.session.*`
- **etcd key changes**: `/lcm/instances/` → `/lcm/sessions/`

### Risks

- Migration script complexity for production data
- External systems consuming old CloudEvent types must be updated

## Implementation Notes

### Migration Checklist

1. Create `lablet_sessions` collection with merged schema
2. Migrate data: LabletInstance + LabletRecordRun + LabletLabBinding → LabletSession
3. Update etcd key prefixes: `/lcm/instances/` → `/lcm/sessions/`
4. Update all API endpoints
5. Update CloudEvent type prefixes
6. Drop old collections after verification
7. Update UI to use new API endpoints

### Entity Hierarchy (Post-Redesign)

```
LabletSession (AggregateRoot)         ← renamed from LabletInstance
  ├── lab_record_id                   ← absorbed from LabletLabBinding
  ├── allocated_ports                 ← absorbed from LabletRecordRun
  ├── started_at, ended_at           ← absorbed from LabletRecordRun
  ├── user_session_id → UserSession   ← see ADR-021
  ├── grading_session_id → GradingSession  ← see ADR-021
  └── score_report_id → ScoreReport   ← see ADR-021

LabRecord (AggregateRoot)             ← unchanged (ADR-019)
LabletDefinition (AggregateRoot)      ← unchanged
```

## Related Documents

- [Lablet Resource Manager Architecture](../lablet-resource-manager-architecture.md) §3.3
- [LabletSession Lifecycle Flow](../lablet-instance-lifecycle-flow.md)
- [Architecture Overview](../index.md) — Data Flow diagram
