# Idle Detection & Auto-Pause

**Version:** 1.0.0 (February 2026)
**Component:** Control Plane API (orchestration), Worker Controller (trigger)
**Source:** `src/control-plane-api/application/commands/worker/detect_worker_idle_command.py`

!!! note "Related Documentation"
    - [Worker Lifecycle](../worker-controller/worker-lifecycle.md) — reconciliation step 5 triggers idle detection
    - [Auto-Scaling](../auto-scaling.md) — scale-down uses idle detection results
    - [Worker Discovery](../worker-controller/worker-discovery.md) — observation patterns

---

## 1. Overview

LCM automatically detects idle workers and pauses them to reduce cloud costs. The idle detection system operates as a **4-step pipeline** orchestrated by the `DetectWorkerIdleCommand`, which is triggered by the Worker Controller during each `RUNNING` reconciliation cycle.

```mermaid
flowchart LR
    subgraph Trigger["Worker Controller"]
        WR["_handle_running()<br/>Step 5: Activity Detection"]
    end

    subgraph Pipeline["Control Plane API Pipeline"]
        direction LR
        S1["1. Fetch<br/>Telemetry"]
        S2["2. Update<br/>Activity"]
        S3["3. Check<br/>Idle Status"]
        S4["4. Auto-Pause<br/>(if eligible)"]
        S1 --> S2 --> S3 --> S4
    end

    WR --> S1

    style Trigger fill:#E3F2FD,stroke:#1565C0
    style Pipeline fill:#FFF3E0,stroke:#E65100
```

---

## 2. Detection Pipeline

The `DetectWorkerIdleCommandHandler` orchestrates four sequential steps. Each step can fail independently — the pipeline returns early with partial results if any step fails.

```mermaid
sequenceDiagram
    autonumber
    participant WC as Worker Controller
    participant Cmd as DetectWorkerIdleCommand
    participant Telem as GetWorkerTelemetryEvents
    participant Update as UpdateWorkerActivity
    participant Idle as GetWorkerIdleStatus
    participant Pause as PauseWorkerCommand

    WC->>Cmd: detect_worker_idle(worker_id)

    rect rgb(227, 242, 253)
        Note over Cmd,Telem: Step 1: Fetch Telemetry
        Cmd->>Telem: GetWorkerTelemetryEventsQuery(worker_id)
        Telem-->>Cmd: latest_activity_at, recent_events[]
    end

    rect rgb(232, 245, 233)
        Note over Cmd,Update: Step 2: Update Activity State
        Cmd->>Update: UpdateWorkerActivityCommand
        Note right of Update: last_activity_at,<br/>recent_events,<br/>last_check_at
        Update-->>Cmd: OK
    end

    rect rgb(255, 243, 224)
        Note over Cmd,Idle: Step 3: Check Idle Status
        Cmd->>Idle: GetWorkerIdleStatusQuery(worker_id)
        Idle-->>Cmd: is_idle, idle_minutes,<br/>eligible_for_pause,<br/>in_snooze_period
    end

    rect rgb(255, 235, 238)
        Note over Cmd,Pause: Step 4: Auto-Pause (conditional)
        alt eligible_for_pause = true
            Cmd->>Pause: PauseWorkerCommand(is_auto_pause=true)
            Pause-->>Cmd: auto_pause_triggered = true
        else not eligible
            Note over Cmd: Skip — not idle or in snooze
        end
    end

    Cmd-->>WC: detection_result dict
```

### Detection Result

The pipeline returns a comprehensive result dictionary:

| Field | Type | Description |
|-------|------|-------------|
| `worker_id` | `str` | Worker identifier |
| `checked_at` | `datetime` | UTC timestamp of check |
| `telemetry_fetched` | `bool` | Step 1 completed |
| `activity_updated` | `bool` | Step 2 completed |
| `idle_check_performed` | `bool` | Step 3 completed |
| `auto_pause_triggered` | `bool` | Step 4 executed |
| `is_idle` | `bool` | Worker is idle (exceeds threshold) |
| `idle_minutes` | `float` | Minutes since last activity |
| `eligible_for_pause` | `bool` | Meets all auto-pause criteria |
| `in_snooze_period` | `bool` | Recently resumed, snooze active |
| `error` | `str?` | Error message if pipeline failed early |

---

## 3. Telemetry Sources (Step 1)

Telemetry events are fetched from the **CML REST API** on the worker instance. The `GetWorkerTelemetryEventsQuery` connects to the worker's CML API and retrieves recent activity events.

### Relevant Activity Categories

The system filters CML events by categories that indicate meaningful user activity:

| Category | Description |
|----------|-------------|
| `start_lab` | User started a lab |
| `stop_lab` | User stopped a lab |
| `create_lab` | User created a new lab |
| `import_lab` | Lab imported to worker |
| `wipe_lab` | Lab data wiped |
| `delete_lab` | Lab deleted |
| `start_node` | Individual node started |
| `stop_node` | Individual node stopped |

!!! info "Why CML Telemetry?"
    CloudWatch metrics (CPU, memory) cannot reliably distinguish between an idle worker and one running static labs with minimal resource usage. CML telemetry events provide **user-intent signals** — if a user is actively interacting with labs, the worker is not idle.

---

## 4. Idle Status Evaluation (Step 3)

The `GetWorkerIdleStatusQueryHandler` evaluates four conditions to determine idle eligibility:

```mermaid
flowchart TD
    Start["GetWorkerIdleStatusQuery"] --> Fetch["Fetch worker from repository"]
    Fetch --> Settings["Get effective idle settings<br/>(SystemConfigurationService)"]

    Settings --> CalcIdle["Calculate idle_minutes<br/>= now - last_activity"]

    CalcIdle --> IsIdle{"idle_minutes ><br/>timeout_minutes?"}
    IsIdle -->|No| NotIdle["is_idle = false<br/>eligible = false"]
    IsIdle -->|Yes| CheckEnabled{"auto_pause_enabled?<br/>(global AND per-worker)"}

    CheckEnabled -->|No| Disabled["auto_pause_enabled = false<br/>eligible = false"]
    CheckEnabled -->|Yes| CheckSnooze{"in_snooze_period?"}

    CheckSnooze -->|Yes| Snoozed["in_snooze = true<br/>eligible = false"]
    CheckSnooze -->|No| CheckStatus{"worker.status<br/>== RUNNING?"}

    CheckStatus -->|No| WrongStatus["eligible = false"]
    CheckStatus -->|Yes| Eligible["eligible_for_pause = true"]

    style Start fill:#1565C0,color:white
    style Eligible fill:#4CAF50,color:white
    style NotIdle fill:#9E9E9E,color:white
    style Disabled fill:#9E9E9E,color:white
    style Snoozed fill:#FF9800,color:white
    style WrongStatus fill:#9E9E9E,color:white
```

### Eligibility Formula

A worker is eligible for auto-pause when **all four conditions** are true:

$$
\text{eligible} = \text{is\_idle} \wedge \text{auto\_pause\_enabled} \wedge \neg\text{in\_snooze} \wedge (\text{status} = \text{RUNNING})
$$

Where:

- **is_idle**: `idle_minutes > timeout_minutes` (default threshold: 60 minutes)
- **auto_pause_enabled**: Global setting AND per-worker `is_idle_detection_enabled` flag
- **in_snooze**: Worker was resumed within the snooze window (default: 60 minutes)
- **status = RUNNING**: Only running workers can be paused

### Last Activity Fallback Chain

The `IdleDetectionService` uses a 3-step fallback to determine the "last activity" timestamp:

```mermaid
flowchart LR
    A{"last_activity_at<br/>set?"} -->|Yes| Use1["Use last_activity_at"]
    A -->|No| B{"last_resumed_at<br/>set?"}
    B -->|Yes| Use2["Use last_resumed_at"]
    B -->|No| Use3["Use created_at"]

    style Use1 fill:#4CAF50,color:white
    style Use2 fill:#FF9800,color:white
    style Use3 fill:#f44336,color:white
```

This ensures every worker has a meaningful baseline — even newly created workers that have never had user activity.

---

## 5. Snooze Period

After a worker is **manually resumed**, auto-pause is temporarily suppressed to prevent a frustrating loop of pause → resume → immediate pause:

```mermaid
sequenceDiagram
    participant User
    participant Worker
    participant System

    Note over Worker: Auto-paused (idle 60+ min)
    Worker->>Worker: status → STOPPED

    User->>Worker: Resume worker
    Worker->>Worker: status → RUNNING
    Worker->>Worker: last_resumed_at = now

    rect rgb(255, 243, 224)
        Note over Worker,System: Snooze Period (60 min default)
        System->>Worker: Idle check
        Worker-->>System: in_snooze = true, eligible = false
        Note over System: Auto-pause suppressed
    end

    Note over Worker: Snooze expires

    System->>Worker: Idle check
    Worker-->>System: in_snooze = false
    Note over System: Auto-pause eligible again
```

### Snooze Calculation

$$
\text{in\_snooze} = (\text{now} - \text{last\_resumed\_at}) < \text{snooze\_minutes}
$$

Default snooze duration: **60 minutes** (configurable via `worker_auto_pause_snooze_minutes`).

---

## 6. Activity Tracking Fields

