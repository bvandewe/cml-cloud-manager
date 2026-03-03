# Lablet Resource Manager - Requirements Specification

| Attribute | Value |
|-----------|-------|
| **Document Version** | 0.4.0 |
| **Status** | Draft |
| **Created** | 2026-01-15 |
| **Last Updated** | 2026-02-18 |
| **Author** | Architecture Team |

---

## 1. Executive Summary

### 1.1 Vision

Transform Lablet Cloud Manager from an imperative EC2/CML management tool into a **Nearly Autonomous Lablet Resource Manager** with Kubernetes-like declarative resource management, intelligent scheduling, and auto-scaling capabilities.

### 1.2 Business Objectives

| Objective | Description | Success Metric |
|-----------|-------------|----------------|
| **Cost Optimization** | Minimize AWS compute costs through intelligent scheduling and auto-scaling | ≥30% reduction in idle worker time |
| **Scalability** | Support growing concurrent user base | Handle 1000+ concurrent LabletSessions |
| **Reliability** | Ensure exam/lab sessions are never disrupted | 99.9% session completion rate |
| **Automation** | Reduce manual intervention in resource management | ≥90% automated operations |

### 1.3 Scope

**In Scope:**

- Declarative LabletDefinition and LabletSession lifecycle management
- Intelligent scheduling with time-windowed reservations
- Automatic Worker scaling (up/down) based on demand
- Integration with LDS (Lab Delivery System) and GradingEngine for assessment
- Multi-license type support (Personal, Enterprise)
- CloudEvent-based integration for audit, LDS, and GradingEngine

**Out of Scope (This Phase):**

- Multi-cloud provider support (AWS-only initially, SPI designed for future)
- Cross-region failover
- Real-time collaborative lab sessions
- Custom node definition management

---

## 2. Functional Requirements

### 2.1 LabletDefinition Management

#### FR-2.1.1: Definition CRUD Operations

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1.1a | System SHALL allow creation of LabletDefinitions via REST API | P0 |
| FR-2.1.1b | System SHALL store LabletDefinitions as immutable versioned aggregates | P0 |
| FR-2.1.1c | System SHALL support semantic versioning (MAJOR.MINOR.PATCH) | P0 |
| FR-2.1.1d | System SHALL auto-increment version on detected diff from artifact | P1 |
| FR-2.1.1e | System SHALL allow admin to override/rename version tags | P1 |

#### FR-2.1.2: Definition Attributes

A LabletDefinition SHALL include:

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | UUID | Yes | Unique identifier |
| `name` | string | Yes | Human-readable name |
| `version` | semver | Yes | Semantic version (e.g., "1.2.3") |
| `form_qualified_name` | string | Yes | Globally unique content identifier (e.g., "Exam CCNP ENCOR v2.3 LAB 2.3.4a") |
| `lab_artifact_uri` | URI | Yes | S3/MinIO path to CML Lab YAML |
| `lab_yaml_hash` | string | Yes | SHA-256 of lab YAML content |
| `content_bucket_name` | string | Yes | S3/MinIO bucket (slugified form_qualified_name) |
| `resource_requirements` | object | Yes | CPU, memory, storage needs |
| `license_affinity` | enum[] | Yes | Compatible license types |
| `node_count` | integer | Yes | Total nodes in lab topology |
| `port_template` | object | Yes | Port allocation template |
| `grading_rules_uri` | URI | No | Path to grading criteria |
| `warm_pool_depth` | integer | No | Pre-provisioned lablet count |
| `max_duration_minutes` | integer | Yes | Maximum session duration |
| `owner_notification` | object | No | Contact info for crash notifications |
| `created_at` | datetime | Yes | Creation timestamp |
| `created_by` | string | Yes | Creator identity |

!!! note "form_qualified_name"
    The `form_qualified_name` is the globally unique key that enables multiple systems (LCM, LDS, Assessment Platform) to access shared content in S3/MinIO. The bucket name is derived by slugifying this value (e.g., "exam-ccnp-encor-v2-3-lab-2-3-4a").

#### FR-2.1.3: Resource Requirements Schema

```yaml
resource_requirements:
  cpu_cores: 4          # Minimum CPU cores
  memory_gb: 8          # Minimum RAM in GB
  storage_gb: 50        # Minimum storage in GB
  nested_virt: true     # Requires nested virtualization
  ami_requirements:     # Optional AMI constraints
    - name_pattern: "CML-2.9.*"
    - min_version: "2.9.0"
```

