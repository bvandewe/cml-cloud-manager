# Worker Discovery & Observation

**Version:** 1.0.0 (February 2026)
**Component:** Worker Controller (core patterns shared with Resource Scheduler and Lablet Controller)
**Source:** `src/core/lcm_core/infrastructure/hosted_services/`

!!! note "Related Documentation"
    - [Worker Lifecycle](worker-lifecycle.md) — what happens after a worker is discovered
    - [Auto-Scaling](../auto-scaling.md) — scale-up/down automation
    - [Background Scheduling](../../background-scheduling.md) — general scheduling patterns

---

## 1. Overview

All LCM controllers (Worker Controller, Resource Scheduler, Lablet Controller) share the same **observation and reconciliation infrastructure** provided by the `lcm-core` package. This architecture implements the Kubernetes-style **controller pattern** with three layers:

1. **Reconciliation** — periodic polling loop with concurrency control and backoff
2. **Leader Election** — etcd-based single-leader guarantee for HA
3. **Watch-Triggered** — reactive etcd watch for near-instant response

```mermaid
flowchart TB
    subgraph core["lcm-core Hosted Service Hierarchy"]
        direction TB
        HS["HostedService<br/>(neuroglia.hosting)"]
        RHS["ReconciliationHostedService[T]<br/>Polling loop, backoff, concurrency"]
        LEHS["LeaderElectedHostedService[T]<br/>etcd lease, single-leader"]
        WTHS["WatchTriggeredHostedService[T]<br/>etcd watch, debounce, dual-mode"]

        HS --> RHS
        RHS --> LEHS
        LEHS --> WTHS
    end

    subgraph controllers["Controller Implementations"]
        direction TB
        WR["WorkerReconciler<br/>watches /workers/"]
        SS["SchedulerHostedService<br/>watches /instances/"]
        LR["LabletReconciler<br/>watches /instances/"]
    end

    WTHS --> WR & SS & LR

    style core fill:#E3F2FD,stroke:#1565C0
    style controllers fill:#E8F5E9,stroke:#2E7D32
```

---

## 2. Dual-Mode Observation

Each controller operates in **dual mode** — combining baseline polling with reactive watching for optimal balance between reliability and responsiveness:

```mermaid
flowchart LR
    subgraph polling["Polling Mode (Baseline)"]
        direction TB
        Timer["Timer<br/>every interval_seconds"] --> Fetch["Fetch ALL resources<br/>from Control Plane API"]
        Fetch --> Reconcile["Reconcile each resource<br/>with semaphore concurrency"]
    end

    subgraph watching["Watch Mode (Reactive)"]
        direction TB
        Watch["etcd watch<br/>on key prefix"] --> Event["Key change event<br/>(PUT/DELETE)"]
        Event --> Debounce["Debounce<br/>(0.5s default)"]
        Debounce --> Single["Reconcile SINGLE<br/>changed resource"]
    end

    polling ~~~ watching

    style polling fill:#FFF3E0,stroke:#E65100
    style watching fill:#E8F5E9,stroke:#2E7D32
```

| Aspect | Polling | Watch |
|--------|---------|-------|
| **Trigger** | Timer (configurable interval) | etcd key change event |
| **Scope** | All active resources | Single changed resource |
| **Latency** | Up to `interval_seconds` (default: 30s) | ~0.5s (debounce window) |
| **Reliability** | High — full state resync every cycle | Depends on etcd connection |
| **Purpose** | Catch drift, ensure consistency | Fast reaction to state changes |
| **Failure mode** | Graceful — exponential backoff | Auto-reconnect with linear backoff |

!!! tip "Why Dual-Mode?"
    Polling alone creates up to 30-second latency for state changes. Watching alone risks missing changes during etcd disconnections. Dual-mode guarantees both **fast response** and **eventual consistency**.

---

## 3. Leader Election

Only one controller instance should be actively reconciling at any time. LCM uses **etcd leases** for leader election:

