# Scenario Engine — Job Execution Engine Design

| Attribute | Value |
|-----------|-------|
| **Document Version** | 1.0.0 |
| **Status** | Draft |
| **Created** | 2026-06-05 |
| **Author** | LCM Architecture Team |
| **Related** | [Scenario Engine README](../../src/scenario-engine/README.md), [ADR-044](../architecture/adr/ADR-044-scenario-engine-microservice.md), [DSL Specification](../architecture/dsl/DSL-SPECIFICATION.md) |

---

## 1. Problem Statement

The scenario-engine has scaffolded domain entities (`Job`, `PodDefinition`), CQRS commands (`SubmitJobCommand`, `CancelJobCommand`, `SyncContentCommand`), and a scenario registry (`@scenario` decorator). However, **no runtime exists** to pick up submitted jobs and execute their associated scenarios.

Currently, `SubmitJobCommandHandler` creates a `Job` aggregate in `SUBMITTED` state and persists it to MongoDB, but nothing transitions the job to `RUNNING`, invokes the scenario's `execute()` method, or emits completion/failure events.

### Scope

This document covers the **Job Execution Engine** — the hosted service responsible for:

1. Picking up submitted jobs and dispatching them to scenarios
2. Managing concurrency (bounded parallelism)
3. Providing execution context (adapters, progress reporting)
4. Handling timeouts, cancellation, and error transitions
5. Delivering CloudEvents callbacks on completion/failure

### Non-Scope

- DSL task DAG executor (Phase 3 — uses this engine as its host)
- Adapter implementations (CML, AWS, Proxmox — Phase 4)
- Content sync download logic (S3 — separate concern)
- ScenarioEngine↔LCM integration wiring (separate task)

---

## 2. Design Decisions

### 2.1 Dispatch Mechanism: Hybrid (Queue + Startup Sweep)

**Decision**: Use an in-process `asyncio.Queue` for immediate dispatch combined with a MongoDB sweep on startup to recover orphaned jobs.

| Approach | Pros | Cons |
|----------|------|------|
| **Polling only** (ReconciliationHostedService pattern) | Crash-resilient; stateless; proven pattern | Latency (poll interval); wasted DB queries when idle |
| **Queue only** (asyncio.Queue) | Zero latency; no DB polling overhead | Jobs lost on crash; queue state not persisted |
| **Hybrid** ✅ | Immediate dispatch + crash recovery; best of both | Slightly more complex; must deduplicate |

**Rationale**: The fire-and-forget API contract (`POST /jobs → 202 Accepted`) implies sub-second dispatch. A pure polling loop with 5s interval introduces unacceptable latency for the caller's UX. The startup sweep ensures no job is permanently orphaned after a service restart.

**Deduplication**: The executor checks `job.state.status` before starting. If a job is already `RUNNING` (e.g., re-discovered on startup but was mid-execution in a previous incarnation), it should be marked `FAILED` with a "service restarted" reason, since the execution context is lost.

### 2.2 Content Sync: No Coupling

**Decision**: Content synchronization (`PodDefinition` lifecycle) is a completely separate concern from job execution.

**Rationale**: Not all scenarios require content. The `pod_definition_id` on Job is an optional reference that scenarios can use if they need it. The executor does NOT gate execution on PodDefinition status. Scenarios that need content must check it themselves or use a `content_resolver` helper on `ScenarioContext`.

### 2.3 CloudEvents Delivery: Global Sink + Per-Job Override

**Decision**: CloudEvents are delivered to the global `settings.cloud_event_sink` by default. If a Job specifies a `callback_url`, events for that job are also emitted there in addition.

| Approach | Pros | Cons |
|----------|------|------|
| Per-job callback_url only | Simple; explicit per-submission | No centralized event observability |
| Global sink only | Central; consistent | Callers can't get direct notifications |
| **Global + override** ✅ | Flexible; global observability + caller control | Must handle both paths |

**Implementation**: A `CloudEventCallbackService` resolves the target URL per event. Uses `httpx.AsyncClient` with retry (3 attempts, exponential backoff). Fire-and-forget — delivery failures are logged + metricked but do NOT fail the job.

