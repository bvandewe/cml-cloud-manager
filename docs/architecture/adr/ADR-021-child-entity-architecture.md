# ADR-021: Child Entity Architecture for Session Tracking

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted (Partially Superseded) |
| **Date** | 2026-02-18 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-020](./ADR-020-session-entity-model.md) (Session Entity Model), [ADR-018](./ADR-018-lds-integration.md) (LDS Integration), [ADR-022](./ADR-022-cloudevent-ingestion-lablet-controller.md) (CloudEvent Ingestion) |
| **Partially Superseded by** | [ADR-045](./ADR-045-multi-part-session-part-model.md) (child entities generalise into first-class `SessionPart` `TimedResource`s) |
| **Knowledge Refs** | AD-40, AD-45, AD-46, AD-47-R1 |

## Context

With the LabletSession redesign (ADR-020), the session aggregate needs to track three external system interactions:

1. **LDS Session**: User-facing lab delivery session with login URL, device access, and content
2. **Grading Session**: Assessment orchestrated by the GradingEngine with pod/device mappings
3. **Score Report**: Final scoring output from grading, including per-section breakdowns

### Design Tension: Embed vs. Separate

Two approaches were considered:

| Approach | Pros | Cons |
|----------|------|------|
| **Embedded** (value objects in LabletSessionState) | Simple, single-document reads | Large aggregate, hard to query independently |
| **Separate** (Entity[str] with own collections) | Independent queries, smaller aggregates, reusable | More collections, cross-collection consistency |

### Why Separate Entities?

- **Reporting queries**: Score reports need independent queries (e.g., "all scores for a form", "scores above threshold") without loading full session aggregates
- **Different lifecycles**: UserSession has its own status machine (PROVISIONING→ACTIVE→ENDED), independent of LabletSession status
- **External system alignment**: Each entity maps 1:1 to an external system's concept (LDS session, GradingEngine session, score report)
- **Collection size**: LabletSession documents would become very large with embedded grading details and score breakdowns

## Decision

### 1. UserSession — Entity[str] (AD-45)

Tracks the LDS (Lab Delivery System) session scoped to a LabletSession.

**Collection**: `user_sessions`

```python
@dataclass
class UserSessionState:
    lablet_session_id: str          # FK to parent LabletSession
    lds_session_id: str             # LDS LabSession identifier
    lds_part_id: str                # LDS LabSessionPart identifier
    form_qualified_name: str        # Content identifier
    login_url: str                  # User-facing IFRAME URL
    devices: list[DeviceAccessInfo] # Provisioned device access
    status: UserSessionStatus       # Own lifecycle
    started_at: datetime | None = None
    ended_at: datetime | None = None

class UserSessionStatus(str, Enum):
    PROVISIONING = "PROVISIONING"   # LDS session being created
    PROVISIONED = "PROVISIONED"     # Session created, devices set
    ACTIVE = "ACTIVE"               # User logged in (lds.session.started)
    PAUSED = "PAUSED"               # User temporarily away
    ENDED = "ENDED"                 # User ended session (lds.session.ended)
    EXPIRED = "EXPIRED"             # Session timed out
    FAULTED = "FAULTED"             # LDS error
```

**Lifecycle**: Created during INSTANTIATING by lablet-controller. Status transitions driven by LDS CloudEvents received via CloudEventIngestor (ADR-022).

### 2. GradingSession — Entity[str] (AD-46)

Tracks a grading session orchestrated by the GradingEngine.

**Collection**: `grading_sessions`

```python
@dataclass
class GradingSessionState:
    lablet_session_id: str          # FK to parent LabletSession
    grading_session_id: str         # GradingEngine session ID
    grading_part_id: str            # GradingEngine part ID
    pod_id: str                     # GradingEngine pod ID
    form_qualified_name: str        # Content identifier
    devices: list[DeviceAccessInfo] # Devices being graded
    status: GradingStatus           # Own lifecycle
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

class GradingStatus(str, Enum):
    PENDING = "PENDING"             # Awaiting grading start
    COLLECTING = "COLLECTING"       # Data collection in progress
    GRADING = "GRADING"             # GradingEngine scoring
    REVIEWING = "REVIEWING"         # Manual review (future)
    SUBMITTED = "SUBMITTED"         # Score finalized
    FAULTED = "FAULTED"             # Grading error
```

**Lifecycle**: Created when LabletSession enters COLLECTING. Updated by GradingEngine CloudEvents (`grading.session.completed`, `grading.session.failed`) received via CloudEventIngestor (ADR-022).

### 3. ScoreReport — Entity[str] (AD-47-R1)

Stores the final scoring output from grading.

**Collection**: `score_reports`

```python
@dataclass
class ScoreReportState:
    lablet_session_id: str          # FK to parent LabletSession
    grading_session_id: str         # FK to GradingSession
    score: float                    # Achieved score
    max_score: float                # Maximum possible score
    cut_score: float                # Passing threshold
    passed: bool                    # score >= cut_score
    sections: list[ScoreSection]    # Per-section breakdown
    submitted_at: datetime          # When score was finalized
    report_url: str | None = None   # Link to detailed report

@dataclass
class ScoreSection:
    name: str                       # Section name (e.g., "Connectivity")
    score: float                    # Section score
    max_score: float                # Section max score
```

