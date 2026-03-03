# Worker Lifecycle & Reconciliation

**Version:** 1.0.0 (February 2026)
**Component:** Worker Controller
**Source:** `src/worker-controller/application/hosted_services/worker_reconciler.py`

!!! note "Related Documentation"
    - [Worker Discovery & Observation](worker-discovery.md) — how changes are detected
    - [Auto-Scaling](../auto-scaling.md) — scale-up/down automation
    - [Idle Detection](../control-plane-api/idle-detection.md) — activity tracking
    - [Worker Templates](../resource-scheduler/worker-templates.md) — capacity definitions

---

## 1. Worker State Machine

Every CML Worker progresses through a well-defined set of statuses. The **Worker Reconciler** drives transitions by comparing the desired state (spec in MongoDB) with the actual cloud infrastructure state (EC2 + CML API).

```mermaid
stateDiagram-v2
    direction LR

    [*] --> PENDING: Worker created
    PENDING --> PROVISIONING: EC2 launched
    PENDING --> FAILED: Launch error

    PROVISIONING --> STARTING: EC2 instance running
    PROVISIONING --> FAILED: EC2 timeout

    STARTING --> RUNNING: EC2 + IP confirmed
    STARTING --> FAILED: Start error

    state running_state <<choice>>
    RUNNING --> running_state: Desired state check
    running_state --> STOPPING: desired = STOPPED
    running_state --> DRAINING: Scale-down drain
    running_state --> TERMINATING: desired = TERMINATED

    DRAINING --> STOPPING: Drain complete
    STOPPING --> STOPPED: EC2 stopped

    STOPPED --> STARTING: desired = RUNNING
    STOPPED --> TERMINATING: desired = TERMINATED

    TERMINATING --> TERMINATED: EC2 terminated
    TERMINATED --> [*]

    FAILED --> TERMINATING: Cleanup
    FAILED --> [*]: Abandoned

    classDef active fill:#4CAF50,color:white
    classDef warning fill:#FF9800,color:white
    classDef danger fill:#f44336,color:white
    classDef neutral fill:#9E9E9E,color:white
    classDef draining fill:#2196F3,color:white

    class RUNNING active
    class PENDING,PROVISIONING,STARTING warning
    class FAILED,TERMINATING danger
    class STOPPED,TERMINATED neutral
    class DRAINING draining
```

### Status Descriptions

| Status | Description | EC2 State |
|--------|-------------|-----------|
| **PENDING** | Worker record created, awaiting EC2 launch | — |
| **PROVISIONING** | EC2 instance launched, waiting for it to reach `running` | `pending` |
| **STARTING** | EC2 confirmed running, waiting for IP assignment | `running` |
| **RUNNING** | Fully operational — metrics collection, idle detection, license management active | `running` |
| **DRAINING** | Scale-down initiated — accepting no new workloads, transitioning to STOPPED | `running` → `stopping` |
| **STOPPING** | EC2 stop command issued, waiting for instance to stop | `stopping` |
| **STOPPED** | EC2 instance stopped (cost-saving state, EBS preserved) | `stopped` |
| **TERMINATING** | EC2 terminate command issued, waiting for termination | `shutting-down` |
| **TERMINATED** | EC2 instance fully terminated, resources released | `terminated` |
| **FAILED** | An error occurred during provisioning or lifecycle management | varies |

---

## 2. Reconciliation Dispatch

The `WorkerReconciler.reconcile_resource()` method dispatches each worker to the appropriate handler based on its current status:

```mermaid
flowchart TD
    Start["reconcile_resource(worker)"] --> Check{"worker.status?"}

    Check -->|PENDING| HP["_handle_pending"]
    Check -->|PROVISIONING| HPR["_handle_provisioning"]
    Check -->|STARTING| HS["_handle_starting"]
    Check -->|RUNNING| HR["_handle_running"]
    Check -->|STOPPING / DRAINING| HST["_handle_stopping"]
    Check -->|TERMINATING| HT["_handle_terminating"]
    Check -->|other| WARN["Log warning, SKIPPED"]

    HP --> Result["ReconciliationResult"]
    HPR --> Result
    HS --> Result
    HR --> Result
    HST --> Result
    HT --> Result
    WARN --> Result

    Result --> Done["Return to reconciliation loop"]

    style Start fill:#1565C0,color:white
    style Check fill:#FF8F00,color:white
    style Result fill:#2E7D32,color:white
```