### 2.4 Scenario Context: Data + Typed Adapter Interfaces

**Decision**: `ScenarioContext` carries input data, job metadata, and typed adapter interfaces injected by the executor.

**Rationale**: Scenarios should not resolve their own dependencies. This follows DDD's dependency inversion — scenarios depend on abstractions, the executor provides implementations. This also enables testing: unit tests inject mock adapters via context.

### 2.5 Progress Reporting: Callback on Context

**Decision**: `ScenarioContext` exposes an `async report_progress(percentage: int, message: str, details: dict | None = None)` callback.

**Rationale**: Explicit, simple, and allows the executor to intercept progress calls for:

- Persisting to Job entity (`job.update_progress(...)`)
- Emitting progress CloudEvents (throttled by `job_progress_interval` setting)
- Updating Prometheus gauges

---

## 3. Component Architecture

```
application/services/
├── job_execution_service.py       # HostedService — manages lifecycle
├── scenario_context.py            # Context dataclass passed to scenarios
├── cloud_event_callback.py        # CloudEvent delivery to sink/callback_url
└── scenario_registry.py           # (existing) @scenario decorator registry

integration/services/
├── adapters/
│   ├── __init__.py
│   ├── adapter_base.py            # Abstract base for all infrastructure adapters
│   ├── cml_adapter.py             # CML API adapter (stub, Phase 4)
│   └── aws_adapter.py             # AWS adapter (stub, Phase 4)
└── cloud_event_client.py          # httpx-based CloudEvent HTTP client
```

### 3.1 JobExecutionService (HostedService)

**Responsibility**: Manage the job dispatch loop, concurrency, and graceful shutdown.

**Lifecycle** (follows `neuroglia.hosting.HostedService` contract):

```
start_async() ─┐
               ├─► _startup_sweep()        # Query MongoDB for orphaned SUBMITTED jobs
               ├─► _dispatch_loop()         # Main asyncio.Task consuming from queue
               └─► [ready to accept jobs]
                        │
              enqueue_job(job_id) ◄──────── called by SubmitJobCommandHandler
                        │
                        ▼
              _execute_job(job_id)           # Managed per-job asyncio.Task
                        │
                        ▼
              scenario.execute(input, ctx)   # Actual scenario invocation
                        │
                        ▼
              _on_job_complete(job, result)  # Persist + callback

stop_async() ──► cancel all running tasks ──► await graceful drain
```

**Concurrency control**: `asyncio.Semaphore(settings.max_concurrent_jobs)` — the dispatch loop acquires before spawning a job task.

**Key design choices**:

| Concern | Approach | Justification |
|---------|----------|---------------|
| Queue type | `asyncio.Queue[str]` (job IDs only) | Lightweight; full Job loaded from repo on execution |
| Task tracking | `dict[str, asyncio.Task]` keyed by job_id | Enables cancellation by job_id |
| Timeout | `asyncio.wait_for(scenario.execute(...), timeout=...)` | Per-job timeout from settings or job-level override |
| Graceful shutdown | Cancel all tasks, await with shield, mark FAILED | Prevents zombie jobs on redeploy |
| Error isolation | Each job in its own try/except | One job failure doesn't crash the service |

### 3.2 ScenarioContext

**Responsibility**: Provide everything a scenario needs to execute without importing application-layer services.

```python
@dataclass
class ScenarioContext:
    """Execution context injected into scenario.execute()."""

    # Identity
    job_id: str
    scenario_name: str
    scenario_version: str

    # Input/Output
    input_data: dict[str, Any]

    # References (optional)
    pod_definition_id: str | None
    callback_url: str | None

    # Adapters (typed interfaces — implementations injected by executor)
    adapters: AdapterRegistry  # keyed by adapter type (cml, aws, proxmox, etc.)

    # Progress reporting
    report_progress: Callable[[int, str, dict | None], Awaitable[None]]

    # Cancellation
    cancellation_event: asyncio.Event  # set when cancel requested

    # Logging (pre-configured with job_id context)
    logger: logging.Logger
```

**AdapterRegistry** is a simple typed dict/mapping:

```python
@dataclass
class AdapterRegistry:
    """Registry of infrastructure adapters available to scenarios."""

    _adapters: dict[str, AdapterBase]

    def get(self, adapter_type: str) -> AdapterBase | None: ...
    def require(self, adapter_type: str) -> AdapterBase: ...  # raises if missing
```

**Why a dataclass and not a class with methods?** Scenarios should only read context and call adapters. Making it a frozen dataclass communicates "this is your input, not a mutable service."

### 3.3 CloudEventCallbackService

**Responsibility**: Deliver CloudEvents to the appropriate sink URL.

**Events emitted**:

| Cloud Event Type | Trigger | Payload |
|------------------|---------|---------|
| `scenario_engine.job.started.v1` | Job transitions to RUNNING | `{job_id, scenario_name, started_at}` |
| `scenario_engine.job.progress.v1` | Scenario calls `report_progress()` | `{job_id, percentage, message, details}` |
| `scenario_engine.job.completed.v1` | Scenario returns `ScenarioResult.completed(...)` | `{job_id, output_data, artifacts, duration}` |
| `scenario_engine.job.failed.v1` | Scenario raises or returns `ScenarioResult.failed(...)` | `{job_id, error, duration}` |
| `scenario_engine.job.cancelled.v1` | Job cancelled via API | `{job_id, cancelled_at}` |

**Delivery semantics**: At-most-once with best-effort retry (3 attempts, 1s/2s/4s backoff). Failures are logged and metricked but do not affect job state.

**Progress throttling**: At most one progress event per `settings.job_progress_interval` seconds per job. The latest progress is always delivered; intermediate calls within the interval are deduplicated.

### 3.4 Cancellation Flow

```
User → DELETE /api/v1/jobs/{id}
  → CancelJobCommandHandler
    → job.cancel()                 # Domain event emitted
    → repository.update_async()
    → executor.request_cancel(job_id)  # Sets cancellation_event + cancels asyncio.Task
```

**Cooperative vs. Hard cancellation**:

- **Cooperative**: `ScenarioContext.cancellation_event` is an `asyncio.Event`. Well-behaved scenarios check it between steps.
- **Hard**: After a grace period (e.g., 10s), the executor cancels the `asyncio.Task` via `task.cancel()`. The scenario receives `asyncio.CancelledError`.
- **Final**: On shutdown, all running tasks are hard-cancelled immediately.

### 3.5 Registration in main.py

Following the Neuroglia pattern (identical to `LabletReconciler.configure(builder.services, settings)` in lablet-controller):

```python
# In create_app()
JobExecutionService.configure(builder.services, settings)
```

The `configure()` class method registers the service as both a **singleton** and a **HostedService**. The `build_app_with_lifespan()` call auto-discovers and starts it.

---

## 4. Interaction Sequence

```
┌────────┐       ┌──────────────┐      ┌──────────────────┐      ┌─────────────┐
│ Caller │       │ JobsCtrl/Cmd │      │ JobExecService   │      │  Scenario   │
└───┬────┘       └──────┬───────┘      └────────┬─────────┘      └──────┬──────┘
    │  POST /jobs       │                       │                       │
    │──────────────────►│                       │                       │
    │                   │ persist Job(SUBMITTED) │                       │
    │                   │───────────────────────►│ enqueue_job(id)       │
    │                   │                       │◄──────────────────────│
    │  202 {job_id}     │                       │                       │
    │◄──────────────────│                       │                       │
    │                   │                       │ semaphore.acquire()    │
    │                   │                       │──────┐                │
    │                   │                       │      │ load Job       │
    │                   │                       │◄─────┘                │
    │                   │                       │ job.start()           │
    │                   │                       │ persist(RUNNING)      │
    │                   │                       │ emit started CE       │
    │                   │                       │                       │
    │                   │                       │ scenario.execute()    │
    │                   │                       │──────────────────────►│
    │                   │                       │                       │
    │                   │                       │   report_progress()   │
    │                   │                       │◄──────────────────────│
    │                   │                       │ emit progress CE      │
    │                   │                       │                       │
    │                   │                       │   ScenarioResult      │
    │                   │                       │◄──────────────────────│
    │                   │                       │                       │
    │                   │                       │ job.complete(output)   │
    │                   │                       │ persist(COMPLETED)    │
    │                   │                       │ emit completed CE     │
    │                   │                       │ semaphore.release()   │
    └                   └                       └                       └
```