**Lifecycle**: Created from GradingEngine CloudEvent data when `grading.session.completed` is received. Immutable after creation — the score is final.

> **Note**: ScoreReport was initially designed as an embedded value object (AD-47) but promoted to a separate Entity[str] (AD-47-R1) to support independent reporting queries.

### 4. Relationship to LabletSession

LabletSession holds foreign key references to its child entities:

```python
@dataclass
class LabletSessionState:
    # ... session fields (see ADR-020)
    user_session_id: str | None = None       # FK to UserSession
    grading_session_id: str | None = None    # FK to GradingSession
    score_report_id: str | None = None       # FK to ScoreReport
```

The lablet-controller creates child entities via Control Plane API internal endpoints, which return the entity ID. The ID is then stored on LabletSession via a separate update call.

### 5. Internal API Endpoints

All child entity CRUD is via internal endpoints (lablet-controller → control-plane-api):

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/internal/sessions/{id}/user-session` | Create UserSession |
| `PUT` | `/api/internal/sessions/{id}/user-session/status` | Update UserSession status |
| `POST` | `/api/internal/sessions/{id}/grading-session` | Create GradingSession |
| `PUT` | `/api/internal/sessions/{id}/grading-session/status` | Update GradingSession status |
| `POST` | `/api/internal/sessions/{id}/score-report` | Create ScoreReport |

Public read endpoints are on the Control Plane API:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/sessions/{id}/user-session` | Get UserSession details |
| `GET` | `/api/v1/sessions/{id}/user-session/login-url` | Get LDS IFRAME login URL |
| `GET` | `/api/v1/sessions/{id}/grading-session` | Get GradingSession details |
| `GET` | `/api/v1/sessions/{id}/score-report` | Get ScoreReport |
| `GET` | `/api/v1/score-reports` | Query score reports (reporting) |

## Rationale

### Why not embed in LabletSession?

- Score reports need independent aggregation queries (average scores, pass rates per form)
- UserSession has its own lifecycle driven by LDS CloudEvents
- GradingSession has its own lifecycle driven by GradingEngine CloudEvents
- Embedding would make LabletSession documents excessively large
- Clean separation enables future extensions (multiple grading sessions per session, retakes)

### Why Entity[str] not AggregateRoot?

- These entities don't have independent lifecycles outside the context of a LabletSession
- They don't publish their own domain events (events are published by LabletSession aggregate)
- They don't need their own repositories — managed through LabletSession's lifecycle
- Simpler than full aggregates while still supporting independent queries

## Consequences

### Positive

- **Independent queries**: Score reports queryable without loading sessions
- **Clean lifecycle**: Each entity tracks its own status machine
- **Smaller aggregates**: LabletSession stays lean
- **External alignment**: 1:1 mapping to LDS/GradingEngine concepts
- **Future extensibility**: Multiple grading attempts, retakes

### Negative

- **More collections**: 3 new MongoDB collections (user_sessions, grading_sessions, score_reports)
- **Cross-collection reads**: Session detail view requires joins across 4 collections
- **Consistency**: Must ensure child entities are created/updated atomically with parent

### Risks

- Orphaned child entities if LabletSession is terminated mid-creation
- Query performance for reporting across large score_reports collection (mitigated by indexing)

## Implementation Notes

### MongoDB Indexes

```javascript
// user_sessions
db.user_sessions.createIndex({ "state.lablet_session_id": 1 }, { unique: true })
db.user_sessions.createIndex({ "state.lds_session_id": 1 })

// grading_sessions
db.grading_sessions.createIndex({ "state.lablet_session_id": 1 })
db.grading_sessions.createIndex({ "state.grading_session_id": 1 })

// score_reports
db.score_reports.createIndex({ "state.lablet_session_id": 1 }, { unique: true })
db.score_reports.createIndex({ "state.grading_session_id": 1 })
db.score_reports.createIndex({ "state.submitted_at": -1 })
db.score_reports.createIndex({ "state.passed": 1, "state.submitted_at": -1 })
```

### Cleanup Strategy

When a LabletSession is TERMINATED:

1. UserSession → status ENDED (if not already)
2. GradingSession → status FAULTED (if incomplete)
3. ScoreReport → retained for historical reporting (never deleted)

## Related Documents

- [ADR-020: Session Entity Model Redesign](./ADR-020-session-entity-model.md)
- [ADR-022: CloudEvent Ingestion via Lablet-Controller](./ADR-022-cloudevent-ingestion-lablet-controller.md)
- [Lablet Resource Manager Architecture](../lablet-resource-manager-architecture.md) §3.3.1–§3.3.3
- [LabletSession Lifecycle Flow](../lablet-instance-lifecycle-flow.md)