#### FR-2.1.4: License Affinity

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1.4a | System SHALL support license types: `PERSONAL`, `ENTERPRISE`, `EVALUATION` | P0 |
| FR-2.1.4b | System SHALL validate node_count against license capacity at scheduling | P0 |
| FR-2.1.4c | Personal license: max 20 nodes | P0 |
| FR-2.1.4d | Enterprise license: unlimited nodes | P0 |

#### FR-2.1.5: Artifact Synchronization

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1.5a | System SHALL download lab YAML from S3/MinIO on demand | P0 |
| FR-2.1.5b | System SHALL detect changes via hash comparison | P0 |
| FR-2.1.5c | System SHALL prompt admin for version tag on detected diff | P1 |
| FR-2.1.5d | System SHALL cache downloaded artifacts locally | P2 |

#### FR-2.1.6: LDS Content Synchronization

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1.6a | System SHALL call LDS `refresh_content` when a LabletDefinition is versioned | P0 |
| FR-2.1.6b | Content refresh SHALL be triggered synchronously via lablet-controller | P0 |
| FR-2.1.6c | System SHALL pass `form_qualified_name` to identify content in S3/MinIO | P0 |
| FR-2.1.6d | System SHALL log content refresh results for audit | P0 |

**Content Package Structure (S3/MinIO):**

The content bucket (derived from `form_qualified_name`) SHALL contain:

```
<slugified-form-qualified-name>/
├── content.xml          # Device definitions and UI layout
├── cml.yaml             # CML lab topology (nodes, links, annotations)
├── tasks/               # Task definitions for LDS UI
└── assets/              # Supporting files (images, scripts)
```

**content.xml Device Schema:**

```xml
<devices>
  <device category="" device_label="SW1" coords="157,417,256,516" user_access_mode="web"/>
  <device category="" device_label="R1" coords="300,200,400,300" user_access_mode="ssh"/>
</devices>
```

---

### 2.2 LabletSession Lifecycle

#### FR-2.2.1: Session States

```
┌─────────┐    ┌───────────┐    ┌───────────────┐    ┌─────────┐    ┌─────────┐
│ PENDING │───▶│ SCHEDULED │───▶│ INSTANTIATING │───▶│  READY  │───▶│ RUNNING │
└─────────┘    └───────────┘    └───────────────┘    └─────────┘    └─────────┘
                                                                         │
                                                                         ▼
┌────────────┐    ┌─────────┐    ┌───────────┐    ┌────────────┐    ┌────────────┐
│ TERMINATED │◀───│ ARCHIVED│◀───│  STOPPED  │◀───│  STOPPING  │◀───│ COLLECTING │
└────────────┘    └─────────┘    └───────────┘    └────────────┘    └────────────┘
                       ▲                                                  │
                       │                                                  ▼
                  ┌─────────┐                                       ┌───────────┐
                  │ GRADING │◀──────────────────────────────────────│  GRADING  │
                  └─────────┘                                       └───────────┘
```

| State | Description | Transitions To |
|-------|-------------|----------------|
| `PENDING` | Session requested, awaiting scheduling | `SCHEDULED`, `TERMINATED` |
| `SCHEDULED` | Assigned to worker, awaiting timeslot | `INSTANTIATING`, `TERMINATED` |
| `INSTANTIATING` | Lab importing/starting on worker, LDS session + UserSession provisioning | `READY`, `TERMINATED` |
| `READY` | CML Lab running, LDS session provisioned, UserSession created, awaiting user login | `RUNNING`, `TERMINATED` |
| `RUNNING` | User has logged in and is actively working | `COLLECTING`, `STOPPING` |
| `COLLECTING` | Gathering evidence from lab nodes via GradingSPI | `GRADING`, `STOPPING` |
| `GRADING` | GradingEngine processing via CloudEvent-driven flow | `STOPPING` |
| `STOPPING` | Lab stopping on worker | `STOPPED` |
| `STOPPED` | Lab stopped, resources held | `ARCHIVED`, `RUNNING` |
| `ARCHIVED` | Results stored (ScoreReport persisted), ready for cleanup | `TERMINATED` |
| `TERMINATED` | All resources released | (terminal) |

!!! info "READY State Purpose"
    The READY state explicitly tracks when infrastructure is fully provisioned but the user has not yet logged in.
    This enables: (1) user engagement metrics, (2) no-show detection, (3) event-driven state transitions from LDS.

#### FR-2.2.2: Session Attributes