---

## 5. Error Handling Strategy

| Failure Mode | Detection | Recovery |
|--------------|-----------|----------|
| Scenario raises exception | `try/except` in `_execute_job` | `job.fail(str(exc))` → persist → emit failed CE |
| Scenario exceeds timeout | `asyncio.wait_for()` raises `TimeoutError` | Same as exception — mark FAILED with timeout error |
| Scenario returns `ScenarioResult.failed(...)` | Check `result.status` | `job.fail(result.error)` → persist → emit failed CE |
| Service crash mid-execution | Startup sweep finds RUNNING jobs | Mark as FAILED ("service restarted") — cannot resume |
| MongoDB unavailable | Repository raises on persist | Log error; retry once; if still fails, job stays in last known state |
| CloudEvent delivery fails | httpx timeout/error | Log + metric; does NOT affect job state |
| Adapter call fails inside scenario | Scenario catches and returns `ScenarioResult.failed(...)` | Scenario is responsible for its own error handling |

### Startup Sweep Rules

On `start_async()`, query MongoDB for:

1. **SUBMITTED** jobs → re-enqueue into `asyncio.Queue` for execution
2. **RUNNING** jobs → mark as FAILED with reason "service restarted; execution context lost"

This ensures no job remains in a terminal-limbo state after a crash/redeploy.

---

## 6. Concurrency Model

```
                        ┌─────────────────────────────┐
                        │   JobExecutionService       │
                        │                             │
  enqueue_job(id) ────► │   asyncio.Queue[str]        │
                        │        │                    │
                        │        ▼                    │
                        │   _dispatch_loop (Task)     │
                        │        │                    │
                        │   semaphore.acquire()       │
                        │        │                    │
                        │        ▼                    │
                        │   create_task(_execute_job) │──► _running_tasks[job_id]
                        │        │                    │
                        │   (up to max_concurrent)    │
                        └─────────────────────────────┘
```

- **Semaphore**: `asyncio.Semaphore(settings.max_concurrent_jobs)` — defaults to 10
- **Backpressure**: If all slots full, `_dispatch_loop` blocks on `semaphore.acquire()`. Jobs stay in queue.
- **Queue is unbounded**: Acceptable because job submission rate is low (controller-initiated, not user-facing)

---

## 7. Observability

### Prometheus Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `se_jobs_submitted_total` | Counter | scenario_name, scenario_version | Total jobs submitted |
| `se_jobs_completed_total` | Counter | scenario_name, status (completed/failed/cancelled) | Outcome tracking |
| `se_jobs_active` | Gauge | — | Currently executing jobs |
| `se_job_duration_seconds` | Histogram | scenario_name | Execution time distribution |
| `se_callback_deliveries_total` | Counter | status (success/failed) | CloudEvent delivery reliability |

### Structured Logging

All log entries within job execution include:

```python
logger = logging.getLogger(__name__).getChild(f"job:{job_id}")
```

This enables filtering by job_id in aggregated logs.

---

## 8. Configuration

All settings already exist in `application/settings.py`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `max_concurrent_jobs` | 10 | Semaphore capacity |
| `job_default_timeout` | 600s | Per-job timeout (10 min) |
| `job_progress_interval` | 5s | Progress CloudEvent throttle |
| `cloud_event_sink` | "" | Global CloudEvent delivery URL |

No new settings required for Phase 2 implementation.

---

## 9. Testing Strategy

### Unit Tests

| Test | Validates |
|------|-----------|
| `test_job_execution_service_startup_sweep` | Orphaned SUBMITTED jobs re-enqueued; RUNNING jobs failed |
| `test_job_execution_service_dispatch` | Job transitions SUBMITTED → RUNNING → COMPLETED |
| `test_job_execution_service_timeout` | Job exceeding timeout transitions to FAILED |
| `test_job_execution_service_cancellation` | Cancel sets event + cancels task → CANCELLED |
| `test_job_execution_service_concurrency` | Semaphore limits parallel execution |
| `test_scenario_context_progress` | Progress callback persists + throttles events |
| `test_cloud_event_callback_delivery` | Events formatted correctly, retry on failure |
| `test_cloud_event_callback_per_job_override` | Job callback_url takes priority over global sink |