The `CMLWorkerState` aggregate tracks comprehensive activity data:

| Field | Type | Updated By | Purpose |
|-------|------|-----------|---------|
| `last_activity_at` | `datetime?` | UpdateWorkerActivity | Last meaningful user event |
| `last_activity_check_at` | `datetime?` | UpdateWorkerActivity | When telemetry was last checked |
| `recent_activity_events` | `list` | UpdateWorkerActivity | Last N activity events |
| `auto_pause_count` | `int` | PauseWorkerCommand | Total auto-pauses for this worker |
| `manual_pause_count` | `int` | StopWorkerCommand | Total manual stops |
| `auto_resume_count` | `int` | ResumeWorkerCommand | Total auto-resumes |
| `manual_resume_count` | `int` | StartWorkerCommand | Total manual starts |
| `last_paused_at` | `datetime?` | PauseWorkerCommand | Timestamp of last pause |
| `last_resumed_at` | `datetime?` | ResumeWorkerCommand | Timestamp of last resume (snooze anchor) |
| `last_paused_by` | `str?` | PauseWorkerCommand | Who triggered the pause |
| `pause_reason` | `str?` | PauseWorkerCommand | "idle_timeout", "manual", "external" |
| `next_idle_check_at` | `datetime?` | GetWorkerIdleStatus | Scheduled next check time |
| `target_pause_at` | `datetime?` | GetWorkerIdleStatus | Estimated pause time |
| `is_idle_detection_enabled` | `bool` | Per-worker setting | Per-worker toggle (default: `True`) |

---

## 7. Cross-Service Interaction

Idle detection spans two services with clear responsibility boundaries:

```mermaid
flowchart TB
    subgraph wc["Worker Controller"]
        Reconciler["WorkerReconciler<br/>_handle_running()"]
        Trigger["Calls detect_worker_idle<br/>via Control Plane API"]
        ScaleDown["_evaluate_scale_down()<br/>uses idle_result"]
    end

    subgraph cp["Control Plane API"]
        Detect["DetectWorkerIdleCommand"]
        Telemetry["GetWorkerTelemetryEvents"]
        Activity["UpdateWorkerActivity"]
        IdleCheck["GetWorkerIdleStatus"]
        Pause["PauseWorkerCommand"]
    end

    subgraph cml["CML Worker Instance"]
        API["CML REST API<br/>/api/v0/events"]
    end

    Reconciler --> Trigger
    Trigger --> Detect
    Detect --> Telemetry
    Telemetry --> API
    Detect --> Activity
    Detect --> IdleCheck
    IdleCheck --> Pause
    Trigger --> ScaleDown

    style wc fill:#E3F2FD,stroke:#1565C0
    style cp fill:#FFF3E0,stroke:#E65100
    style cml fill:#E8F5E9,stroke:#2E7D32
```

| Responsibility | Service | Why |
|---------------|---------|-----|
| **Trigger detection** | Worker Controller | Runs during reconciliation loop, knows worker IP |
| **Fetch CML telemetry** | Control Plane API | Has CML API client, domain logic |
| **Evaluate idle status** | Control Plane API | Owns worker aggregate, settings, domain services |
| **Execute pause** | Control Plane API | CQRS command updates aggregate state |
| **Act on scale-down** | Worker Controller | Makes EC2 infrastructure decisions |

---

## 8. Configuration Reference

### Control Plane API Settings

| Setting | Env Variable | Default | Description |
|---------|-------------|---------|-------------|
| `worker_idle_timeout_minutes` | `WORKER_IDLE_TIMEOUT_MINUTES` | `60` | Minutes of inactivity before idle |
| `worker_auto_pause_enabled` | `WORKER_AUTO_PAUSE_ENABLED` | `True` | Global auto-pause toggle |
| `worker_auto_pause_snooze_minutes` | `WORKER_AUTO_PAUSE_SNOOZE_MINUTES` | `60` | Snooze after resume |
| `worker_activity_detection_enabled` | `WORKER_ACTIVITY_DETECTION_ENABLED` | `True` | Enable activity tracking |
| `worker_activity_detection_interval` | `WORKER_ACTIVITY_DETECTION_INTERVAL` | `1800` | Seconds between activity checks |

### Worker Controller Settings

| Setting | Env Variable | Default | Description |
|---------|-------------|---------|-------------|
| `idle_detection_interval` | `IDLE_DETECTION_INTERVAL` | `300` | Min seconds between per-worker idle checks |
| `scale_down_enabled` | `SCALE_DOWN_ENABLED` | `False` | Enable scale-down after idle detection |

### Per-Worker Override

Each worker has an `is_idle_detection_enabled` flag (default: `True`) that can disable idle detection individually without affecting global settings.