A LabletSession SHALL include the following attributes (per ADR-020, ADR-021):

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | UUID | Yes | Unique identifier |
| `definition_id` | UUID | Yes | Reference to LabletDefinition |
| `definition_version` | semver | Yes | Pinned definition version |
| `worker_id` | UUID | No | Assigned worker (null until scheduled) |
| `state` | enum | Yes | Current lifecycle state (LabletSessionStatus) |
| `lab_record_id` | UUID | No | Bound LabRecord on worker (1:1 active binding, per ADR-020) |
| `allocated_ports` | map | No | Port allocations — serial, vnc, etc. (absorbed from LabletRecordRun) |
| `user_session_id` | UUID | No | FK → UserSession entity (null until INSTANTIATING) |
| `grading_session_id` | UUID | No | FK → GradingSession entity (null until COLLECTING) |
| `score_report_id` | UUID | No | FK → ScoreReport entity (null until grading completes) |
| `timeslot_start` | datetime | Yes | Requested start time |
| `timeslot_end` | datetime | Yes | Maximum end time |
| `owner_id` | string | Yes | Requestor identity |
| `reservation_id` | UUID | No | Associated exam/session reservation |
| `created_at` | datetime | Yes | Request timestamp |
| `started_at` | datetime | No | Actual start timestamp (absorbed from LabletRecordRun) |
| `ended_at` | datetime | No | Session end timestamp (absorbed from LabletRecordRun) |
| `duration_seconds` | integer | No | Computed session duration |
| `terminated_at` | datetime | No | Termination timestamp |

!!! info "Child Entity References (ADR-021)"
    LDS/grading-related attributes (`lds_session_id`, `lds_login_url`, `grading_score`) are NOT stored directly on LabletSession.
    Instead, they are managed in separate child entities (UserSession, GradingSession, ScoreReport) with their own MongoDB collections.
    The LabletSession holds only FK references (`user_session_id`, `grading_session_id`, `score_report_id`) to these entities.

#### FR-2.2.3: Session Operations

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.2.3a | System SHALL create LabletSession via reservation request | P0 |
| FR-2.2.3b | System SHALL assign session to worker with sufficient capacity | P0 |
| FR-2.2.3c | System SHALL allocate unique ports per session on assigned worker | P0 |
| FR-2.2.3d | System SHALL rewrite lab YAML with allocated ports at instantiation | P0 |
| FR-2.2.3e | System SHALL import rewritten lab YAML to CML worker | P0 |
| FR-2.2.3f | System SHALL start lab after successful import | P0 |
| FR-2.2.3g | System SHALL track session state transitions via domain events | P0 |
| FR-2.2.3h | System SHALL create UserSession child entity during INSTANTIATING phase | P0 |
| FR-2.2.3i | System SHALL create GradingSession child entity when entering COLLECTING | P0 |
| FR-2.2.3j | System SHALL create ScoreReport child entity upon grading completion | P0 |

#### FR-2.2.4: Port Allocation

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.2.4a | System SHALL allocate ports from range 2000-9999 per worker | P0 |
| FR-2.2.4b | System SHALL prevent port conflicts across sessions on same worker | P0 |
| FR-2.2.4c | System SHALL rewrite `smart_annotations.tag` values with allocated ports | P0 |
| FR-2.2.4d | System SHALL release ports when session reaches TERMINATED state | P0 |
| FR-2.2.4e | System SHALL track port allocations per worker | P0 |

**Port Rewriting Example:**

Template (in LabletDefinition):

```yaml
smart_annotations:
  - tag: serial:${PORT_SERIAL_1}
  - tag: vnc:${PORT_VNC_1}
```

Instantiated (per LabletSession):

```yaml
smart_annotations:
  - tag: serial:5041
  - tag: vnc:5044
```

#### FR-2.2.5: LabSession Provisioning (LDS Integration)

A LabletSession requires BOTH a CML lab AND a LabSession in LDS (Lab Delivery System). The LabSession provides the user-facing interface for interacting with lab devices and viewing task requirements. LDS-related attributes are stored in a **UserSession** child entity (per ADR-021).

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.2.5a | System SHALL provision LabSession in LDS during INSTANTIATING state | P0 |
| FR-2.2.5b | System SHALL create LabSession with username and timeslot details | P0 |
| FR-2.2.5c | System SHALL append LabSessionPart with `form_qualified_name` to identify content | P0 |
| FR-2.2.5d | System SHALL provision device access info for each device in content.xml | P0 |
| FR-2.2.5e | Device access info SHALL include: name, protocol, host, port, uri, username, password | P0 |
| FR-2.2.5f | Device port SHALL be derived from allocated ports (FR-2.2.4) | P0 |
| FR-2.2.5g | Device host SHALL be the CML worker IP address | P0 |
| FR-2.2.5h | System SHALL create a **UserSession** child entity with `lds_session_id`, `lds_part_id`, `login_url`, and `devices` | P0 |
| FR-2.2.5i | System SHALL store `user_session_id` FK reference on LabletSession | P0 |
| FR-2.2.5j | System SHALL archive LabSession when LabletSession reaches TERMINATED | P0 |
| FR-2.2.5k | All LDS interactions SHALL be synchronous via lablet-controller | P0 |

