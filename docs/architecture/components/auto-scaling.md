# Auto-Scaling Architecture

**Version:** 1.0.0 (February 2026)
**Scope:** Cross-cutting — spans Resource Scheduler, Control Plane API, and Worker Controller
**Phase:** Phase 3 - Auto-Scaling

!!! note "Related Documentation"
    - [Worker Lifecycle](worker-controller/worker-lifecycle.md) — state transitions during scaling
    - [Worker Discovery](worker-controller/worker-discovery.md) — how controllers observe changes
    - [Idle Detection](control-plane-api/idle-detection.md) — activity tracking for scale-down
    - [Worker Templates](resource-scheduler/worker-templates.md) — template selection and capacity

---

## 1. Overview

LCM auto-scaling automatically adjusts the CML worker fleet based on workload demand. It operates in two directions:

| Direction | Trigger | Service Chain | Goal |
|-----------|---------|---------------|------|
| **Scale Up** | Insufficient capacity for pending lablet instances | Resource Scheduler → Control Plane API → Worker Controller | Add workers |
| **Scale Down** | Workers idle beyond threshold | Worker Controller → Control Plane API | Remove workers |

```mermaid
flowchart LR
    subgraph up["Scale Up"]
        direction TB
        RS["Resource Scheduler<br/>PlacementEngine"]
        CP1["Control Plane API<br/>RequestScaleUpCommand"]
        WC1["Worker Controller<br/>_handle_pending"]
        RS -->|"No capacity"| CP1 -->|"Create PENDING worker"| WC1
    end

    subgraph down["Scale Down"]
        direction TB
        WC2["Worker Controller<br/>_evaluate_scale_down"]
        CP2["Control Plane API<br/>DrainWorkerCommand"]
        WC3["Worker Controller<br/>_handle_stopping"]
        WC2 -->|"Idle + eligible"| CP2 -->|"DRAINING"| WC3
    end

    style up fill:#E8F5E9,stroke:#2E7D32
    style down fill:#FFEBEE,stroke:#C62828
```

---

## 2. Scale-Up Flow

When the Resource Scheduler cannot find a suitable worker for a pending lablet instance, it triggers a scale-up:

```mermaid
sequenceDiagram
    autonumber
    participant Inst as Lablet Instance<br/>(PENDING_SCHEDULING)
    participant RS as Resource Scheduler
    participant PE as Placement Engine
    participant CP as Control Plane API
    participant etcd as etcd
    participant WC as Worker Controller
    participant EC2 as AWS EC2

    Inst->>RS: Observed via watch/polling

    RS->>PE: place_instance(instance, workers, templates)

    alt Workers available
        PE->>PE: Filter → Score → Select
        PE-->>RS: PlacementDecision(action=assign, worker_id)
        RS->>CP: assign_instance(instance_id, worker_id)
    else No workers or no capacity
        PE->>PE: _select_template(requirements)
        PE-->>RS: PlacementDecision(action=scale_up, template)
        RS->>CP: request_scale_up(template, reason)

        rect rgb(232, 245, 233)
            Note over CP: RequestScaleUpCommand
            CP->>CP: Resolve template
            CP->>CP: Check scaling constraints
            CP->>CP: Create CMLWorker(status=PENDING)
            CP->>etcd: PUT /workers/new-id
        end

        etcd-->>WC: Watch event

        rect rgb(227, 242, 253)
            Note over WC: _handle_pending
            WC->>EC2: launch_instance()
            EC2-->>WC: instance_id
            WC->>CP: update_status(PROVISIONING)
        end

        Note over WC: Subsequent cycles:<br/>PROVISIONING → RUNNING
    end
```

### Scaling Constraints

Before creating a new worker, `RequestScaleUpCommand` validates:

| Constraint | Check | Default | Behavior on Violation |
|-----------|-------|---------|----------------------|
| **Max workers per region** | `active_count < max_workers_per_region` | `10` | Reject with 409 Conflict |
| **Pending workers** | Check for existing PENDING workers | — | Log warning (does not block) |
| **Constraint check failure** | Exception during validation | — | **Fail open** — allows scale-up |

!!! warning "Fail-Open Design"
    If the constraint check itself fails (e.g., database error), the scale-up is **allowed** to proceed. This prevents a cascading failure where infrastructure issues also prevent scaling.

---

## 3. Placement Algorithm

The `PlacementEngine` implements a **Filter → Score → Select** pattern inspired by the Kubernetes scheduler:

```mermaid
flowchart TD
    Start["place_instance(instance)"] --> HasWorkers{"Any workers<br/>registered?"}

    HasWorkers -->|No| ScaleUp1["PlacementDecision<br/>action=scale_up<br/>reason: no workers available"]

    HasWorkers -->|Yes| Filter["Filter Phase<br/>(5 predicates)"]

    Filter --> HasCandidates{"Any candidates<br/>passed filter?"}

    HasCandidates -->|No| ScaleUp2["PlacementDecision<br/>action=scale_up<br/>reason: + rejection_reasons"]

    HasCandidates -->|Yes| Score["Score Phase<br/>(utilization + locality)"]

    Score --> Select["Select highest score<br/>(bin-packing: most utilized)"]

    Select --> Assign["PlacementDecision<br/>action=assign<br/>worker_id=selected"]

    style Start fill:#1565C0,color:white
    style ScaleUp1 fill:#FF9800,color:white
    style ScaleUp2 fill:#FF9800,color:white
    style Assign fill:#4CAF50,color:white
```

### Filter Predicates (5 checks)

Each worker must pass **all** predicates to be eligible:

```mermaid
flowchart TD
    W["Worker candidate"] --> F1{"Status check<br/>status = RUNNING?"}
    F1 -->|Fail| R1["Rejected:<br/>status_not_eligible"]
    F1 -->|Pass| F2{"License affinity<br/>matches requirement?"}
    F2 -->|Fail| R2["Rejected:<br/>license_affinity"]
    F2 -->|Pass| F3{"Resource capacity<br/>CPU, memory, storage?"}
    F3 -->|Fail| R3["Rejected:<br/>insufficient_capacity"]
    F3 -->|Pass| F4{"AMI requirements<br/>CML version, node defs?"}
    F4 -->|Fail| R4["Rejected:<br/>ami"]
    F4 -->|Pass| F5{"Port availability<br/>enough free ports?"}
    F5 -->|Fail| R5["Rejected:<br/>port_availability"]
    F5 -->|Pass| OK["Passes filter"]

    style OK fill:#4CAF50,color:white
    style R1 fill:#f44336,color:white
    style R2 fill:#f44336,color:white
    style R3 fill:#f44336,color:white
    style R4 fill:#f44336,color:white
    style R5 fill:#f44336,color:white
```

| # | Predicate | Data Source | Logic |
|---|-----------|------------|-------|
| 1 | **Status** | Worker state | Must be `RUNNING` (not DRAINING, STOPPING, etc.) |
| 2 | **License** | Instance requirements | If instance specifies license types, worker's license must match |
| 3 | **Capacity** | etcd (preferred) or worker state | Available CPU ≥ required, memory ≥ required, storage ≥ required |
| 4 | **AMI** | Instance requirements | CML version in min/max range, required node definitions present |
| 5 | **Ports** | Worker state + allocated ports | `max_ports - allocated_ports ≥ required_ports` |

!!! tip "Real-Time Capacity via etcd"
    The placement engine **prefers etcd** for capacity data (updated every 30s by workers) over MongoDB state, which may be stale. Capacity keys: `/lcm/workers/{id}/capacity`.

### Scoring Formula

Workers that pass filtering are scored to select the **most utilized** (bin-packing strategy):

$$
\text{score} = \frac{\text{cpu\_utilization} + \text{memory\_utilization}}{2} + \text{locality\_bonus}
$$

Where:

- $\text{cpu\_utilization} = \frac{\text{allocated\_cpu}}{\text{declared\_cpu}}$
- $\text{memory\_utilization} = \frac{\text{allocated\_memory}}{\text{declared\_memory}}$
- $\text{locality\_bonus} = \min(0.05, \text{instance\_count} \times 0.01)$ — small bonus for co-locating instances

**Higher score = preferred** — the algorithm packs workloads onto the most utilized workers first, keeping other workers available for larger workloads or scale-down.

---

## 4. Template Selection

When the placement engine decides to scale up, it selects the optimal worker template:

```mermaid
flowchart TD
    Start["_select_template(requirements)"] --> HasTemplates{"Templates<br/>available?"}

    HasTemplates -->|No| Hardcoded["Tier 3: Hardcoded fallback"]

    HasTemplates -->|Yes| Tier1["Tier 1: Capacity-based<br/>cheapest viable"]

    Tier1 --> T1Filter["Filter: enabled templates<br/>where CPU, memory, storage<br/>all >= requirements"]
    T1Filter --> T1Sort["Sort by cost_per_hour ASC"]
    T1Sort --> T1Check{"Any matches?"}

    T1Check -->|Yes| T1Select["Select cheapest viable"]
    T1Check -->|No| Tier2["Tier 2: Largest available"]

    Tier2 --> T2Filter["Filter: enabled templates"]
    T2Filter --> T2Sort["Sort by CPU DESC"]
    T2Sort --> T2Check{"Any templates?"}

    T2Check -->|Yes| T2Select["Select largest + warning"]
    T2Check -->|No| Hardcoded

    Hardcoded --> HC{"Required CPU?"}
    HC -->|">= 32"| Metal["metal"]
    HC -->|">= 16"| Large["large"]
    HC -->|">= 4"| Medium["medium"]
    HC -->|"< 4"| Small["small"]

    style Start fill:#1565C0,color:white
    style T1Select fill:#4CAF50,color:white
    style T2Select fill:#FF9800,color:white
    style Metal fill:#9E9E9E,color:white
    style Large fill:#9E9E9E,color:white
    style Medium fill:#9E9E9E,color:white
    style Small fill:#9E9E9E,color:white
```

See [Worker Templates](resource-scheduler/worker-templates.md) for template definitions and capacity model.

---

## 5. Scale-Down Flow

Scale-down is evaluated during the Worker Controller's `_handle_running` reconciliation (Step 6), after idle detection has run:

```mermaid
sequenceDiagram
    autonumber
    participant WC as Worker Controller
    participant CP as Control Plane API
    participant etcd as etcd

    Note over WC: _handle_running Step 6

    WC->>WC: _evaluate_scale_down(worker, idle_result)

    alt Guard 1: auto_pause_triggered
        Note over WC: Skip — auto-pause already acted
    else Guard 2: not idle
        Note over WC: Skip — worker is active
    else Guard 3: not eligible
        Note over WC: Skip — not eligible for pause
    else Guard 4: running <= min_workers
        Note over WC: Skip — at minimum fleet size
    else Guard 5: cooldown active
        Note over WC: Skip — too soon since last drain
    else All guards pass
        WC->>CP: drain_worker(worker_id, reason=scale_down)

        rect rgb(255, 235, 238)
            Note over CP: DrainWorkerCommand
            CP->>CP: Validate status = RUNNING
            CP->>CP: Set status = DRAINING
            CP->>CP: Set desired_status = STOPPED
            CP->>etcd: PUT /workers/id (status=DRAINING)
        end

        WC->>WC: Update last_scale_down_at
        WC->>WC: Decrement running_worker_count
        WC->>WC: Increment scale_down_count
    end
```

### Safety Guards (5 checks, in order)

The `_evaluate_scale_down` method applies five sequential guards before draining:

| # | Guard | Condition to Skip | Audit Label | Purpose |
|---|-------|-------------------|-------------|---------|
| 1 | **Auto-pause** | `auto_pause_triggered` is true | `skipped_auto_pause` | Avoid double-action with auto-pause |
| 2 | **Idle check** | `is_idle` is false | `skipped_not_idle` | Only drain idle workers |
| 3 | **Eligibility** | `eligible_for_pause` is false | `skipped_not_eligible` | Respects snooze, per-worker flags |
| 4 | **Min workers** | `running_count <= min_workers` | `skipped_min_workers` | Maintain minimum fleet |
| 5 | **Cooldown** | `elapsed < cooldown_seconds` | `skipped_cooldown` | Prevent rapid succession drains |

```mermaid
flowchart TD
    Start["_evaluate_scale_down"] --> G1{"auto_pause<br/>triggered?"}
    G1 -->|Yes| Skip1["Skip: auto-pause<br/>already handled"]
    G1 -->|No| G2{"is_idle?"}
    G2 -->|No| Skip2["Skip: not idle"]
    G2 -->|Yes| G3{"eligible_for<br/>_pause?"}
    G3 -->|No| Skip3["Skip: not eligible"]
    G3 -->|Yes| G4{"running_count<br/><= min_workers?"}
    G4 -->|Yes| Skip4["Skip: minimum<br/>fleet size"]
    G4 -->|No| G5{"cooldown<br/>active?"}
    G5 -->|Yes| Skip5["Skip: too soon"]
    G5 -->|No| Drain["DRAIN WORKER"]

    style Start fill:#1565C0,color:white
    style Drain fill:#f44336,color:white
    style Skip1 fill:#9E9E9E,color:white
    style Skip2 fill:#9E9E9E,color:white
    style Skip3 fill:#9E9E9E,color:white
    style Skip4 fill:#9E9E9E,color:white
    style Skip5 fill:#9E9E9E,color:white
```

### Running Worker Count Tracking

After a successful drain, the reconciler **decrements `_running_worker_count`** locally. This ensures that if multiple idle workers are evaluated in the same reconciliation cycle, the `min_workers` guard remains accurate without waiting for the next API refresh.

