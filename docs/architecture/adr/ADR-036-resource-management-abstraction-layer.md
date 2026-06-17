# ADR-036: Resource Management Abstraction Layer

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed (Revision 3) |
| **Date** | 2026-03-05 (revised 2026-03-08, 2026-06-12) |
| **Deciders** | Architecture Team |
| **Extends** | [ADR-034](./ADR-034-pipeline-executor-lifecycle-handlers.md) (Pipeline Executor), [ADR-020](./ADR-020-session-entity-model.md) (Session Entity Model) |
| **Related ADRs** | [ADR-001](./ADR-001-api-centric-state-management.md) (API-Centric State), [ADR-005](./ADR-005-state-store-architecture.md) (Dual Storage), [ADR-011](./ADR-011-apscheduler-removal.md) (APScheduler Removal), [ADR-031](./ADR-031-checkpoint-instantiation-pipeline.md) (Checkpoint Pipeline), [ADR-045](./ADR-045-multi-part-session-part-model.md) (Multi-part Sessions), [ADR-046](./ADR-046-host-abstraction-and-pod-host-type-split.md) (Host Abstraction), [ADR-047](./ADR-047-generic-reconciliation-framework.md) (Reconciliation Framework) |
| **Revision Notes** | R2: Adds TimedResource/Timeslot/ManagedLifecycle abstraction layer (§2.1.4–§2.1.7); updates Phase 1 status; refines abstraction boundary based on LabletSession/CMLWorker/LabRecord analysis. **R3**: Generalizes the abstraction into a **nested TimedResource tree** — `SessionPart` and `PodInstance` become first-class TimedResources and a generic `Host`/`Worker` layer is introduced (§2.6). The single `ResourceSession` becomes a `Session` profile; multi-part sessions are now first-class. |

---

## 1. Context

### 1.1 Problem Statement

The Lablet Cloud Manager currently manages a single resource type — `LabletSession` — through a
monolithic 12-state lifecycle with hardcoded pipeline steps. As the platform matures, it must
support **multiple resource types** (ExpertLabSession, PracticeLabSession, DemoSession,
ExpertDesignSession, TestSession, BYOLSession) with **distinct lifecycle behaviors**,
**pluggable execution strategies** (internal DAG pipelines + external Serverless Workflow via
Synapse), and **full-stack event-driven reactivity** from domain events through to the frontend
SSE stream.

### 1.2 Current State

| Aspect | Current Implementation | Limitation |
|--------|----------------------|------------|
| **Resource types** | Single `LabletSession` aggregate | Cannot model resource-type-specific behaviors (e.g., BYOL skips scheduling, Demo has no grading) |
| **Lifecycle** | 12-state enum hardcoded in `LabletSessionStatus` | All session types share identical state machine |
| **Execution** | `PipelineExecutor` (ADR-034) — internal DAG engine | No external workflow orchestration; step handlers hardcoded on reconciler |
| **Pipeline events** | Progress persisted to CPA but no domain events emitted | No SSE real-time pipeline progress; no etcd projection for pipeline state |
| **Definition model** | `LabletDefinition` with `pipelines: dict` | One definition type, no resource-type polymorphism |
| **Intent** | Imperative `CreateLabletSessionCommand` | No desired-state tracking; cannot express "reserve 3 timeslot sessions" vs "create 3 running sessions now" |
| **Storage** | Single `lablet_sessions` MongoDB collection | All types co-mingled |

### 1.3 Goals

1. **Concrete resource subtypes** — each with dedicated aggregate, MongoDB collection, events, and lifecycle
2. **Dual execution strategy** — internal `PipelineExecutor` + external `WorkflowExecutor` (Synapse delegation)
3. **Desired-state tracking** — `desired_status` field enabling declarative intent (expandable to richer `Intent` sub-entity later)
4. **Pipeline domain events** — first-class events flowing through the existing mediator → etcd projector → SSE relay chain
5. **Full-stack reactivity** — domain events to frontend EventBus in real-time
6. **Phased implementation** — complete functional implementation first, then add abstraction layer

---

## 2. Decision

### 2.1 Concrete Resource Subtypes (Option A)

Each resource type is a **separate aggregate** with its own MongoDB collection, domain events,
repository, commands, and queries. A shared abstract base provides common lifecycle infrastructure.

#### 2.1.1 Resource Type Hierarchy

```
                    ┌─────────────────────┐
                    │  ResourceDefinition │  (abstract concept in docs,
                    │  ─────────────────  │   LabletDefinition is the
                    │  resource_type      │   concrete aggregate for now)
                    │  pipelines          │
                    │  workflows          │
                    └─────────┬───────────┘
                              │ defines
                              ▼
                    ┌─────────────────────┐
                    │   ResourceSession   │  (abstract base class)
                    │  ─────────────────  │
                    │  definition_id      │
                    │  resource_type      │
                    │  status             │
                    │  desired_status     │
                    │  state_history[]    │
                    │  pipeline_progress  │
                    └─────────┬───────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
    ┌─────▼──────┐   ┌───────▼────────┐  ┌───────▼────────┐
    │ LabletSess │   │ExpertLabSess   │  │ DemoSession    │   ...
    │ ───────────│   │────────────────│  │────────────────│
    │ + grading  │   │ + design_tools │  │ + demo_config  │
    │ + LDS      │   │ + rubric       │  │ - no grading   │
    │ + scoring  │   │ + peer_review  │  │ - no LDS       │
    └────────────┘   └────────────────┘  └────────────────┘
```

#### 2.1.2 Initial Resource Types

| Resource Type | Collection | Grading | LDS | Scheduling | Key Differentiator |
|---------------|-----------|---------|-----|------------|-------------------|
| `LabletSession` | `lablet_sessions` | ✅ | ✅ | ✅ | Full lifecycle — exam/certification lab |
| `ExpertLabSession` | `expert_lab_sessions` | ✅ | ✅ | ✅ | Expert-level with advanced rubric |
| `ExpertDesignSession` | `expert_design_sessions` | ✅ | ✅ | ✅ | Design tasks with topology creation |
| `PracticeLabSession` | `practice_lab_sessions` | Optional | ✅ | ✅ | Self-paced, no time pressure |
| `DemoSession` | `demo_sessions` | ❌ | ❌ | ✅ | Quick-start, no grading or LDS |
| `TestSession` | `test_sessions` | ✅ | Optional | ✅ | Internal testing/validation |
| `BYOLSession` | `byol_sessions` | ❌ | ❌ | ❌ | Bring-your-own-lab — user provides CML lab, skip scheduling + import |

#### 2.1.3 Event Layering

Events are emitted at **two layers** — resource-level (shared) and session-type-level (specific):

```
Resource-Level Events (shared base)               Session-Type Events (specific)
─────────────────────────────────                  ────────────────────────────────
resource.session.created.v1                        lablet.session.created.v1
resource.session.status_changed.v1                 expert_lab.session.created.v1
resource.session.desired_status_set.v1             demo.session.created.v1
resource.pipeline.started.v1                       lablet.session.grading_completed.v1
resource.pipeline.step_completed.v1                expert_design.session.design_submitted.v1
resource.pipeline.completed.v1                     byol.session.lab_attached.v1
resource.pipeline.failed.v1                        test.session.validation_passed.v1
resource.pipeline.retry.v1
```

**Flow**: The concrete aggregate emits type-specific domain events. The Neuroglia mediator
dispatches to **NotificationHandlers** that handle both:

- **Type-specific handlers** (e.g., `LabletSessionCreatedDomainEventHandler` → SSE `lablet.session.created`)
- **Shared pipeline handlers** (e.g., `PipelineStepCompletedHandler` → SSE `resource.pipeline.step_completed`)

#### 2.1.4 Three-Layer Abstraction Model (Revision 2)