**LabSession Provisioning Sequence:**

```
1. lablet-controller detects INSTANTIATING state
2. Allocate ports (FR-2.2.4)
3. Import lab to CML worker
4. Call LDS: create_session_with_part(username, timeslot, form_qualified_name)
5. Parse content.xml to identify required devices
6. Map device_labels to allocated ports via cml.yaml annotations
7. Call LDS: set_devices(session_id, devices[])
8. Call LDS: get_session_info(session_id) → login_url
9. Create UserSession entity with lds_session_id, lds_part_id, login_url, devices
10. Store user_session_id FK on LabletSession
11. Transition to READY (awaiting user login)
12. LDS emits CloudEvent on user login → lablet-controller (ADR-022) → READY → RUNNING
```

**Device Access Info Schema:**

```yaml
devices:
  - name: "SW1"              # Matches device_label in content.xml
    protocol: "ssh"          # From cml.yaml annotation
    host: "10.0.1.50"        # CML worker IP
    port: 5041               # Allocated port
    uri: "ssh://10.0.1.50:5041"
    username: "admin"        # Device credentials
    password: "cisco123"
```

**LabSession State Mapping:**

| LabletSession State | LabSession State | Notes |
|---------------------|------------------|-------|
| `INSTANTIATING` | `PENDING` | Session created, devices being provisioned, UserSession created |
| `READY` | `PENDING` | Infrastructure ready, awaiting user login |
| `RUNNING` | `RUNNING` | User has logged in and is working |
| `COLLECTING` | `RUNNING` or `USER_FINISHED` | Depends on collection trigger |
| `TERMINATED` | `ARCHIVED` | Session archived for audit |

!!! note "State Decoupling"
    LDS states (`EMPTY`, `PENDING`, `PRELAUNCH`, `RUNNING`, `PAUSED`, `USER_FINISHED`, `ARCHIVED`) do not map 1:1 to LabletSession states. States like `PRELAUNCH` and `PAUSED` apply to other LDS lab types and are not used for Lablets.

#### FR-2.2.6: CloudEvent Handling (LDS & GradingEngine)

The system receives CloudEvents from LDS and GradingEngine to drive state transitions. All CloudEvents are routed to **lablet-controller** via its CloudEventIngestor endpoint (per ADR-022):

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.2.6a | lablet-controller SHALL expose a CloudEvent ingestion endpoint (CloudEventIngestor pattern) | P0 |
| FR-2.2.6b | lablet-controller SHALL handle `lds.session.started` event to transition READY → RUNNING | P0 |
| FR-2.2.6c | lablet-controller SHALL handle `lds.session.ended` event to trigger collection/stopping | P0 |
| FR-2.2.6d | lablet-controller SHALL handle `grading.session.completed` event to create ScoreReport and transition GRADING → STOPPING | P1 |
| FR-2.2.6e | lablet-controller SHALL handle `grading.session.failed` event for error handling | P1 |
| FR-2.2.6f | System SHALL validate session_id matches a known LabletSession (via UserSession lookup) | P0 |
| FR-2.2.6g | System SHALL log CloudEvent processing for audit | P0 |
| FR-2.2.6h | System SHALL ignore events for unknown session_ids (graceful degradation) | P0 |
| FR-2.2.6i | CloudEventIngestor SHALL use Neuroglia @dispatch pattern for event-type routing | P0 |

**CloudEvent Schema (lds.session.started):**

```json
{
  "specversion": "1.0",
  "type": "lds.session.started",
  "source": "/lds/sessions",
  "id": "evt-12345",
  "time": "2026-02-08T10:30:00Z",
  "data": {
    "session_id": "sess-abc123",
    "user_id": "user-xyz",
    "started_at": "2026-02-08T10:30:00Z"
  }
}
```

**CloudEvent Schema (grading.session.completed):**

```json
{
  "specversion": "1.0",
  "type": "grading.session.completed",
  "source": "/grading-engine/sessions",
  "id": "evt-67890",
  "time": "2026-02-08T11:00:00Z",
  "data": {
    "grading_session_id": "gs-abc123",
    "lablet_session_id": "inst-abc123",
    "score": 85,
    "max_score": 100,
    "cut_score": 70,
    "passed": true,
    "sections": [...],
    "report_url": "https://grading.example.com/reports/gs-abc123"
  }
}
```