Each handler returns a `ReconciliationResult` with one of four outcomes:

| Result | Meaning | Backoff |
|--------|---------|---------|
| `SUCCESS` | Convergence achieved, reset retry state | None |
| `REQUEUE` | Not yet converged, retry next cycle | None |
| `RETRY` | Transient error, retry with exponential backoff | 1s × 2^n (max 60s) |
| `SKIP` | No action needed or unknown status | None |

---

## 3. EC2 Provisioning Flow (_handle_pending)

When a worker is in `PENDING` status, the reconciler launches a new EC2 instance through a 6-step provisioning flow:

```mermaid
sequenceDiagram
    autonumber
    participant WR as Worker Reconciler
    participant API as Control Plane API
    participant EC2 as AWS EC2 SPI

    Note over WR: Worker status = PENDING

    WR->>API: get_worker_template(template_name)
    alt Template not found
        WR->>API: update_status(FAILED)
        WR-->>WR: return RETRY
    end

    WR->>WR: Extract instance_type from template

    WR->>WR: Get region config (ADR-018)
    Note right of WR: security_group_ids,<br/>subnet_id, key_name,<br/>default_tags from region

    WR->>EC2: resolve_ami(ami_name_filter)
    Note right of EC2: Returns most recent<br/>matching AMI

    WR->>WR: Build instance tags
    Note right of WR: Name, template_name,<br/>worker_id, lcm:managed_by<br/>+ region defaults<br/>+ worker overrides

    WR->>EC2: launch_instance(instance_type, ami_id, tags, ...)
    EC2-->>WR: instance_id

    WR->>API: update_status(PROVISIONING, instance_id)
    WR->>API: record_scaling_audit("provisioned")

    WR-->>WR: return SUCCESS
```

### Region Configuration (ADR-018)

Each AWS region has its own infrastructure configuration loaded from settings:

```yaml
# Example region config
aws_region_configs:
  us-east-1:
    region: us-east-1
    security_group_ids: ["sg-abc123"]
    subnet_id: "subnet-xyz789"
    key_name: "cml-workers"
    default_tags:
      environment: "production"
      team: "networking"
```

The reconciler resolves region config by:

1. Worker's explicit `aws_region` field
2. Settings default region (`aws_default_region`)

---

## 4. Instance Readiness (_handle_provisioning)

After EC2 launch, the reconciler polls for the instance to reach `running`:

```mermaid
flowchart TD
    Start["_handle_provisioning(worker)"] --> Check{"Has instance_id?"}
    Check -->|No| Fail["Update FAILED, return RETRY"]
    Check -->|Yes| GetState["EC2: get_instance_state()"]

    GetState --> EC2State{"EC2 state?"}

    EC2State -->|running| UpdateRunning["Update RUNNING<br/>with public/private IP"]
    EC2State -->|pending| Requeue["return REQUEUE"]
    EC2State -->|other| Retry["return RETRY"]

    UpdateRunning --> Success["Increment started_count<br/>return SUCCESS"]

    style Start fill:#1565C0,color:white
    style UpdateRunning fill:#4CAF50,color:white
    style Requeue fill:#FF9800,color:white
    style Fail fill:#f44336,color:white
```

---

## 5. Steady-State Management (_handle_running)

The `RUNNING` handler is the most complex — it performs six sequential checks every reconciliation cycle:

```mermaid
sequenceDiagram
    autonumber
    participant WR as Worker Reconciler
    participant EC2 as AWS EC2 SPI
    participant CW as CloudWatch SPI
    participant CML as CML System SPI
    participant API as Control Plane API

    Note over WR: Worker status = RUNNING

    rect rgb(255, 243, 224)
        Note over WR: Step 1: Desired State Check
        WR->>WR: Check desired_status
        alt desired = STOPPED
            WR->>API: update_status(STOPPING)
            WR-->>WR: return SUCCESS
        else desired = TERMINATED
            WR->>API: update_status(TERMINATING)
            WR-->>WR: return SUCCESS
        end
    end

    rect rgb(232, 245, 233)
        Note over WR: Step 2: EC2 Drift Detection
        WR->>EC2: get_instance_state(instance_id)
        alt EC2 state is not running
            WR->>API: update_status(mapped_status)
            WR-->>WR: return SUCCESS
        end
    end

    rect rgb(227, 242, 253)
        Note over WR: Step 3: Metrics Collection
        par CloudWatch Metrics
            WR->>CW: get_instance_metrics(instance_id)
            Note right of CW: cpu_utilization,<br/>memory_utilization,<br/>disk_utilization
        and CML System Metrics
            WR->>CML: get_system_info(ip_address)
            Note right of CML: labs_count,<br/>nodes_count,<br/>system_info,<br/>version
        end
        WR->>API: report_metrics(combined_metrics)
    end

    rect rgb(243, 229, 245)
        Note over WR: Step 4: License Reconciliation (ADR-016)
        WR->>WR: Check pending_license_operation
        alt operation = register
            WR->>CML: register_license(token)
            WR->>API: update_license_status(success/fail)
        else operation = deregister
            WR->>CML: deregister_license()
            WR->>API: update_license_status(success/fail)
        end
    end

    rect rgb(255, 235, 238)
        Note over WR: Step 5: Activity Detection
        alt idle_detection_enabled
            WR->>API: detect_worker_idle(worker_id)
            Note right of API: 4-step pipeline<br/>(see Idle Detection doc)
        end
    end

    rect rgb(224, 247, 250)
        Note over WR: Step 6: Scale-Down Evaluation (Phase 3)
        alt scale_down_enabled AND idle_result exists
            WR->>WR: _evaluate_scale_down(worker, idle_result)
            Note right of WR: 5 safety guards<br/>(see Auto-Scaling doc)
        end
    end

    WR-->>WR: return SUCCESS
```

### EC2-to-Worker Status Mapping

When EC2 state drifts from expected, the reconciler maps EC2 states to worker statuses:

| EC2 State | Mapped Worker Status |
|-----------|---------------------|
| `pending` | PROVISIONING |
| `running` | RUNNING |
| `stopping` | STOPPING |
| `stopped` | STOPPED |
| `shutting-down` | TERMINATING |
| `terminated` | TERMINATED |
| _other_ | UNKNOWN |

---

## 6. Shutdown Flow (_handle_stopping)

Handles both `STOPPING` and `DRAINING` statuses with the same EC2 stop logic:

```mermaid
flowchart TD
    Start["_handle_stopping(worker)"] --> HasID{"Has instance_id?"}

    HasID -->|No| MarkStopped1["Update STOPPED"]
    HasID -->|Yes| GetState["EC2: get_instance_state()"]

    GetState --> Found{"State found?"}
    Found -->|No| MarkStopped2["Update STOPPED"]
    Found -->|Yes| EC2State{"EC2 state?"}

    EC2State -->|stopped| MarkStopped3["Update STOPPED<br/>Increment stopped_count"]
    EC2State -->|running| StopEC2["EC2: stop_instance()"]
    EC2State -->|stopping| Requeue["return REQUEUE"]
    EC2State -->|other| Retry["return RETRY"]

    MarkStopped1 --> Success["return SUCCESS"]
    MarkStopped2 --> Success
    MarkStopped3 --> Success
    StopEC2 --> Requeue2["return REQUEUE"]

    style Start fill:#1565C0,color:white
    style MarkStopped1 fill:#4CAF50,color:white
    style MarkStopped2 fill:#4CAF50,color:white
    style MarkStopped3 fill:#4CAF50,color:white
    style StopEC2 fill:#FF9800,color:white
```

---

## 7. Termination Flow (_handle_terminating)

```mermaid
flowchart TD
    Start["_handle_terminating(worker)"] --> HasID{"Has instance_id?"}

    HasID -->|No| MarkTerm1["Update TERMINATED"]
    HasID -->|Yes| GetState["EC2: get_instance_state()"]

    GetState --> Found{"State found?"}
    Found -->|No| MarkTerm2["Update TERMINATED"]
    Found -->|Yes| EC2State{"EC2 state?"}

    EC2State -->|terminated| MarkTerm3["Update TERMINATED<br/>Increment terminated_count"]
    EC2State -->|shutting-down| Requeue["return REQUEUE"]
    EC2State -->|other| TermEC2["EC2: terminate_instance()"]

    MarkTerm1 --> Success["return SUCCESS"]
    MarkTerm2 --> Success
    MarkTerm3 --> Success
    TermEC2 --> Requeue2["return REQUEUE"]

    style Start fill:#1565C0,color:white
    style MarkTerm1 fill:#4CAF50,color:white
    style MarkTerm2 fill:#4CAF50,color:white
    style MarkTerm3 fill:#4CAF50,color:white
    style TermEC2 fill:#FF9800,color:white
```