The original ADR proposed a flat `ResourceSessionState` base class. Analysis of the three
existing aggregates — `CMLWorker`, `LabRecord`, and `LabletSession` — reveals that all three
share a deeper commonality: they are **time-bounded resources with managed lifecycles**. This
leads to a three-layer type hierarchy:

```
Resource (abstract)             ← Kubernetes-like spec/status, desired_status, state_history
  └── TimedResource (abstract)  ← + Timeslot (start/end/lead-time/teardown), ManagedLifecycle
        ├── CMLWorker           ← 24h max, licensing pipeline, idle-detection
        ├── LabRecord           ← 24h max, boot/wipe/teardown pipelines
        └── LabletSession       ← 24h max, 120min timeslot, full assessment lifecycle
              ├── ExpertLabSession
              ├── DemoSession
              └── ...
```

##### Layer 1: Resource (Spec vs Status)

The foundational abstraction, aligned with Neuroglia ROA patterns
(see [pyneuro ROA docs](https://bvandewe.github.io/pyneuro/patterns/resource-oriented-architecture/)):

```python
# lcm_core/domain/value_objects/state_transition.py (already exists)

@dataclass(frozen=True)
class StateTransition:
    from_state: str | None
    to_state: str
    transitioned_at: datetime
    triggered_by: str
    reason: str | None = None
    metadata: dict[str, Any] | None = None
```

```python
# lcm_core/domain/entities/resource.py (new — Phase 2)

class ResourceState(AggregateState[str]):
    """Base state for all managed resources (Kubernetes-like spec/status)."""

    id: str
    resource_type: str              # Discriminator: "cml_worker" | "lab_record" | "lablet" | ...
    status: str                     # Actual state (status)
    desired_status: str | None      # Desired state (spec) — reconciliation target (§2.2)
    owner_id: str                   # Who owns this resource

    state_history: list[StateTransition]    # Audit trail of transitions
    pipeline_progress: dict | None          # Per-pipeline progress: {"instantiate": {...}, ...}

    created_at: datetime
    updated_at: datetime
```

**What belongs here** (confirmed by field analysis across all 3 aggregates):

| Field | CMLWorker | LabRecord | LabletSession | → Resource? |
|-------|-----------|-----------|---------------|-------------|
| `id` | ✅ | ✅ | ✅ | ✅ Yes |
| `status` | ✅ (CMLWorkerStatus) | ✅ (LabRecordStatus) | ✅ (LabletSessionStatus) | ✅ Yes (str) |
| `desired_status` | ✅ | ❌ (not yet) | ✅ | ✅ Yes |
| `state_history` | ❌ (not yet) | ❌ (not yet) | ✅ | ✅ Yes (promote) |
| `pipeline_progress` | ❌ | ❌ | ✅ | ✅ Yes (promote) |
| `created_at` / `updated_at` | ✅ | ✅ | ✅ | ✅ Yes |
| `owner_id` | ✅ (`created_by`) | ✅ (`owner_username`) | ✅ | ✅ Yes (normalize) |

##### Layer 2: TimedResource (Timeslot + ManagedLifecycle)

A `TimedResource` adds **time-bounded execution** and **managed lifecycle phases**:

```python
# lcm_core/domain/value_objects/timeslot.py (new — Phase 2)

@dataclass(frozen=True)
class Timeslot:
    """Time window during which a resource is active.

    Timeslots define both the user-visible window (start → end) and the
    operational margins needed for preparation and teardown.

    Timeline:
        |--lead_time--|------- active window -------|--teardown_buffer--|
        ^             ^                             ^                   ^
      provision     start                          end              cleanup
      begins       (ready)                       (user done)       complete
    """
    start: datetime                       # When the resource should be ready
    end: datetime                         # When the user session ends
    lead_time: timedelta = timedelta(minutes=15)    # Provisioning lead time
    teardown_buffer: timedelta = timedelta(minutes=10)  # Cleanup buffer after end

    @property
    def provision_at(self) -> datetime:
        """When provisioning must begin to be ready by start."""
        return self.start - self.lead_time

    @property
    def cleanup_deadline(self) -> datetime:
        """Hard deadline by which teardown must complete."""
        return self.end + self.teardown_buffer

    @property
    def duration(self) -> timedelta:
        """Active window duration (start → end)."""
        return self.end - self.start

    @property
    def total_duration(self) -> timedelta:
        """Total time including lead-time and teardown."""
        return self.cleanup_deadline - self.provision_at

    def is_active(self, now: datetime | None = None) -> bool:
        """True if within the active window."""
        now = now or datetime.now(timezone.utc)
        return self.start <= now <= self.end

    def is_expired(self, now: datetime | None = None) -> bool:
        """True if past the active window end."""
        now = now or datetime.now(timezone.utc)
        return now > self.end

    def remaining(self, now: datetime | None = None) -> timedelta:
        """Time remaining in the active window."""
        now = now or datetime.now(timezone.utc)
        return max(timedelta(0), self.end - now)

    def extend(self, new_end: datetime) -> "Timeslot":
        """Return new Timeslot with extended end time."""
        if new_end <= self.end:
            raise ValueError("new_end must be after current end")
        return Timeslot(
            start=self.start,
            end=new_end,
            lead_time=self.lead_time,
            teardown_buffer=self.teardown_buffer,
        )
```

```python
# lcm_core/domain/value_objects/managed_lifecycle.py (new — Phase 2)

@dataclass(frozen=True)
class LifecyclePhase:
    """A single lifecycle phase with its execution strategy.

    Each phase maps to either a PipelineExecutor (internal DAG) or a
    WorkflowExecutor (external Synapse delegation). See §2.3.
    """
    name: str                           # e.g., "instantiate", "teardown", "collect_evidence"
    engine: str = "pipeline"            # "pipeline" | "workflow"
    trigger_on_status: str | None = None  # Status that triggers this phase
    pipeline_def: dict | None = None    # Step definitions for PipelineExecutor
    workflow_ref: dict | None = None    # {namespace, name, version} for WorkflowExecutor
    is_required: bool = True            # If False, phase can be skipped per resource type

@dataclass(frozen=True)
class ManagedLifecycle:
    """Ordered set of lifecycle phases for a resource type.

    Defines which pipelines/workflows execute during each lifecycle
    transition. A LabletSession might have: instantiate → collect_evidence
    → compute_grading → teardown. A CMLWorker might have: provision →
    license_register → teardown → license_deregister.
    """
    phases: dict[str, LifecyclePhase]   # Keyed by phase name
    current_phase: str | None = None    # Currently executing phase

    def get_phase(self, name: str) -> LifecyclePhase | None:
        return self.phases.get(name)

    def get_active_phases(self) -> list[LifecyclePhase]:
        return [p for p in self.phases.values() if p.is_required]

    def phase_names(self) -> list[str]:
        return list(self.phases.keys())
```

```python
# lcm_core/domain/entities/timed_resource.py (new — Phase 2)

class TimedResourceState(ResourceState):
    """State for time-bounded resources with managed lifecycles.

    All LCM-managed resources are TimedResources:
    - CMLWorker: 24h max, may require licensing, monitor-resources, clean-up
    - LabRecord: 24h max, may require boot-up, wipe-out, teardown
    - LabletSession: 24h max, typically 120min user timeslot,
      with creation → instantiation → collect-and-grade → archive → restore
    """

    # Time-bounded execution
    timeslot: Timeslot                  # When this resource is active

    # Lifecycle management
    lifecycle: ManagedLifecycle | None  # Phases and their execution strategies

    # Runtime tracking
    started_at: datetime | None         # When resource became active
    ended_at: datetime | None           # When resource finished
    duration_seconds: float | None      # Computed on completion
    terminated_at: datetime | None      # Force-termination timestamp
```

**What belongs in TimedResource vs Resource** (validated against concrete aggregates):

| Field | In Resource | In TimedResource | Concrete-only |
|-------|-------------|------------------|---------------|
| `id`, `resource_type`, `status`, `desired_status` | ✅ | | |
| `owner_id`, `created_at`, `updated_at` | ✅ | | |
| `state_history`, `pipeline_progress` | ✅ | | |
| `timeslot` (start/end/lead/teardown) | | ✅ | |
| `lifecycle` (phases) | | ✅ | |
| `started_at`, `ended_at`, `duration_seconds` | | ✅ | |
| `terminated_at` | | ✅ | |
| `worker_id`, `allocated_ports` | | | LabletSession |
| `lab_record_id`, `cml_lab_id` | | | LabletSession |
| `user_session_id`, `grading_session_id` | | | LabletSession |
| `aws_instance_id`, `instance_type`, `metrics` | | | CMLWorker |
| `runtime_binding`, `topology_spec` | | | LabRecord |

##### Layer 3: Concrete Resource Types

Each concrete type extends `TimedResourceState` with domain-specific fields.
The existing implementations remain as-is — the abstraction is **extracted** from
them, not imposed on them:

```python
# In control-plane-api/domain/entities/lablet_session.py (existing, updated)

class LabletSessionState(TimedResourceState):
    """Concrete state for LabletSession — extends TimedResource."""

    # Definition reference (pinned at creation)
    definition_id: str
    definition_name: str
    definition_version: str

    # Lab binding
    worker_id: str | None
    lab_record_id: str | None
    cml_lab_id: str | None
    allocated_ports: dict[str, int] | None

    # Child entity FKs (ADR-021)
    user_session_id: str | None
    grading_session_id: str | None
    score_report_id: str | None
    grade_result: str | None

    # Resource observation (ADR-030)
    observed_resources: dict | None
    observed_ports: dict[str, int] | None
    port_drift_detected: bool
    observation_count: int
    observed_at: datetime | None
```

#### 2.1.5 Concrete Resource Mapping — CMLWorker as TimedResource

CMLWorker fields map to the TimedResource abstraction as follows:

| CMLWorker field | Maps to TimedResource field | Notes |
|---|---|---|
| `status` (CMLWorkerStatus) | `status` | Enum → str at abstract level |
| `desired_status` (CMLWorkerStatus) | `desired_status` | Already implemented |
| `created_at` / `updated_at` | `created_at` / `updated_at` | Direct |
| `created_by` | `owner_id` | Normalized naming |
| _(no field)_ | `timeslot` | **New**: 24h max window from creation |
| _(no field)_ | `lifecycle` | **New**: provision → license_register → teardown phases |
| `start_initiated_at` | `started_at` | Normalize |
| `terminated_at` | `terminated_at` | Direct |

**CMLWorker Lifecycle Phases** (to be expressed as `ManagedLifecycle`):

```yaml
lifecycle:
  phases:
    provision:
      engine: pipeline
      trigger_on_status: pending
      steps: [launch_ec2, wait_running, configure_cml]
    license_register:
      engine: pipeline
      trigger_on_status: running
      steps: [request_license, apply_license, verify_license]
      is_required: false  # Only when license required
    monitor_resources:
      engine: pipeline
      trigger_on_status: running
      steps: [collect_ec2_metrics, collect_cml_metrics, check_capacity]
    teardown:
      engine: pipeline
      trigger_on_status: stopping
      steps: [drain_sessions, deregister_license, stop_instance]
    terminate:
      engine: pipeline
      trigger_on_status: terminating
      steps: [terminate_instance, cleanup_resources]
```

#### 2.1.6 Concrete Resource Mapping — LabRecord as TimedResource

| LabRecord field | Maps to TimedResource field | Notes |
|---|---|---|
| `status` (LabRecordStatus) | `status` | Enum → str at abstract level |
| _(not yet)_ | `desired_status` | **New**: enables declarative lab management |
| `first_seen_at` | `created_at` | Normalize |
| `modified_at` | `updated_at` | Direct |
| `owner_username` | `owner_id` | Normalized naming |
| _(no field)_ | `timeslot` | **New**: derived from parent session timeslot |
| _(no field)_ | `lifecycle` | **New**: import → start → wipe → teardown phases |

**LabRecord Lifecycle Phases**:

```yaml
lifecycle:
  phases:
    import:
      engine: pipeline
      trigger_on_status: importing
      steps: [upload_topology, create_lab, verify_nodes]
    boot:
      engine: pipeline
      trigger_on_status: starting
      steps: [start_nodes, wait_booted, verify_connectivity]
    wipe:
      engine: pipeline
      trigger_on_status: wiping
      steps: [stop_nodes, wipe_configs, verify_clean]
    teardown:
      engine: pipeline
      trigger_on_status: deleting
      steps: [stop_nodes, delete_lab, release_resources]
```

#### 2.1.7 Concrete Resource Mapping — LabletSession as TimedResource

The primary reference implementation (already the most mature):

| LabletSession field | Maps to TimedResource field | Notes |
|---|---|---|
| `status` (LabletSessionStatus) | `status` | Direct |
| `desired_status` | `desired_status` | Already implemented |
| `timeslot_start` / `timeslot_end` | `timeslot.start` / `timeslot.end` | Consolidated into VO |
| _(hardcoded 15min)_ | `timeslot.lead_time` | Now configurable |
| _(not tracked)_ | `timeslot.teardown_buffer` | **New**: explicit teardown window |
| `state_history` | `state_history` | Direct |
| `pipeline_progress` | `pipeline_progress` | Direct |
| `started_at` / `ended_at` | `started_at` / `ended_at` | Direct |
| `duration_seconds` | `duration_seconds` | Direct |
| `terminated_at` | `terminated_at` | Direct |
| `created_at` | `created_at` | Direct |
| `owner_id` | `owner_id` | Direct |

**LabletSession Lifecycle Phases** (current implementation):

```yaml
lifecycle:
  phases:
    instantiate:
      engine: pipeline
      trigger_on_status: instantiating
      steps: [import_lab, start_lab, bind_lab, register_lab_record, create_user_session]
    collect_evidence:
      engine: workflow  # Future: Synapse delegation
      trigger_on_status: collecting
      steps: [capture_configs, capture_screenshots, package_evidence]
      is_required: false  # DemoSession skips this
    compute_grading:
      engine: workflow  # Future: Synapse delegation
      trigger_on_status: grading
      steps: [evaluate_rubric, compute_score, record_result]
      is_required: false  # DemoSession, PracticeLabSession skip
    teardown:
      engine: pipeline
      trigger_on_status: stopping
      steps: [stop_lab, wipe_lab, release_ports, cleanup_resources]
```

**Phase 1 (immediate)**: `LabletSession` remains the sole concrete aggregate. New types are added
incrementally as separate aggregates that follow the same patterns.

**Phase 2 (abstraction)**: Extract `Resource` → `TimedResource` hierarchy into `lcm_core` and have
all aggregates inherit shared lifecycle infrastructure.

#### 2.1.5 Storage Model

Each resource type gets its own MongoDB collection:

```
MongoDB Collections (per resource type):
├── lablet_sessions          ← existing, unchanged
├── expert_lab_sessions      ← new
├── expert_design_sessions   ← new
├── practice_lab_sessions    ← new
├── demo_sessions            ← new
├── test_sessions            ← new
└── byol_sessions            ← new

etcd Key Prefixes (per resource type):
├── /lcm/sessions/lablet/{id}/state
├── /lcm/sessions/expert_lab/{id}/state
├── /lcm/sessions/demo/{id}/state
└── /lcm/sessions/byol/{id}/state
```

Each collection has its own repository interface and Mongo implementation, following the
existing `LabletSessionRepository` → `MongoLabletSessionRepository` pattern.

---

### 2.2 Desired-State Tracking

Add `desired_status` as a first-class field on session aggregates, enabling declarative
reconciliation alongside the existing imperative state machine.

#### 2.2.1 Immediate: `desired_status` Field

```python
class LabletSessionState:
    status: str                     # Current actual status (existing)
    desired_status: str | None      # What the user/system wants (NEW)
```

**Reconciliation logic** — the controller compares `desired_status` vs `status`:

```
if desired_status is set AND desired_status != status:
    → determine required transitions to reach desired_status
    → execute pipeline for current status → next status
    → repeat until desired_status == status or error
```

**Examples**:

| User Action | `desired_status` | `status` | Reconciler Behavior |
|------------|-----------------|----------|---------------------|
| "Create session" | `RUNNING` | `PENDING` | Schedule → Instantiate → Ready → Running |
| "Reserve for later" | `SCHEDULED` | `PENDING` | Schedule only, wait for timeslot |
| "Stop session" | `STOPPED` | `RUNNING` | Stop → Stopped |
| "Terminate" | `TERMINATED` | `RUNNING` | Terminate immediately |

**Domain event**: `ResourceSessionDesiredStatusSetDomainEvent` → etcd projector writes
`/lcm/sessions/{type}/{id}/desired_status` → controller watches and reconciles.

#### 2.2.2 Future: Rich Intent Sub-Entity

The `desired_status` field is designed to be **replaced or augmented** by a richer `Intent`
value object in a future phase:

```python
# Future Phase — NOT implemented now, documented for forward planning
@dataclass(frozen=True)
class SessionIntent:
    """Declarative specification of what the user wants."""
    expected_state: str                     # Target lifecycle state
    quantity: int = 1                       # Batch creation support
    scheduling_mode: str = "on_demand"      # "on_demand" | "timeslot" | "warm_pool"
    timeslot_spec: TimeslotSpec | None = None
    priority: str = "normal"                # "low" | "normal" | "high"
    constraints: dict | None = None         # Resource/affinity constraints
```

This would enable commands like:

- `create_lablet_session(definition, intent={expected_state: "RUNNING", quantity: 3, scheduling_mode: "timeslot", timeslot_spec: {...}})`
- `create_demo_session(definition, intent={expected_state: "RUNNING", scheduling_mode: "on_demand"})`

**Migration path**: `desired_status` → `intent.expected_state` with backward compatibility.

---

### 2.3 Dual Execution Strategy

The lifecycle phase management supports two pluggable execution strategies. The
`LifecyclePhaseHandler` (ADR-034) selects the strategy based on the pipeline definition.

#### 2.3.1 Strategy Selection

```yaml
# In LabletDefinition.pipelines:
pipelines:
  instantiate:
    engine: "pipeline"              # ← Uses PipelineExecutor (internal)
    steps: [...]

  collect_evidence:
    engine: "workflow"              # ← Uses WorkflowExecutor (Synapse delegation)
    workflow_ref:
      namespace: "lcm"
      name: "collect-evidence"
      version: "0.1.0"
    input_mapping:                  # jq-like mapping of context → workflow input
      session_id: "$SESSION.id"
      worker_ip: "$WORKER.ip"
      lab_id: "$SESSION.lab_record_id"
```

#### 2.3.2 PipelineExecutor (Internal — existing, ADR-034)

No changes to the existing `PipelineExecutor`. It remains the default strategy for
deterministic, step-by-step DAG execution with `simpleeval` skip_when expressions.

| Aspect | PipelineExecutor |
|--------|-----------------|
| **Runtime** | In-process Python asyncio |
| **Step dispatch** | `_step_{handler}()` methods on reconciler |
| **State** | Progress persisted to CPA after each step |
| **Recovery** | Resume from last completed step |
| **Expression language** | `simpleeval` (Python-like) |
| **Best for** | Deterministic lifecycle phases with known steps |

#### 2.3.3 WorkflowExecutor (External — Synapse delegation)

The `WorkflowExecutor` delegates **entirely** to Synapse via its REST API. It does NOT
interpret Serverless Workflow DSL locally — it creates a workflow instance in Synapse and
monitors it for completion.

| Aspect | WorkflowExecutor |
|--------|-----------------|
| **Runtime** | External Synapse server (C#/.NET) |
| **Orchestration** | CNCF Serverless Workflow DSL (jq expressions, CloudEvents) |
| **State** | Managed by Synapse; LCM polls/watches for status |
| **Recovery** | Synapse handles internally; LCM reconnects on restart |
| **Expression language** | jq (Serverless Workflow standard) |
| **Best for** | Complex cross-service choreography, conditional branching, event-driven workflows |

##### Synapse Integration Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    LABLET CONTROLLER                              │
│                                                                  │
│  LifecyclePhaseHandler                                           │
│    │                                                             │
│    ├── engine == "pipeline" → PipelineExecutor (existing)        │
│    │                                                             │
│    └── engine == "workflow" → WorkflowExecutor                   │
│         │                                                        │
│         ├── 1. Create workflow instance via Synapse API           │
│         ├── 2. Monitor instance via SSE watch endpoint            │
│         ├── 3. Relay progress events to CPA                      │
│         └── 4. On completion/failure → return result to handler   │
│                                                                  │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    SYNAPSE SERVER                                 │
│                                                                  │
│  POST /api/v1/workflow-instances                                 │
│    → Creates runner, executes workflow                           │
│                                                                  │
│  GET  /api/v1/workflow-instances/{ns}/{name}/monitor/sse         │
│    → Real-time status + task progress stream                     │
│                                                                  │
│  POST /api/v1/events                                             │
│    → CloudEvent ingestion for correlation/callback               │
│                                                                  │
│  PUT  /api/v1/workflow-instances/{ns}/{name}/cancel              │
│    → Graceful cancellation on leader step-down                   │
│                                                                  │
│  Workflow tasks can call back to LCM services:                   │
│    call: http                                                    │
│      with:                                                       │
│        method: post                                              │
│        endpoint: { uri: "http://control-plane-api/api/internal/…"│
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

##### WorkflowExecutor Class Design

```python
class WorkflowExecutor:
    """Delegates workflow execution to Synapse server."""

    def __init__(self, synapse_client: SynapseApiClient):
        self._synapse = synapse_client

    async def execute(
        self,
        workflow_ref: dict,       # {namespace, name, version}
        input_data: dict,         # Mapped context → workflow input
        on_progress: Callable,    # Callback for progress relay to CPA
    ) -> WorkflowResult:
        """
        Create a Synapse workflow instance and monitor to completion.

        1. POST /api/v1/workflow-instances — create instance with input
        2. GET .../monitor/sse — stream status updates
        3. Relay task completions via on_progress callback
        4. Return WorkflowResult on completion/failure
        """
        # Create instance
        instance = await self._synapse.create_instance(
            workflow_ref=workflow_ref,
            input_data=input_data,
        )

        # Monitor via SSE until terminal state
        async for event in self._synapse.monitor_instance_sse(
            namespace=instance.namespace,
            name=instance.name,
        ):
            if event.type == "task_completed":
                await on_progress(event.task_name, event.outcome)
            elif event.phase in ("completed", "faulted", "cancelled"):
                break

        # Fetch final state
        final = await self._synapse.get_instance(
            namespace=instance.namespace,
            name=instance.name,
        )

        return WorkflowResult(
            workflow_name=workflow_ref["name"],
            status="completed" if final.phase == "completed" else "failed",
            output=final.output,
            error=final.error if final.phase == "faulted" else None,
            duration_seconds=(final.ended_at - final.started_at).total_seconds(),
        )

    async def cancel(self, namespace: str, name: str) -> None:
        """Cancel a running workflow instance (leader step-down)."""
        await self._synapse.cancel_instance(namespace, name)
```

##### SynapseApiClient (Integration Layer)

```python
# integration/services/synapse_api_client.py

class SynapseApiClient:
    """HTTP client for Synapse REST API v1."""

    def __init__(self, base_url: str, http_client: httpx.AsyncClient):
        self._base_url = base_url
        self._http = http_client

    # --- Documents (Workflow Definitions) ---
    async def create_document(self, workflow_yaml: str) -> dict:
        """POST /api/v1/documents — upload workflow definition."""

    # --- Workflow Instances ---
    async def create_instance(self, workflow_ref: dict, input_data: dict) -> WorkflowInstanceInfo:
        """POST /api/v1/workflow-instances — create and start instance."""

    async def get_instance(self, namespace: str, name: str) -> WorkflowInstanceInfo:
        """GET /api/v1/workflow-instances/{ns}/{name}"""

    async def cancel_instance(self, namespace: str, name: str) -> None:
        """PUT /api/v1/workflow-instances/{ns}/{name}/cancel"""

    async def suspend_instance(self, namespace: str, name: str) -> None:
        """PUT /api/v1/workflow-instances/{ns}/{name}/suspend"""

    async def resume_instance(self, namespace: str, name: str) -> None:
        """PUT /api/v1/workflow-instances/{ns}/{name}/resume"""

    async def get_instance_logs(self, namespace: str, name: str) -> str:
        """GET /api/v1/workflow-instances/{ns}/{name}/logs"""

    async def monitor_instance_sse(self, namespace: str, name: str) -> AsyncIterator[WorkflowEvent]:
        """GET /api/v1/workflow-instances/{ns}/{name}/monitor/sse — SSE stream."""

    async def list_instances(self, namespace: str | None = None) -> list[WorkflowInstanceInfo]:
        """GET /api/v1/workflow-instances[/{ns}]"""

    # --- Events (CloudEvent ingestion for correlation) ---
    async def publish_event(self, cloud_event: dict) -> None:
        """POST /api/v1/events — publish CloudEvent for workflow correlation."""

    # --- DI registration ---
    @classmethod
    def configure(cls, services: ServiceCollection) -> None:
        """Register SynapseApiClient as singleton."""
```

##### Synapse Deployment

Synapse is added to the local Docker development stack:

```yaml
# docker-compose.yml
synapse:
  image: ghcr.io/serverlessworkflow/synapse:latest
  ports:
    - "8088:8088"    # API Server
    - "4200:4200"    # Dashboard UI
  environment:
    - SYNAPSE_API__STORAGE__MONGODB__CONNECTIONSTRING=mongodb://mongodb:27017
    - SYNAPSE_API__STORAGE__PROVIDER=mongodb
  depends_on:
    - mongodb
```

##### Input Mapping

The `WorkflowExecutor` transforms the `PipelineContext` into workflow input using
the `input_mapping` defined in the pipeline definition:

```yaml
# Pipeline definition with workflow engine
pipelines:
  collect_evidence:
    engine: "workflow"
    workflow_ref:
      namespace: "lcm"
      name: "collect-evidence"
      version: "0.1.0"
    input_mapping:
      session_id: "$SESSION.id"
      worker_ip: "$WORKER.ip"
      lab_id: "$SESSION.lab_record_id"
      definition_name: "$DEFINITION.name"
      cml_username: "$WORKER.cml_username"
```

The `$` variables reference the same `PipelineContext` objects used by `PipelineExecutor`,
ensuring consistency between the two execution strategies.

---

### 2.4 Pipeline Domain Events

Pipeline lifecycle events become **first-class domain events**, flowing through the existing
Neuroglia mediator → NotificationHandler chain. This is consistent with how all other domain
events already work in the system (per confirmed pattern: aggregate `register_event()` →
repository auto-publishes via mediator → handlers run concurrently).

#### 2.4.1 New Domain Events

| Domain Event | CloudEvent Type | Trigger |
|---|---|---|
| `PipelineStartedDomainEvent` | `resource.pipeline.started.v1` | Pipeline execution begins |
| `PipelineStepCompletedDomainEvent` | `resource.pipeline.step_completed.v1` | Individual step succeeds |
| `PipelineStepFailedDomainEvent` | `resource.pipeline.step_failed.v1` | Individual step fails |
| `PipelineStepSkippedDomainEvent` | `resource.pipeline.step_skipped.v1` | Step skipped by `skip_when` |
| `PipelineCompletedDomainEvent` | `resource.pipeline.completed.v1` | All steps completed successfully |
| `PipelineFailedDomainEvent` | `resource.pipeline.failed.v1` | Pipeline failed fatally |
| `PipelineRetryDomainEvent` | `resource.pipeline.retry.v1` | Pipeline retry initiated |

#### 2.4.2 Event Emission Point

Pipeline events are emitted by the **session aggregate** (not the executor). The executor
reports results back to the reconciler, which mutates the aggregate, which emits the event.
This preserves the existing pattern where all domain events originate from aggregates:

```
PipelineExecutor/WorkflowExecutor
  → reports step completion to reconciler
  → reconciler calls CPA: update_pipeline_progress(session_id, step, status)
  → CPA command handler loads LabletSession aggregate
  → aggregate.record_pipeline_step_completed(step_name, result_data)
  → aggregate.register_event(PipelineStepCompletedDomainEvent(...))
  → repository.update_async(aggregate)
  → Neuroglia auto-publishes domain event via mediator
  → NotificationHandlers fire concurrently:
      ├── etcd projector → /lcm/sessions/{type}/{id}/pipeline/{step}
      └── SSE handler → broadcast "resource.pipeline.step_completed"
```

#### 2.4.3 NotificationHandler Pattern

Following the established pattern — one handler class per event, auto-discovered by mediator:

```python
# application/events/domain/pipeline_event_handlers.py (in CPA)

class PipelineStepCompletedSSEHandler(
    DomainEventHandler[PipelineStepCompletedDomainEvent]
):
    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(self, notification):
        await self._sse_relay.broadcast_event(
            event_type="resource.pipeline.step_completed",
            data={
                "session_id": notification.aggregate_id,
                "resource_type": notification.resource_type,
                "pipeline_name": notification.pipeline_name,
                "step_name": notification.step_name,
                "step_status": notification.step_status,
                "step_index": notification.step_index,
                "total_steps": notification.total_steps,
                "duration_ms": notification.duration_ms,
                "timestamp": notification.timestamp.isoformat(),
            },
            source="domain.pipeline",
        )


class PipelineStepCompletedEtcdProjector(
    DomainEventHandler[PipelineStepCompletedDomainEvent]
):
    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, notification):
        await self._etcd.set_key(
            f"/lcm/sessions/{notification.resource_type}/{notification.aggregate_id}"
            f"/pipeline/{notification.step_name}",
            json.dumps({
                "status": notification.step_status,
                "pipeline": notification.pipeline_name,
                "timestamp": notification.timestamp.isoformat(),
            }),
        )
```

#### 2.4.4 Frontend SSE Integration

The `lcm_ui` SSEClient and EventBus already support subscribing to new event types.
Pipeline events are consumed by the frontend with zero framework changes:

```typescript
// In session detail component
sseClient.on('resource.pipeline.step_completed', (data) => {
    if (data.session_id === currentSessionId) {
        stateStore.dispatch('pipeline/stepCompleted', data);
        // Update progress bar, step list, timing display
    }
});

sseClient.on('resource.pipeline.completed', (data) => {
    stateStore.dispatch('pipeline/completed', data);
    showToast(`Pipeline ${data.pipeline_name} completed`, 'success');
});

sseClient.on('resource.pipeline.failed', (data) => {
    stateStore.dispatch('pipeline/failed', data);
    showToast(`Pipeline ${data.pipeline_name} failed: ${data.error}`, 'error');
});
```

**SSE filtering** (per ADR-013): Pipeline events should be added to the
`event_types` filter parameter, allowing clients to subscribe to
`resource.pipeline.*` events specifically.

---

### 2.5 LabletDefinition Extension

The `LabletDefinition` aggregate gains two new fields to support the dual execution strategy
and resource type binding:

```python
class LabletDefinitionState:
    # ... existing fields ...

    resource_type: str = "lablet"           # NEW — which session type this definition creates
    pipelines: dict | None = None           # EXISTING (ADR-034) — internal DAG pipelines
    workflows: dict | None = None           # NEW — external Synapse workflow references
```

#### 2.5.1 `workflows` Schema

```yaml
# In LabletDefinition seed YAML
workflows:
  collect_evidence:
    namespace: "lcm"
    name: "collect-evidence-workflow"
    version: "0.1.0"
    description: "Capture configs, screenshots, and pcaps for assessment"
    input_mapping:
      session_id: "$SESSION.id"
      worker_ip: "$WORKER.ip"
      lab_id: "$SESSION.lab_record_id"
    output_mapping:
      evidence_package_url: ".output.artifact_url"
      screenshots_count: ".output.screenshots | length"
```

#### 2.5.2 Pipeline-Workflow Coexistence

A definition can use **both** pipelines and workflows — different lifecycle phases can use
different engines:

```yaml
pipelines:
  instantiate:
    engine: "pipeline"         # Internal DAG — fast, deterministic
    steps: [...]

workflows:
  collect_evidence:            # External Synapse — complex choreography
    namespace: "lcm"
    name: "collect-evidence"
    version: "0.1.0"
    input_mapping: {...}

pipelines:
  teardown:
    engine: "pipeline"         # Internal DAG — deterministic cleanup
    steps: [...]
```

The reconciler resolves the execution strategy per lifecycle phase:

1. Check `pipelines[phase_name]` — if found and `engine == "pipeline"`, use `PipelineExecutor`
2. Check `workflows[phase_name]` — if found, use `WorkflowExecutor`
3. Check `pipelines[phase_name]` with `engine == "workflow"` — use `WorkflowExecutor` with inline ref
4. If neither found — error (AD-PIPELINE-009: no fallback)

---

## 2.6 Generalized Nested Resource Tree (Revision 3)

> R3 generalizes the layered abstraction (§2.1.4) into a **recursive tree** so the same
> spec/status + reconciliation machinery applies to sessions, their parts, their pods, and the
> hosts they run on. Detailed in [resource-model.md](../solution/resource-model.md).

### 2.6.1 From single session to a tree

Revision 2 modelled a flat `ResourceSession` with a pipeline. Real deliveries are not flat:
an expert exam is **multi-part** (DES → DOO → AI-DOO), each part may run **0..N pods**, and
each pod runs on **some host**. R3 therefore promotes three things to first-class
`TimedResource`s:

```
Session (was ResourceSession)
  └─ SessionPart        ← NEW first-class TimedResource (0..N per Session)
        └─ PodInstance   ← NEW first-class TimedResource (0..N per Part)
              └─ binds → Host / Worker   ← NEW generic infra TimedResource
```

`Session` is now a **profile** concept: a `LabletSession` is a `Session` with one part and one
`cml_on_aws` pod. The R2 "initial resource types" table (§2.1.2) is reinterpreted as session
**profiles** over this tree, not parallel aggregates.

### 2.6.2 New state classes (Layer 3)

All extend `TimedResourceState` (Layer 2) unchanged:

| State | Key fields | Reconciled by |
|---|---|---|
| `SessionState` | `session_definition_ref`, `part_ids[]` | CPA (Session manager) |
| `SessionPartState` | `session_id`, `part_definition_ref`, `pod_ids[]`, `order`, `gates_next` | CPA (Part manager) |
| `PodInstanceState` | `part_id`, `pod_definition_ref`, `pod_type`, `host_id` | controllers (Pod manager) |
| `HostState` | `host_type`, `pod_ids[]`, `capacity` | worker-controller (Host manager) |

`LabRecordState` becomes the `cml_on_aws` `PodInstanceState`; `CMLWorkerState` becomes the
`cml_on_aws` `HostState`. No change to Layers 1–2.

### 2.6.3 Intent cascade

`desired_status` cascades **down** the tree; observed `status` bubbles **up**:

- An operator/scheduler sets `Session.desired_status`.
- The Session manager sets each `SessionPart.desired_status` (respecting order + gating).
- The Part manager sets each `PodInstance.desired_status`.
- Pod/Host managers reconcile infrastructure and report status upward.

Parts are **sequential and gated**; a later part's **eager** pod (large `Timeslot.lead_time`)
may begin provisioning while an earlier part is still active.

### 2.6.4 Reconciliation ownership

| Level | Owner |
|---|---|
| `Session`, `SessionPart` | **CPA** (ordering, gating) |
| `PodInstance`, `Host`/`Worker` | **controllers** (+ resource-scheduler for allocation) |
| Per-part content automation | **SE** (via a `workflow` lifecycle phase) |

The reconcile loop itself is generalized into a single framework with per-type managers — see
[ADR-047](./ADR-047-generic-reconciliation-framework.md). The host abstraction and the
`PodType`/`HostType` split are specified in
[ADR-046](./ADR-046-host-abstraction-and-pod-host-type-split.md). The multi-part session/part
model and selector resolution are specified in
[ADR-045](./ADR-045-multi-part-session-part-model.md).

---

## 3. Implementation Plan

### Guiding Principle: Functional First, Abstraction Second

Complete the existing pipeline implementation (Sprint D–E from ADR-034) before introducing
resource type polymorphism. This validates the execution model end-to-end with `LabletSession`
before generalizing. **Phase 1 is substantially complete** (see status column below).

### Phase 1: Complete Pipeline Functional Implementation (Sprint D–E)

**Goal**: Finish ADR-034 delivery — all 4 pipelines wired, pipeline domain events flowing, SSE working.

**Status**: 11/14 tasks DONE, 1 PARTIAL, 2 NOT DONE (frontend only).

| # | Task | Component | Sprint | Status |
|---|------|-----------|--------|--------|
| 1.1 | Decompose `_handle_stopping()` into teardown step handlers | lablet-controller | D | ✅ DONE |
| 1.2 | Wire `_handle_stopping()` to LifecyclePhaseHandler + teardown pipeline | lablet-controller | D | ✅ DONE |
| 1.3 | Create stub step handlers for evidence collection | lablet-controller | D | ✅ DONE |
| 1.4 | Create stub step handlers for grading | lablet-controller | D | ✅ DONE |
| 1.5 | Wire `_handle_collecting()` and `_handle_grading()` | lablet-controller | D | ✅ DONE |
| 1.6 | Tests for all new step handlers and delegation paths | lablet-controller | D | ✅ DONE (59 tests) |
| 1.7 | Validate seed files load with all handlers | lablet-controller | D | ✅ DONE |
| 1.8 | Add `PipelineStarted/StepCompleted/Completed/Failed` domain events to CPA | CPA domain | E | ✅ DONE (integration events) |
| 1.9 | Add `PipelineStepCompletedSSEHandler` + etcd projector | CPA application | E | ⚠️ PARTIAL (SSE done, etcd projector missing) |
| 1.10 | Add `desired_status` field to `LabletSessionState` + aggregate method | CPA domain | E | ✅ DONE |
| 1.11 | Add `DesiredStatusSetDomainEvent` + etcd projector + SSE handler | CPA application | E | ✅ DONE |
| 1.12 | Frontend pipeline progress panel (SSE subscription) | lcm_ui | E | ❌ NOT DONE |
| 1.13 | Session detail: pipeline timeline visualization | lcm_ui | E | ❌ NOT DONE |
| 1.14 | Tests for pipeline event handlers (30+ tests) | CPA + lablet-controller | E | ✅ DONE (80+ tests) |

**Phase 1 Remaining Work**:

- **1.9**: Add etcd projector for `PipelineProgressUpdated` domain events
- **1.12–1.13**: Frontend pipeline progress components (can run in parallel with Phase 2)

### Phase 2: TimedResource Abstraction Extraction (Sprint F) ← REVISED

**Goal**: Extract the three-layer `Resource` → `TimedResource` hierarchy into `lcm_core`,
creating the framework-promotable abstraction layer. This replaces the original Phase 3
(which was "Extract `ResourceSessionState` base") and is brought forward because the
TimedResource pattern is now validated against all 3 existing aggregates.

| # | Task | Component | Sprint |
|---|------|-----------|--------|
| 2.1 | Create `StateTransition` value object in `lcm_core` (already exists, verify) | lcm_core/domain/value_objects | F |
| 2.2 | Create `Timeslot` value object in `lcm_core` | lcm_core/domain/value_objects | F |
| 2.3 | Create `LifecyclePhase` + `ManagedLifecycle` value objects in `lcm_core` | lcm_core/domain/value_objects | F |
| 2.4 | Create `ResourceState` abstract base in `lcm_core` | lcm_core/domain/entities | F |
| 2.5 | Create `TimedResourceState` abstract base in `lcm_core` | lcm_core/domain/entities | F |
| 2.6 | Create `TimedResourceReadModel` base read model in `lcm_core` | lcm_core/domain/entities/read_models | F |
| 2.7 | Refactor `LabletSessionState` to extend `TimedResourceState` | CPA domain | F |
| 2.8 | Add `desired_status` + `state_history` to `CMLWorkerState` (promote to base) | CPA domain | F |
| 2.9 | Add `desired_status` to `LabRecordState` (promote to base) | CPA domain | F |
| 2.10 | Update `LabletSessionReadModel` to extend `TimedResourceReadModel` | lcm_core/domain/entities/read_models | F |
| 2.11 | Update `CMLWorkerReadModel` to extend `TimedResourceReadModel` | lcm_core/domain/entities/read_models | F |
| 2.12 | Tests for all value objects + base classes (40+ tests) | lcm_core/tests | F |
| 2.13 | Verify backward compatibility — all existing tests pass | all | F |

**Key Constraint**: Refactoring MUST be backward-compatible. Existing aggregates gain base
class inheritance but no behavioral changes. MongoDB serialization unchanged.

### Phase 3: Synapse WorkflowExecutor (Sprint G) ← WAS Phase 2

**Goal**: Enable external workflow execution via Synapse for `collect_evidence` pipeline.

| # | Task | Component | Sprint |
|---|------|-----------|--------|
| 3.1 | Add Synapse to `docker-compose.yml` dev stack | deployment | G |
| 3.2 | Create `SynapseApiClient` integration service | lablet-controller/integration | G |
| 3.3 | Create `WorkflowExecutor` class | lablet-controller/application | G |
| 3.4 | Create `WorkflowResult` dataclass | lablet-controller/application | G |
| 3.5 | Add `engine` field to pipeline definition schema | lablet-controller | G |
| 3.6 | Add `workflows` field to `LabletDefinitionState` + read model | CPA + lcm_core | G |
| 3.7 | Update `LifecyclePhaseHandler` to select executor by `engine` | lablet-controller | G |
| 3.8 | Create sample `collect-evidence` workflow definition (YAML) | deployment/synapse | G |
| 3.9 | Wire `WorkflowExecutor` progress → CPA pipeline domain events | lablet-controller | G |
| 3.10 | Tests for `WorkflowExecutor` + `SynapseApiClient` (25+ tests) | lablet-controller | G |

### Phase 4: Concrete Resource Subtypes (Sprint H–I) ← WAS Phase 3

**Goal**: Add first new session type (`DemoSession`) using the extracted base.

| # | Task | Component | Sprint |
|---|------|-----------|--------|
| 4.1 | Add `resource_type` field to `LabletDefinitionState` | CPA domain | H |
| 4.2 | Create `DemoSession` aggregate extending `TimedResourceState` | CPA domain | H |
| 4.3 | Create `DemoSessionRepository` + Mongo implementation | CPA integration | H |
| 4.4 | Create `DemoSession` commands + queries (CQRS) | CPA application | H |
| 4.5 | Create `DemoSession` domain events + SSE handlers + etcd projectors | CPA application | H |
| 4.6 | Create `DemoSession` controller endpoints | CPA api | H |
| 4.7 | Update resource-scheduler to handle `resource_type` routing | resource-scheduler | I |
| 4.8 | Update lablet-controller reconciler for `resource_type` dispatch | lablet-controller | I |
| 4.9 | Create `DemoSession` seed definitions with demo-specific pipelines | CPA data | I |
| 4.10 | Frontend: session type selector + type-specific UI | lcm_ui | I |
| 4.11 | Tests for DemoSession full lifecycle (50+ tests) | all | I |

### Phase 5: Additional Resource Types (Sprint J+) ← WAS Phase 4

**Goal**: Add remaining resource types incrementally.

| # | Task | Sprint |
|---|------|--------|
| 5.1 | `ExpertLabSession` aggregate + full CQRS + events + tests | J |
| 5.2 | `ExpertDesignSession` aggregate + full CQRS + events + tests | J |
| 5.3 | `PracticeLabSession` aggregate + full CQRS + events + tests | K |
| 5.4 | `TestSession` aggregate + full CQRS + events + tests | K |
| 5.5 | `BYOLSession` aggregate + full CQRS + events + tests | L |

### Phase 6: Rich Intent Model (Sprint M — Future) ← WAS Phase 5

**Goal**: Expand `desired_status` into full `SessionIntent` sub-entity.

| # | Task | Sprint |
|---|------|--------|
| 6.1 | Design `SessionIntent` value object (separate ADR) | M |
| 6.2 | Add `intent` field to session aggregates | M |
| 6.3 | Migrate `desired_status` → `intent.expected_state` | M |
| 6.4 | Support batch creation (`intent.quantity`) | M |
| 6.5 | Support scheduling modes (`timeslot`, `on_demand`, `warm_pool`) | M |

---

## 4. Consequences

### 4.1 Positive

- **Type safety**: Concrete aggregates enforce type-specific constraints at compile time
- **Independent evolution**: Each resource type can add/remove lifecycle phases independently
- **Clean storage**: Separate collections enable type-specific indexes and queries
- **Dual execution**: Deterministic internal pipelines for fast lifecycle ops; Synapse for complex external orchestrations
- **Full-stack reactivity**: Pipeline events flow through the proven mediator → etcd/SSE chain
- **Incremental adoption**: Each phase delivers value independently; no big-bang migration
- **Standard-based**: Synapse implements CNCF Serverless Workflow — vendor-neutral, CloudEvent-native
- **Forward-compatible**: `desired_status` field prepares for richer `Intent` model without breaking changes
- **Framework-promotable**: `Resource` → `TimedResource` hierarchy in `lcm_core` is generic enough for Neuroglia framework adoption
- **Unified timeslot model**: `Timeslot` VO provides consistent time-bounded semantics for all resource types
- **Lifecycle as data**: `ManagedLifecycle` makes lifecycle phases declarative (YAML-driven), not hardcoded

### 4.2 Negative

- **Code duplication**: Each resource type duplicates the aggregate/repository/commands/events structure (~15 files per type)
- **Migration effort**: Phase 2 refactoring touches all 3 existing aggregates; Phase 4 touches all microservices when resource-type routing is added
- **Synapse operational overhead**: New service to deploy, monitor, and maintain (C#/.NET)
- **etcd key proliferation**: Per-resource-type key prefixes increase watch scope
- **Abstraction tax**: Three-layer hierarchy adds conceptual depth; developers must understand Resource → TimedResource → Concrete

### 4.3 Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Code duplication across resource types | Phase 2 extracts `TimedResourceState` base; code generators possible for boilerplate |
| Backward-incompatible refactoring in Phase 2 | All changes must pass existing tests; MongoDB serialization uses `get_type_hints()` which supports inheritance |
| Synapse server availability | `WorkflowExecutor` includes health check; fallback to pipeline if Synapse unavailable (configurable) |
| Synapse is early-stage (Neuroglia/cdavernas) | Same team as our Neuroglia framework; aligned roadmap; standard spec ensures portability |
| Resource type explosion | New types require explicit ADR approval; `LabletDefinition.resource_type` field is the gatekeeper |
| `desired_status` introduces semantic gap | Clear documentation: `desired_status` = "where to go", `status` = "where we are"; reconciler bridges the gap |
| Pipeline event storm (many steps × many sessions) | SSE batching (ADR-013) applies; pipeline events added to batchable list if frequency exceeds threshold |
| Timeslot VO adds field mapping complexity | Gradual migration: aggregate keeps `timeslot_start`/`timeslot_end` for now, `Timeslot` VO derived from them |

---

## 5. Appendices

### Appendix A: Synapse API Reference (Key Endpoints)

Based on the Synapse OpenAPI spec at [docs/integration/Synapse/openapi.json](../../integration/Synapse/openapi.json).

| Operation | Method | Endpoint |
|-----------|--------|----------|
| Upload workflow definition | POST | `/api/v1/documents` |
| Create workflow instance | POST | `/api/v1/workflow-instances` |
| Get instance | GET | `/api/v1/workflow-instances/{ns}/{name}` |
| Monitor instance (SSE) | GET | `/api/v1/workflow-instances/{ns}/{name}/monitor/sse` |
| Cancel instance | PUT | `/api/v1/workflow-instances/{ns}/{name}/cancel` |
| Suspend instance | PUT | `/api/v1/workflow-instances/{ns}/{name}/suspend` |
| Resume instance | PUT | `/api/v1/workflow-instances/{ns}/{name}/resume` |
| Get instance logs | GET | `/api/v1/workflow-instances/{ns}/{name}/logs` |
| Watch logs (stream) | GET | `/api/v1/workflow-instances/{ns}/{name}/logs/watch` |
| Publish CloudEvent | POST | `/api/v1/events` |
| List workflows | GET | `/api/v1/workflows[/{ns}]` |
| Watch workflows (SSE) | GET | `/api/v1/workflows/{ns}/watch/sse` |

### Appendix B: Serverless Workflow DSL — Quick Reference

```yaml
document:
  dsl: '1.0.0'
  namespace: lcm
  name: collect-evidence
  version: '0.1.0'

input:
  schema:
    type: object
    properties:
      session_id: { type: string }
      worker_ip: { type: string }
      lab_id: { type: string }

do:
  - captureConfigs:
      call: http
      with:
        method: get
        endpoint:
          uri: 'https://${.worker_ip}/api/v0/labs/${.lab_id}/nodes'
      output:
        as: '{ configs: . }'

  - checkGradable:
      switch:
        - hasRubric:
            when: '.definition.grade_xml_path != null'
            then: captureScreenshots
        - noRubric:
            then: packageEvidence

  - captureScreenshots:
      call: http
      with:
        method: post
        endpoint:
          uri: 'http://screenshot-service/capture'
        body:
          lab_id: '${.lab_id}'
          nodes: '${.configs}'

  - packageEvidence:
      call: http
      with:
        method: post
        endpoint:
          uri: 'http://control-plane-api/api/internal/evidence/package'
        body:
          session_id: '${.session_id}'
          evidence: '${.}'

output:
  as: '{ artifact_url: .package_url, screenshots_count: (.screenshots // []) | length }'
```

### Appendix C: Resource Type × Lifecycle Phase Matrix

| Resource Type | instantiate | collect_evidence | compute_grading | teardown | warmup |
|--------------|-------------|-----------------|-----------------|---------|--------|
| CMLWorker | ✅ pipeline (provision) | ⬜ n/a | ⬜ n/a | ✅ pipeline | ⬜ n/a |
| LabRecord | ✅ pipeline (import) | ⬜ n/a | ⬜ n/a | ✅ pipeline | ⬜ future |
| LabletSession | ✅ pipeline | ✅ workflow | ✅ workflow | ✅ pipeline | ⬜ future |
| ExpertLabSession | ✅ pipeline | ✅ workflow | ✅ workflow | ✅ pipeline | ⬜ future |
| ExpertDesignSession | ✅ pipeline | ✅ workflow (+ topology) | ✅ workflow | ✅ pipeline | ⬜ future |
| PracticeLabSession | ✅ pipeline | ⬜ optional | ⬜ skip | ✅ pipeline | ⬜ future |
| DemoSession | ✅ pipeline (minimal) | ⬜ skip | ⬜ skip | ✅ pipeline | ⬜ future |
| TestSession | ✅ pipeline | ✅ workflow | ✅ workflow | ✅ pipeline | ⬜ future |
| BYOLSession | ⬜ skip (user-provided) | ⬜ optional | ⬜ skip | ✅ pipeline (minimal) | ⬜ n/a |

### Appendix D: Revised Dependency Chain

```
Phase 1 (Functional — ADR-034 Sprint D+E) ← 11/14 DONE
  ├── D: Teardown + evidence + grading pipelines wired ✅
  └── E: Pipeline domain events + SSE + desired_status (backend ✅, frontend ❌)
          │
Phase 2 (TimedResource Abstraction — Sprint F) ← NEW, brought forward
  ├── Extract Resource → TimedResource hierarchy into lcm_core
  ├── Timeslot + ManagedLifecycle value objects
  └── Refactor all 3 aggregates to extend TimedResourceState
          │
Phase 3 (Synapse — Sprint G) ── depends on Phase 2 (abstraction available)
  ├── WorkflowExecutor + SynapseApiClient + docker-compose
  └── Sample workflow definitions
          │
Phase 4 (Concrete Subtypes — Sprint H+I) ── depends on Phase 2 (base class exists)
  ├── DemoSession aggregate extending TimedResourceState
  └── Multi-type routing in scheduler + controller + frontend
          │
Phase 5 (More Types — Sprint J+) ── depends on Phase 4 (routing works)
  ├── J: ExpertLabSession + ExpertDesignSession
  ├── K: PracticeLabSession + TestSession
  └── L: BYOLSession
          │
Phase 6 (Rich Intent — Sprint M) ── independent, can start after Phase 2
  └── SessionIntent value object, batch creation, scheduling modes
```

### Appendix E: Neuroglia Framework Gap Analysis

**What Neuroglia ROA provides** (per [pyneuro ROA docs](https://bvandewe.github.io/pyneuro/patterns/resource-oriented-architecture/)):

| Capability | Neuroglia Status | LCM Status | Gap |
|---|---|---|---|
| Resource Definition (spec/status) | ✅ Documented pattern | ✅ Implemented (CMLWorker, LabletSession) | None — aligned |
| Watcher Pattern | ✅ Documented pattern | ✅ Implemented (ReconciliationHostedService, etcd watches) | None |
| Controller Pattern | ✅ Documented pattern | ✅ Implemented (lablet-controller, worker-controller) | None |
| Reconciliation Loop | ✅ Documented pattern | ✅ Implemented (ReconciliationHostedService in lcm_core) | None |
| Drift Detection | ✅ Documented pattern | ✅ Implemented (port drift, resource observation) | None |
| Error Recovery | ✅ Documented pattern | ✅ Implemented (retry budgets, requeue) | None |
| **Resource State base class** | ❌ Not in framework | ✅ Proposed (ResourceState in lcm_core) | **Gap: promote to Neuroglia** |
| **TimedResource abstraction** | ❌ Not in framework | ✅ Proposed (TimedResourceState in lcm_core) | **Gap: promote to Neuroglia** |
| **Timeslot value object** | ❌ Not in framework | ✅ Proposed (Timeslot in lcm_core) | **Gap: promote to Neuroglia** |
| **ManagedLifecycle value object** | ❌ Not in framework | ✅ Proposed (ManagedLifecycle in lcm_core) | **Gap: promote to Neuroglia** |
| **Pipeline/Workflow orchestration** | ❌ Not in framework | ✅ Implemented (PipelineExecutor) | **Gap: promote to Neuroglia** |
| **desired_status (declarative intent)** | ✅ Documented (spec/status) | ✅ Implemented | Aligned — naming differs |

**Promotion strategy**: Implement in `lcm_core` first, validate across 3+ aggregates (CMLWorker,
LabRecord, LabletSession), then propose as Neuroglia framework PR. The `lcm_core` package serves
as the staging ground for framework-promotable abstractions.