**CloudEvent Handler Pattern (ADR-022):**

```
LDS / GradingEngine     lablet-controller              LabletSession
 │                    (CloudEventIngestor)                  │
 │ POST /cloudevents        │                                │
 │ (lds.session.started)    │                                │
 │───────────────────────▶│                                │
 │                          │ lookup by user_session_id      │
 │                          │──────────────────────────────▶│
 │                          │                                │
 │                          │ validate state == READY        │
 │                          │──────────────────────────────▶│
 │                          │                                │
 │                          │ transition READY → RUNNING     │
 │                          │──────────────────────────────▶│
 │                          │                                │
 │◀───────────────────────│ 202 Accepted                   │
```

#### FR-2.2.7: Collect and Grade Command

Collection and grading are triggered either by an external system (exam flow) or by CloudEvent from LDS (`lds.session.ended`). The lablet-controller orchestrates the flow via GradingSPI (per ADR-021, ADR-022):

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.2.7a | System SHALL expose `CollectAndGradeCommand` via control-plane-api | P0 |
| FR-2.2.7b | Command SHALL accept `session_id` as required parameter | P0 |
| FR-2.2.7c | Command SHALL validate LabletSession is in RUNNING state | P0 |
| FR-2.2.7d | Command SHALL transition LabletSession from RUNNING to COLLECTING | P0 |
| FR-2.2.7e | lablet-controller SHALL observe COLLECTING state and perform collection via GradingSPI | P0 |
| FR-2.2.7f | lablet-controller SHALL create **GradingSession** child entity with grading API references | P0 |
| FR-2.2.7g | After collection complete, system SHALL transition to GRADING | P0 |
| FR-2.2.7h | GradingEngine SHALL emit `grading.session.completed` CloudEvent upon completion | P1 |
| FR-2.2.7i | lablet-controller SHALL handle grading CloudEvent to create **ScoreReport** child entity | P1 |
| FR-2.2.7j | After grading complete, system SHALL transition to STOPPING | P0 |
| FR-2.2.7k | `lds.session.ended` CloudEvent SHALL also trigger CollectAndGrade flow | P1 |

**CollectAndGradeCommand Schema:**

```json
{
  "session_id": "sess-abc123",
  "collect_configs": true,
  "collect_logs": false,
  "grading_rubric_id": "rubric-xyz"
}
```

**Collect and Grade Flow (ADR-021, ADR-022):**

```
Trigger (API or CloudEvent)  control-plane-api     lablet-controller     GradingEngine
        │                         │                     │                    │
        │ POST CollectAndGrade    │                     │                    │
        │  or lds.session.ended   │                     │                    │
        │────────────────────────▶│                     │                    │
        │                         │                     │                    │
        │                         │ RUNNING → COLLECTING│                    │
        │                         │────────────────────▶│                    │
        │                         │                     │                    │
        │                         │ Observe COLLECTING  │                    │
        │                         │◀────────────────────│                    │
        │                         │                     │                    │
        │                         │  Collect configs from nodes via CML API  │
        │                         │                     │                    │
        │                         │  Create GradingSession entity            │
        │                         │  Submit via GradingSPI                   │
        │                         │                     │───────────────────▶│
        │                         │                     │                    │
        │                         │ COLLECTING → GRADING│                    │
        │                         │────────────────────▶│                    │
        │                         │                     │                    │
        │                         │                     │ grading.session    │
        │                         │                     │ .completed (CE)    │
        │                         │                     │◀───────────────────│
        │                         │                     │                    │
        │                         │  Create ScoreReport entity               │
        │                         │  Store score_report_id on LabletSession  │
        │                         │                     │                    │
        │                         │ GRADING → STOPPING  │                    │
        │                         │────────────────────▶│                    │
        │                         │                     │                    │
        │◀────────────────────────│ 202 Accepted        │                    │
```

!!! note "Asynchronous Processing"
    The `CollectAndGradeCommand` is acknowledged immediately (202 Accepted).
    Collection and grading are performed asynchronously by lablet-controller.
    Grading completion is signaled via `grading.session.completed` CloudEvent.
    Final results (ScoreReport) are available via query once GRADING completes.

---

### 2.3 Scheduling & Reservations

#### FR-2.3.1: Reservation Request

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.3.1a | System SHALL accept reservation requests with timeslot specification | P0 |
| FR-2.3.1b | System SHALL support "ASAP" scheduling (earliest available) | P0 |
| FR-2.3.1c | System SHALL support future-dated scheduling | P0 |
| FR-2.3.1d | System SHALL queue reservations when no capacity available | P0 |
| FR-2.3.1e | System SHALL NOT preempt running sessions for new reservations | P0 |