---

## 6. DRAINING State (ADR-008)

The `DRAINING` status provides a graceful transition between `RUNNING` and `STOPPING`:

```mermaid
stateDiagram-v2
    direction LR
    RUNNING --> DRAINING: DrainWorkerCommand
    DRAINING --> STOPPING: Worker Controller reconcile
    STOPPING --> STOPPED: EC2 instance stopped

    note right of DRAINING
        Worker accepts no new<br/>lablet assignments.<br/>Active workloads continue<br/>until completion.
    end note
```

The `DrainWorkerCommand` handler:

1. Validates the worker is in `RUNNING` status (returns 409 Conflict otherwise)
2. Sets `status = DRAINING`
3. Sets `desired_status = STOPPED`
4. Records scaling audit event

The Worker Controller's `_handle_stopping` method handles both `STOPPING` and `DRAINING` statuses with the same EC2 stop logic.

---

## 7. End-to-End Scale-Up Timeline

```mermaid
sequenceDiagram
    autonumber
    participant User as User / System
    participant RS as Resource Scheduler
    participant CP as Control Plane API
    participant WC as Worker Controller
    participant EC2 as AWS EC2
    participant CML as CML Instance

    User->>CP: Create LabletInstance (PENDING)
    CP->>CP: Set status = PENDING_SCHEDULING

    Note over RS: Watch event or polling cycle

    RS->>RS: PlacementEngine: no capacity
    RS->>CP: RequestScaleUp(template=large)
    CP->>CP: Create worker (PENDING)

    Note over WC: Watch event (~0.5s)

    WC->>EC2: launch_instance(m5zn.metal)
    WC->>CP: Update status (PROVISIONING)

    Note over EC2: EC2 instance booting (~2-5 min)

    WC->>EC2: get_instance_state()
    EC2-->>WC: running + IP
    WC->>CP: Update status (RUNNING, ip_address)

    Note over RS: Next reconciliation cycle

    RS->>RS: PlacementEngine: worker available
    RS->>CP: assign_instance(instance, worker)

    Note over CML: Lablet Controller provisions lab
```

---

## 8. Observability

### Scaling Audit Events

All scaling decisions are recorded via `record_scaling_event()` for observability:

| Event | Service | Description |
|-------|---------|-------------|
| `scale_up_accepted` | Control Plane API | New worker created from template |
| `scale_up_rejected` | Control Plane API | Constraint violation or error |
| `provisioned` | Worker Controller | EC2 instance launched |
| `scale_down_initiated` | Worker Controller | Drain command sent |
| `scale_down_failed` | Worker Controller | Drain command failed |
| `skipped_auto_pause` | Worker Controller | Scale-down skipped (auto-pause acted) |
| `skipped_not_idle` | Worker Controller | Scale-down skipped (worker active) |
| `skipped_not_eligible` | Worker Controller | Scale-down skipped (not eligible) |
| `skipped_min_workers` | Worker Controller | Scale-down skipped (min fleet) |
| `skipped_cooldown` | Worker Controller | Scale-down skipped (cooldown) |
| `drained` | Worker Controller | Worker successfully drained |

---

## 9. Configuration Reference

### Scale-Up Settings (Control Plane API)

| Setting | Env Variable | Default | Description |
|---------|-------------|---------|-------------|
| `max_workers_per_region` | `MAX_WORKERS_PER_REGION` | `10` | Maximum active workers per AWS region |

### Scale-Down Settings (Worker Controller)

| Setting | Env Variable | Default | Description |
|---------|-------------|---------|-------------|
| `scale_down_enabled` | `SCALE_DOWN_ENABLED` | `False` | Enable automatic scale-down |
| `min_workers` | `MIN_WORKERS` | `0` | Minimum running workers to maintain |
| `scale_down_cooldown_seconds` | `SCALE_DOWN_COOLDOWN_SECONDS` | `600` | Cooldown between drains (10 min) |

### Scheduler Settings (Resource Scheduler)

| Setting | Env Variable | Default | Description |
|---------|-------------|---------|-------------|
| `scheduling_interval` | `RECONCILE_INTERVAL` | `30` | Seconds between scheduling cycles |
| `max_retries` | `MAX_RETRIES` | `35` | Max retries for failed placements |
| `scheduling_polling_enabled` | `SCHEDULING_POLLING_ENABLED` | `True` | Enable polling-based scheduling |

!!! warning "Scale-Down Disabled by Default"
    `scale_down_enabled` defaults to `False`. Enable it only after validating idle detection thresholds and min_workers settings for your environment.