### Integration Tests

| Test | Validates |
|------|-----------|
| `test_submit_and_execute_e2e` | Full flow: submit → execute mock scenario → completed |
| `test_startup_recovery` | Kill service mid-job → restart → orphan detected |

### Mock Scenario for Testing

```python
@scenario(name="echo", version="v1", description="Echo input as output (test utility)")
class EchoScenario:
    async def execute(self, input_data: dict, context: ScenarioContext) -> ScenarioResult:
        await context.report_progress(50, "Processing...")
        return ScenarioResult.completed(output_data=input_data)
```

---

## 10. Implementation Order

| Step | Component | Depends On | Estimated Complexity |
|------|-----------|------------|---------------------|
| 1 | `ScenarioContext` dataclass + `AdapterRegistry` | None | Low |
| 2 | `CloudEventCallbackService` | Settings | Medium |
| 3 | `JobExecutionService` (HostedService) | ScenarioContext, repositories | High |
| 4 | Wire `enqueue_job()` into `SubmitJobCommandHandler` | JobExecutionService | Low |
| 5 | Wire `request_cancel()` into `CancelJobCommandHandler` | JobExecutionService | Low |
| 6 | Register in `main.py` via `configure()` | All above | Low |
| 7 | `EchoScenario` test scenario | ScenarioContext | Low |
| 8 | Unit tests | All above | Medium |
| 9 | Integration test (full flow) | All above | Medium |

---

## 11. Alignment with Established Patterns

| Pattern | Reference Implementation | Scenario Engine Equivalent |
|---------|--------------------------|----------------------------|
| HostedService lifecycle | `ReconciliationHostedService` (lcm-core) | `JobExecutionService.start_async() / stop_async()` |
| Semaphore concurrency | `ReconciliationHostedService._semaphore` | Same pattern, `max_concurrent_jobs` |
| Managed asyncio.Task per work item | `LifecyclePhaseHandler._task` (lablet-controller) | `_running_tasks[job_id]` dict |
| Decorator-based registry | `@step_handler` (lablet-controller), `@scenario` (SE) | Unchanged — executor resolves from registry |
| CloudEvent emission | `CloudEventPublisher` (control-plane-api) | `CloudEventCallbackService` (httpx-based, no bus needed) |
| Context bag for execution | `PipelineContext` (lablet-controller) | `ScenarioContext` (lighter — no CML-specific fields) |
| CQRS self-contained command | All services | `SubmitJobCommand` already exists; adds `enqueue_job()` call |
| `configure()` class method | `LabletReconciler.configure(builder.services, settings)` | `JobExecutionService.configure(builder.services, settings)` |
| Startup recovery | `_startup_reconcile_sweep()` (WatchTriggeredHostedService) | `_startup_sweep()` — same concept, different query |

---

## 12. Open Questions (Deferred to Implementation)

1. **Job priority**: Should the queue support priority levels? (Not needed for MVP — FIFO is sufficient)
2. **Job retry**: Should failed jobs be retryable via API? (Recommend: yes, via a new `RetryJobCommand` that re-submits with same input)
3. **Progress persistence frequency**: Should every `report_progress()` call write to MongoDB, or only on completion? (Recommend: write on each call — jobs are low-volume and progress survives crashes)
4. **Adapter lifecycle**: Should adapters be per-job (fresh) or shared (singleton)? (Recommend: shared singletons — they hold connection pools. Scenarios get references via context.)

---

## 13. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Job stuck in RUNNING after crash | Medium | Medium | Startup sweep marks orphans as FAILED |
| Scenario leaks resources (connections, files) | Medium | High | Timeout enforcement + scenario guidelines doc |
| Queue overflow on burst submissions | Low | Low | Queue is unbounded; bounded by semaphore anyway |
| CloudEvent sink unreachable | Medium | Low | Retry + fire-and-forget; does not block job lifecycle |
| Long-running scenario blocks shutdown | Medium | Medium | Grace period + hard cancel after N seconds |