#### FR-2.3.2: Scheduling Algorithm

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.3.2a | Scheduler SHALL evaluate license affinity constraints | P0 |
| FR-2.3.2b | Scheduler SHALL evaluate resource requirements | P0 |
| FR-2.3.2c | Scheduler SHALL prefer workers with existing capacity (bin-packing) | P1 |
| FR-2.3.2d | Scheduler SHALL trigger scale-up when no suitable worker exists | P0 |
| FR-2.3.2e | Scheduler SHALL respect AMI requirements in definition | P1 |

#### FR-2.3.3: Scheduling Constraints

```
SCHEDULE(session) WHERE:
  worker.license_type IN session.definition.license_affinity
  AND worker.available_capacity >= session.definition.resource_requirements
  AND worker.available_nodes >= session.definition.node_count
  AND worker.ami MATCHES session.definition.ami_requirements
  AND worker.available_ports >= session.definition.port_count
```

---

### 2.4 Worker Capacity Management

#### FR-2.4.1: Capacity Model

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.4.1a | Worker capacity SHALL include: CPU cores, memory GB, storage GB | P0 |
| FR-2.4.1b | Worker capacity SHALL include: license type, max node count | P0 |
| FR-2.4.1c | Worker capacity SHALL be declared via Worker Template | P0 |
| FR-2.4.1d | Worker utilization SHALL be measured via CloudWatch + CML API | P0 |
| FR-2.4.1e | Available capacity = Declared capacity - Allocated capacity | P0 |

#### FR-2.4.2: Worker Template

```yaml
worker_template:
  name: "enterprise-large"
  instance_type: "m5zn.metal"
  capacity:
    cpu_cores: 48
    memory_gb: 192
    storage_gb: 500
  license_type: "ENTERPRISE"
  max_nodes: 500  # Enterprise = unlimited, but practical limit
  ami_pattern: "CML-2.9.*"
  region: "us-east-1"
  port_range:
    start: 2000
    end: 9999
```

#### FR-2.4.3: Capacity Tracking

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.4.3a | System SHALL track allocated capacity per running session | P0 |
| FR-2.4.3b | System SHALL update available capacity on session state changes | P0 |
| FR-2.4.3c | System SHALL track allocated ports per worker | P0 |
| FR-2.4.3d | System SHALL expose capacity metrics via API and SSE | P0 |

---

### 2.5 Auto-Scaling

#### FR-2.5.1: Scale-Up Triggers

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.5.1a | System SHALL scale up when scheduled sessions approach timeslot with no capacity | P0 |
| FR-2.5.1b | System SHALL scale up when pending queue exceeds threshold | P1 |
| FR-2.5.1c | System SHALL select appropriate worker template based on pending requirements | P0 |
| FR-2.5.1d | System SHALL account for worker startup time (≤15 minutes) in scheduling | P0 |

#### FR-2.5.2: Scale-Down Triggers

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.5.2a | System SHALL scale down workers with no running sessions | P0 |
| FR-2.5.2b | System SHALL scale down workers with no approaching scheduled sessions | P0 |
| FR-2.5.2c | System SHALL prefer stopping over terminating (faster restart) | P1 |
| FR-2.5.2d | System SHALL consolidate sessions to minimize running workers | P1 |

#### FR-2.5.3: Scaling Constraints

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.5.3a | System SHALL NOT scale down workers with active sessions | P0 |
| FR-2.5.3b | System SHALL honor minimum warm capacity (configurable) | P1 |
| FR-2.5.3c | System SHALL log all scaling decisions for audit | P0 |

---

### 2.6 Assessment Integration

Assessment integration uses the **GradingEngine** via a GradingSPI adapter in lablet-controller, with CloudEvent-driven asynchronous grading completion (per ADR-021, ADR-022).

#### FR-2.6.1: Collection Process

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.6.1a | System SHALL expose API to trigger collection for a LabletSession | P0 |
| FR-2.6.1b | System SHALL transition session to COLLECTING state | P0 |
| FR-2.6.1c | lablet-controller SHALL orchestrate collection via GradingSPI | P0 |
| FR-2.6.1d | Collection SHALL gather text output from lab node consoles via CML API | P0 |
| FR-2.6.1e | lablet-controller SHALL create **GradingSession** child entity during collection | P0 |
| FR-2.6.1f | GradingSession SHALL store `grading_session_id`, `grading_part_id`, `pod_id`, `devices` from GradingEngine | P0 |