---

## 8. Metrics Collection

The reconciler collects metrics from two independent sources during each `RUNNING` cycle:

```mermaid
flowchart LR
    subgraph Sources
        CW["AWS CloudWatch"]
        CML["CML System API"]
    end

    subgraph CloudWatch Metrics
        CPU["cpu_utilization (%)"]
        MEM["memory_utilization (%)"]
        DISK["disk_utilization (%)"]
    end

    subgraph CML System Metrics
        LABS["labs_count"]
        NODES["nodes_count"]
        SYS["system_info"]
        VER["cml_version"]
    end

    CW --> CPU & MEM & DISK
    CML --> LABS & NODES & SYS & VER

    CPU & MEM & DISK & LABS & NODES & SYS & VER --> Combined["Combined Metrics<br/>+ collected_at (UTC)"]
    Combined --> Report["API: report_metrics()"]
```

Each source has independent error handling — one failing does not block the other. Both require the worker to have the relevant identifiers (`ec2_instance_id` for CloudWatch, `ip_address` for CML API).

---

## 9. License Reconciliation (ADR-016)

License operations are performed **exclusively by the Worker Controller** via the CML System API. The Control Plane API sets a `pending_license_operation` on the worker, and the reconciler executes it:

```mermaid
sequenceDiagram
    autonumber
    participant CP as Control Plane API
    participant WR as Worker Reconciler
    participant CML as CML System SPI

    CP->>CP: Set pending_license_operation = "register"

    Note over WR: Next reconciliation cycle

    WR->>WR: Check pending_license_operation
    alt operation = register
        WR->>CP: Get license token
        WR->>CML: register_license(ip, token)
        alt Success
            WR->>CP: clear_pending_operation()
            WR->>CP: update_license_status(registered)
        else Failure
            WR->>CP: update_license_status(failed)
        end
    else operation = deregister
        WR->>CML: deregister_license(ip)
        alt Success
            WR->>CP: clear_pending_operation()
            WR->>CP: update_license_status(deregistered)
        else Failure
            WR->>CP: update_license_status(failed)
        end
    end
```

---

## 10. Reconciler Counters & Observability

The `WorkerReconciler` tracks 12 operational counters for observability:

| Counter | Description |
|---------|-------------|
| `provisioned_count` | EC2 instances successfully launched |
| `started_count` | EC2 instances confirmed running |
| `stopped_count` | EC2 instances confirmed stopped |
| `terminated_count` | EC2 instances confirmed terminated |
| `metrics_collected_count` | Metrics collection cycles completed |
| `idle_detection_count` | Idle detection checks performed |
| `auto_pause_count` | Auto-pauses triggered |
| `license_registered_count` | License registrations completed |
| `license_deregistered_count` | License deregistrations completed |
| `scale_down_drain_count` | Scale-down drains initiated |
| `running_worker_count` | Current running workers (updated each cycle) |

These counters are available via the `/admin/stats` endpoint and are included in the reconciler's `stats` property for Prometheus exposition.

---

## 11. Configuration Reference

| Setting | Env Variable | Default | Description |
|---------|-------------|---------|-------------|
| `reconcile_interval` | `RECONCILE_INTERVAL` | `30` | Seconds between reconciliation cycles |
| `reconcile_polling_enabled` | `RECONCILE_POLLING_ENABLED` | `True` | Enable polling-based reconciliation |
| `idle_detection_interval` | `IDLE_DETECTION_INTERVAL` | `300` | Min seconds between idle checks per worker |
| `cml_default_username` | `CML_DEFAULT_USERNAME` | `"admin"` | Default CML API username |
| `cml_default_password` | `CML_DEFAULT_PASSWORD` | `""` | Default CML API password |
| `scale_down_enabled` | `SCALE_DOWN_ENABLED` | `False` | Enable automatic scale-down |
| `min_workers` | `MIN_WORKERS` | `0` | Minimum running workers to maintain |
| `scale_down_cooldown_seconds` | `SCALE_DOWN_COOLDOWN_SECONDS` | `600` | Cooldown between scale-down actions |

See also: [Worker Discovery](worker-discovery.md) for etcd and leader election settings.