```mermaid
sequenceDiagram
    autonumber
    participant I1 as Instance A
    participant etcd as etcd Cluster
    participant I2 as Instance B

    Note over I1,I2: Both instances start up

    I1->>etcd: Grant lease (TTL=15s)
    etcd-->>I1: lease_id

    I1->>etcd: PUT /lcm/worker-controller/leader<br/>value=instance-A (IF key not exists)
    etcd-->>I1: Success (key created)

    Note over I1: Elected as LEADER

    I1->>I1: Start reconciliation loop
    I1->>I1: Start etcd watch

    I2->>etcd: Grant lease (TTL=15s)
    etcd-->>I2: lease_id

    I2->>etcd: PUT /lcm/worker-controller/leader<br/>value=instance-B (IF key not exists)
    etcd-->>I2: Failure (key exists)

    I2->>etcd: GET /lcm/worker-controller/leader
    etcd-->>I2: value=instance-A

    Note over I2: STANDBY — wait TTL/2, retry

    loop Every 5 seconds
        I1->>etcd: Lease keepalive
        etcd-->>I1: OK
    end

    Note over I1: Instance A crashes

    Note over etcd: Lease expires after 15s

    I2->>etcd: PUT /lcm/worker-controller/leader<br/>value=instance-B (IF key not exists)
    etcd-->>I2: Success

    Note over I2: Elected as LEADER
    I2->>I2: Start reconciliation loop
    I2->>I2: Start etcd watch
```

### Election Key Prefixes

Each controller uses a unique election key to ensure independent leadership:

| Controller | Election Key | Port |
|------------|-------------|------|
| Worker Controller | `/lcm/worker-controller/leader` | 8083 |
| Resource Scheduler | `/lcm/resource-scheduler/leader` | 8081 |
| Lablet Controller | `/lcm/lablet-controller/leader` | 8082 |

### Leader Lifecycle

```mermaid
stateDiagram-v2
    direction LR

    [*] --> Standby: Service starts
    Standby --> Campaigning: Attempt election

    state elected <<choice>>
    Campaigning --> elected
    elected --> Leader: Lease acquired
    elected --> Standby: Key exists, wait TTL/2

    state Leader {
        direction LR
        [*] --> Reconciling
        Reconciling --> Watching: Start watch
        Watching --> Reconciling: Watch event
    }

    Leader --> Standby: Lease lost / demoted
    Leader --> [*]: Service stopping
    Standby --> [*]: Service stopping
```

### Mock Mode

When no etcd client is configured (local development), the service immediately assumes leadership without election — useful for single-instance development environments.

---

## 4. Reconciliation Loop

The base `ReconciliationHostedService` provides a polling loop with concurrency control and exponential backoff:

```mermaid
flowchart TD
    Start["Service elected as leader"] --> Delay["Wait initial_delay<br/>(default: 5s)"]
    Delay --> Loop["Reconciliation cycle"]

    Loop --> Fetch["list_resources_async()<br/>Fetch all active resources"]
    Fetch --> Filter["Filter: skip in-progress,<br/>skip resources in backoff"]

    Filter --> Sem["Create tasks with<br/>semaphore(max_concurrent=10)"]

    Sem --> Reconcile["reconcile_resource(resource)"]
    Reconcile --> Result{"Result?"}

    Result -->|SUCCESS| Reset["Reset retry count<br/>and backoff timer"]
    Result -->|REQUEUE| SetRequeue["Mark for next cycle"]
    Result -->|RETRY| Backoff["Increment retries<br/>Calculate backoff"]
    Result -->|SKIP| Skip["Log and continue"]

    Reset --> Sleep
    SetRequeue --> Sleep
    Backoff --> Sleep
    Skip --> Sleep

    Sleep["Sleep interval_seconds<br/>(default: 30s)"] --> Loop

    style Start fill:#1565C0,color:white
    style Reconcile fill:#2E7D32,color:white
    style Backoff fill:#E65100,color:white
```

### Exponential Backoff Formula

When a resource reconciliation returns `RETRY`, the backoff delay is calculated as:

$$
\text{delay} = \min(\text{base} \times \text{multiplier}^{\text{retries}}, \text{max\_backoff})
$$

With defaults: $\text{base} = 1.0s$, $\text{multiplier} = 2.0$, $\text{max\_backoff} = 60.0s$

| Retry # | Delay |
|---------|-------|
| 0 | 1s |
| 1 | 2s |
| 2 | 4s |
| 3 | 8s |
| 4 | 16s |
| 5 | 32s |
| 6+ | 60s (capped) |

### Resource State Tracking

Each resource gets a `ResourceState` record tracking:

| Field | Purpose |
|-------|---------|
| `resource_id` | Unique identifier |
| `status` | Current reconciliation status (PENDING, IN_PROGRESS, SUCCESS, FAILED) |
| `retry_count` | Consecutive failures |
| `next_retry_at` | Earliest next attempt (backoff timer) |
| `last_reconciled_at` | Timestamp of last successful reconciliation |

---

## 5. Watch Event Processing

The `WatchTriggeredHostedService` layer adds reactive observation via etcd watches:

```mermaid
sequenceDiagram
    autonumber
    participant etcd as etcd Cluster
    participant Watch as Watch Loop
    participant Debounce as Debounce Timer
    participant Reconcile as Reconciler

    Note over Watch: Leader elected, watch started

    Watch->>etcd: watch_prefix("/workers/")

    loop Continuous stream
        etcd-->>Watch: PUT /workers/abc123 = ...
        Watch->>Watch: parse_watch_key() -> worker_id
        Watch->>Debounce: Add "abc123" to pending set

        alt No debounce timer running
            Debounce->>Debounce: Start timer (0.5s)
        end
    end

    Note over Debounce: Timer fires after 0.5s

    Debounce->>Debounce: Drain pending set -> [abc123, ...]

    loop For each resource ID
        Debounce->>Reconcile: fetch_single_resource(id)
        Reconcile->>Reconcile: reconcile_single_resource(resource)
    end
```

### Watch Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `watch_enabled` | `True` | Enable etcd watch mode |
| `watch_prefix` | varies | etcd key prefix to watch |
| `reconnect_delay` | `1.0s` | Delay between reconnect attempts |
| `max_reconnect_attempts` | `10` | Max reconnect attempts before giving up |
| `debounce_seconds` | `0.5s` | Debounce window for batching watch events |

### Watch Prefixes by Controller

| Controller | Watch Prefix | Event Type | Trigger Condition |
|------------|-------------|------------|-------------------|
| Worker Controller | `/workers/` | PUT | Any worker state change |
| Resource Scheduler | `/instances/` | PUT | Instance status = `PENDING_SCHEDULING` |
| Lablet Controller | `/instances/` | PUT | Instance status changes |

### Reconnection Strategy

If the etcd watch connection drops, the service automatically reconnects:

```mermaid
flowchart TD
    Start["Watch connection lost"] --> Attempt["Reconnect attempt #N"]
    Attempt --> Delay["Wait reconnect_delay × N<br/>(linear backoff)"]
    Delay --> Try["Establish new watch"]

    Try --> Result{"Success?"}
    Result -->|Yes| Watching["Resume watching<br/>Reset attempt counter"]
    Result -->|No| Check{"N < max_reconnect?"}
    Check -->|Yes| Attempt
    Check -->|No| Fallback["Give up watching<br/>Polling continues as fallback"]

    style Start fill:#f44336,color:white
    style Watching fill:#4CAF50,color:white
    style Fallback fill:#FF9800,color:white
```

!!! info "Graceful Degradation"
    If the watch connection is permanently lost, the controller continues operating in **polling-only mode**. The reconciliation loop remains active and catches all state changes within the polling interval.

---

## 6. Worker Discovery Service

In addition to reconciling known workers, the Worker Controller has a **discovery service** that finds unmanaged EC2 instances:

| Setting | Default | Description |
|---------|---------|-------------|
| `worker_discovery_enabled` | `True` | Enable auto-discovery |
| `discovery_interval` | `300s` (5 min) | Seconds between discovery scans |
| `worker_discovery_tag_filter` | `None` | EC2 tag filter for discovery |
| `worker_discovery_ami_filter` | `""` | AMI name filter for discovery |

The discovery service scans AWS EC2 for instances matching the configured tags (e.g., `cml-managed=true`) and creates worker records in the Control Plane API for any instances not already tracked.

---

## 7. Full Observation Timeline

This diagram shows how polling and watching interact during a typical scale-up scenario:

```mermaid
sequenceDiagram
    autonumber
    participant CP as Control Plane API
    participant etcd as etcd State Store
    participant WC as Worker Controller

    Note over CP: User creates worker via API
    CP->>etcd: PUT /workers/w-123 (status=PENDING)

    rect rgb(232, 245, 233)
        Note over WC: Watch event (< 0.5s latency)
        etcd-->>WC: Watch: PUT /workers/w-123
        WC->>WC: Debounce (0.5s)
        WC->>CP: Fetch worker w-123
        WC->>WC: reconcile_resource(w-123)
        Note right of WC: _handle_pending<br/>→ Launch EC2
    end

    CP->>etcd: PUT /workers/w-123 (status=PROVISIONING)

    rect rgb(232, 245, 233)
        Note over WC: Watch event (< 0.5s latency)
        etcd-->>WC: Watch: PUT /workers/w-123
        WC->>WC: reconcile_resource(w-123)
        Note right of WC: _handle_provisioning<br/>→ EC2 state = pending
    end

    rect rgb(255, 243, 224)
        Note over WC: Polling cycle (every 30s)
        WC->>CP: list_resources() → all active workers
        WC->>WC: reconcile_resource(w-123)
        Note right of WC: _handle_provisioning<br/>→ EC2 state = running!
    end

    CP->>etcd: PUT /workers/w-123 (status=RUNNING)
```

---

## 8. Prometheus Metrics

The reconciliation infrastructure exposes several Prometheus metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `reconcile_total` | Counter | Total reconciliations (by result) |
| `reconcile_duration_seconds` | Histogram | Reconciliation duration |
| `active_reconciles` | Gauge | Currently in-progress reconciliations |
| `resources_pending` | Gauge | Resources awaiting reconciliation |

These are initialized lazily on first use and tagged with the `metric_prefix` from `ReconciliationConfig` (e.g., `reconciliation_reconcile_total`).

---

## 9. Configuration Reference

### ReconciliationConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `interval_seconds` | `float` | `30.0` | Seconds between polling cycles |
| `initial_delay` | `float` | `5.0` | Startup delay before first cycle |
| `polling_enabled` | `bool` | `True` | Enable polling mode |
| `max_concurrent` | `int` | `10` | Max concurrent reconciliations |
| `backoff_base` | `float` | `1.0` | Base delay for exponential backoff |
| `max_backoff` | `float` | `60.0` | Maximum backoff delay |
| `backoff_multiplier` | `float` | `2.0` | Backoff multiplier |
| `metric_prefix` | `str` | `"reconciliation"` | Prometheus metric prefix |

### LeaderElectionConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `etcd_endpoints` | `list[str]` | `["localhost:2379"]` | etcd cluster endpoints |
| `election_key_prefix` | `str` | `"/elections"` | Base path for election keys |
| `lease_ttl` | `int` | `15` | Leader lease TTL in seconds |
| `retry_interval` | `float` | `5.0` | Election retry interval |
| `instance_id` | `str` | auto-generated | Unique instance identifier |
| `service_name` | `str` | `"service"` | Service name for election key |

### WatchConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `True` | Enable etcd watch mode |
| `prefix` | `str` | `""` | etcd key prefix to watch |
| `reconnect_delay` | `float` | `1.0` | Base reconnect delay |
| `max_reconnect_attempts` | `int` | `10` | Max reconnect tries |
| `debounce_seconds` | `float` | `0.5` | Event debounce window |