#### FR-2.6.2: Grading Process

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.6.2a | System SHALL transition to GRADING after collection completes | P0 |
| FR-2.6.2b | GradingEngine SHALL emit `grading.session.completed` CloudEvent upon completion | P0 |
| FR-2.6.2c | lablet-controller SHALL handle grading CloudEvent via CloudEventIngestor (ADR-022) | P0 |
| FR-2.6.2d | lablet-controller SHALL create **ScoreReport** child entity from grading results | P0 |
| FR-2.6.2e | ScoreReport SHALL include: `score`, `max_score`, `cut_score`, `passed`, `sections[]`, `report_url` | P0 |
| FR-2.6.2f | System SHALL store `score_report_id` FK on LabletSession | P0 |
| FR-2.6.2g | System SHALL transition to STOPPING after grading completes | P0 |
| FR-2.6.2h | System SHALL handle `grading.session.failed` CloudEvent for error recovery | P1 |

#### FR-2.6.3: CloudEvent Integration

**Events Emitted by LCM:**

| Event Type | Trigger | Consumers |
|------------|---------|-----------|
| `ccm.lablet.session.created` | Session created | LDS, Audit |
| `ccm.lablet.session.ready` | Infrastructure provisioned, awaiting user | LDS, Assessment |
| `ccm.lablet.session.running` | User logged in | Assessment, Audit |
| `ccm.lablet.session.collecting` | Collection started | GradingEngine |
| `ccm.lablet.session.grading` | Grading in progress | Audit |
| `ccm.lablet.session.terminated` | Resources released | Audit, Billing |
| `ccm.worker.scaled.up` | New worker started | Audit |
| `ccm.worker.scaled.down` | Worker stopped | Audit |

**Events Consumed by LCM (via lablet-controller CloudEventIngestor — ADR-022):**

| Event Type | Source | Action |
|------------|--------|--------|
| `lds.session.started` | LDS | Transition READY → RUNNING, update UserSession |
| `lds.session.ended` | LDS | Trigger CollectAndGrade flow, update UserSession |
| `grading.session.completed` | GradingEngine | Create ScoreReport, transition GRADING → STOPPING |
| `grading.session.failed` | GradingEngine | Error handling, transition GRADING → STOPPING |

---

### 2.7 Warm Pool (Pre-Provisioning)

#### FR-2.7.1: Warm Lablet Management

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.7.1a | System SHALL maintain warm pool per LabletDefinition (if configured) | P2 |
| FR-2.7.1b | Warm pool = labs imported and stopped (not started) | P2 |
| FR-2.7.1c | System SHALL start warm lab instead of importing new | P2 |
| FR-2.7.1d | System SHALL replenish warm pool after consumption | P2 |

---

## 3. Non-Functional Requirements

### 3.1 Performance

| ID | Requirement | Target | Priority |
|----|-------------|--------|----------|
| NFR-3.1.1 | API response time (p95) | < 500ms | P0 |
| NFR-3.1.2 | Scheduling decision time | < 5s | P0 |
| NFR-3.1.3 | Session instantiation time | < 3min (excl. worker startup) | P0 |
| NFR-3.1.4 | Concurrent sessions supported | ≥ 1000 | P0 |
| NFR-3.1.5 | Concurrent workers per region | ≥ 100 | P0 |

### 3.2 Availability

| ID | Requirement | Target | Priority |
|----|-------------|--------|----------|
| NFR-3.2.1 | API availability | 99.9% | P0 |
| NFR-3.2.2 | Scheduler availability | 99.9% | P0 |
| NFR-3.2.3 | Recovery Time Objective (RTO) | < 2 minutes | P0 |
| NFR-3.2.4 | No single point of failure for control plane | Required | P0 |

### 3.3 Scalability

| ID | Requirement | Target | Priority |
|----|-------------|--------|----------|
| NFR-3.3.1 | Horizontal scaling for API | Required | P0 |
| NFR-3.3.2 | Horizontal scaling for Scheduler | Required | P0 |
| NFR-3.3.3 | Worker startup time tolerance | ≤ 15 minutes | P0 |

### 3.4 Security

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-3.4.1 | All API endpoints require authentication | P0 |
| NFR-3.4.2 | RBAC for definition/session operations | P0 |
| NFR-3.4.3 | Audit logging for all state changes | P0 |
| NFR-3.4.4 | Secrets (AWS credentials) encrypted at rest | P0 |

### 3.5 Observability

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-3.5.1 | OpenTelemetry traces for all operations | P0 |
| NFR-3.5.2 | Prometheus metrics for business KPIs | P0 |
| NFR-3.5.3 | Structured logging with correlation IDs | P0 |
| NFR-3.5.4 | Real-time SSE dashboard | P0 |
| NFR-3.5.5 | Audit log retention: minimum 3 months, maximum 1 year | P0 |

### 3.6 Maintainability

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-3.6.1 | Cloud Provider abstraction via SPI | P1 |
| NFR-3.6.2 | Configuration-driven worker templates | P0 |
| NFR-3.6.3 | Feature flags for gradual rollout | P2 |

---

## 4. Constraints & Assumptions

### 4.1 Constraints

| ID | Constraint |
|----|------------|
| C-1 | AWS m5zn.metal instances required (nested virtualization) |
| C-2 | Worker startup time: up to 15 minutes |
| C-3 | CML licenses are tied to individual workers |
| C-4 | Port range 2000-9999 per worker |
| C-5 | Initial deployment: AWS only (SPI for future multi-cloud) |
| C-6 | LDS (Lab Delivery System) required for user-facing lab sessions |
| C-7 | GradingEngine required for automated grading; accessed via GradingSPI adapter in lablet-controller |

### 4.2 Assumptions

| ID | Assumption |
|----|------------|
| A-1 | GradingEngine provides REST API (GradingSPI) for collection orchestration |
| A-2 | GradingEngine and LDS emit CloudEvents consumed by lablet-controller (ADR-022) |
| A-3 | Lab YAML artifacts managed externally in S3/MinIO |
| A-4 | Users book reservations in advance (not purely on-demand) |
| A-5 | Region isolation acceptable (no cross-region failover) |
| A-6 | LDS provides synchronous REST API for session management |
| A-7 | Content packages (content.xml, cml.yaml) conform to defined schema |

---

## 5. Glossary

| Term | Definition |
|------|------------|
| **LabletDefinition** | Immutable, versioned template for a lab environment |
| **LabletSession** | Runtime session of a LabletDefinition on a Worker (CML lab + LDS LabSession + child entities). Renamed from LabletInstance per ADR-020 |
| **Worker** | AWS EC2 instance running CML (compute node) |
| **Timeslot** | Reserved time window for a LabletSession |
| **Warm Pool** | Pre-provisioned (imported, stopped) labs for fast startup |
| **Capacity** | Available compute resources on a Worker |
| **License Affinity** | Constraint matching definitions to compatible license types |
| **LDS** | Lab Delivery System - user-facing web UI for lab interaction |
| **LabSession** | LDS container for user lab experience (states: EMPTY → PENDING → RUNNING → ARCHIVED) |
| **LabSessionPart** | Component of LabSession linking to specific content/tasks |
| **form_qualified_name** | Globally unique content identifier shared across LCM, LDS, and S3/MinIO |
| **content.xml** | XML file defining devices, UI layout, and access modes for LDS |
| **Device Access Info** | Connection details (protocol, host, port, credentials) for lab devices |
| **UserSession** | Child entity of LabletSession storing LDS session details (lds_session_id, login_url, devices). Separate MongoDB collection per ADR-021 |
| **GradingSession** | Child entity of LabletSession storing GradingEngine session details (grading_session_id, pod_id, devices). Separate MongoDB collection per ADR-021 |
| **ScoreReport** | Child entity of LabletSession storing grading results (score, max_score, cut_score, passed, sections). Separate MongoDB collection per ADR-021 |
| **LabRecord** | CML lab instance on a worker, bound 1:1 to LabletSession (absorbed from LabletLabBinding per ADR-020) |
| **GradingSPI** | Service Provider Interface adapter in lablet-controller for GradingEngine REST API |
| **CloudEventIngestor** | Neuroglia pattern for receiving and dispatching CloudEvents in lablet-controller (ADR-022) |
| **GradingEngine** | External system for automated grading of lab configurations |

---

## 6. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-01-15 | Architecture Team | Initial draft |
| 0.2.0 | 2026-02-08 | Architecture Team | Added LDS integration (FR-2.1.6, FR-2.2.5), form_qualified_name attribute |
| 0.3.0 | 2026-02-08 | Architecture Team | Added READY state, CloudEvent handling (FR-2.2.6), CollectAndGrade command (FR-2.2.7) |
| 0.4.0 | 2026-02-18 | Architecture Team | Renamed LabletInstance → LabletSession (ADR-020). Added child entities: UserSession, GradingSession, ScoreReport (ADR-021). CloudEvent routing to lablet-controller via CloudEventIngestor (ADR-022). Rewrote assessment integration for GradingEngine/GradingSPI. Updated CloudEvent catalog (ccm.lablet.session.*). Updated glossary with new terms. |
