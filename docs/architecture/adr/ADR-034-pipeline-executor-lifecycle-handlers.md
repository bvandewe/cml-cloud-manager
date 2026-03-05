# ADR-034: Pipeline Executor & Lifecycle Phase Handlers

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-03-02 |
| **Deciders** | Architecture Team |
| **Supersedes** | Partially supersedes [ADR-031](./ADR-031-checkpoint-instantiation-pipeline.md) §execution-model |
| **Related ADRs** | [ADR-011](./ADR-011-apscheduler-removal.md) (APScheduler Removal), [ADR-031](./ADR-031-checkpoint-instantiation-pipeline.md) (Checkpoint Pipeline), [ADR-030](./ADR-030-resource-observation-learn-from-live.md) (Resource Observation), [ADR-020](./ADR-020-session-entity-model.md) (Session Entity Model), [ADR-019](./ADR-019-labrecord-independent-aggregate.md) (LabRecord Aggregate) |
| **Related Decisions** | AD-PIPELINE-002, AD-PIPELINE-003, AD-PIPELINE-004, AD-PIPELINE-007, AD-PIPELINE-008, AD-PIPELINE-009 |

> **Errata (Sprint C):**
>
> - `fail_session()` referenced in §3 pseudocode is replaced by `terminate_session()` per AD-PIPELINE-008 (internal terminate endpoint)
> - Backward compatibility fallback (definitions without pipelines) is removed per AD-PIPELINE-009 — all definitions MUST have pipelines
> - Pipeline failures do NOT auto-trigger teardown per AD-PIPELINE-007 — reconciler retries with resumability, then terminates after max_retries exhausted
> - See `docs/implementation/ADR-034-sprint-c-prompt.md` for the authoritative implementation spec

## Context

### Problem 1: Pipeline Execution Stall

ADR-031 introduced a checkpoint-based instantiation pipeline with 9 DAG-ordered steps.
The design executes **one step per reconciliation cycle**, returning `ReconciliationResult.requeue()` after each step. However, `LabletSessionInstantiationProgressUpdatedDomainEvent` has **no etcd projector**, so progress updates don't trigger watch events. The next reconcile waits for the 30-second polling interval. With 9 steps, the pipeline takes **~4.5 minutes** instead of ~30 seconds.

### Problem 2: Single Pipeline, Hardcoded

ADR-031 only covers the `instantiate` pipeline. The system needs at least 4 more pipelines across the LabletSession lifecycle:

| Pipeline | Trigger Status | Purpose |
|----------|---------------|---------|
| `instantiate` | INSTANTIATING | Lab import, ports, LDS, readiness |
| `collect_evidence` | COLLECTING | Capture configs, screenshots, pcaps |
| `compute_grading` | GRADING | Evaluate evidence against rubric |
| `teardown` | STOPPING | Stop lab, deregister LDS, wipe, archive |
| _(future)_ `warmup` | WARMING | Pre-instantiate warm pool instances |

Each pipeline shares the same DAG execution mechanics but differs in steps.

### Problem 3: Reconciler Monolith

The `LabletReconciler` is **2009 lines** with a monolithic `reconcile()` that routes by status to `_handle_{status}()` methods. Each handler runs inline within the reconcile call and returns a `ReconciliationResult`. This one-reconcile-per-action model doesn't fit multi-step pipelines.

### Problem 4: LabletDefinition Aggregate Bloat

`LabletDefinitionState` carries **46 fields** spanning 5 distinct responsibilities. Pipeline definitions, when added, would be a 6th concern on an already overloaded aggregate. The `upstream_sync_status` field alone is an unbounded JSON blob containing 5 nested service results with their own status/version/logs.

### Problem 5: No Background Job Framework

[ADR-011](./ADR-011-apscheduler-removal.md) removed APScheduler in January 2026, replacing all background jobs with reconciliation loops. This was correct for simple poll-and-act patterns but doesn't address long-running, multi-step pipelines that need to self-drive within a lifecycle phase.

APScheduler 4.x was evaluated (async-native, MongoDB data store, Redis event broker, distributed scheduling) but rejected because:

1. It's **pre-release** — README explicitly warns "do NOT use in production"
2. It solves **scheduling** (when to run) not **orchestration** (DAG execution)
3. We'd still need PipelineExecutor on top — APScheduler adds a layer without eliminating one
4. It introduces a second scheduling paradigm alongside reconcilers (violates ADR-011's principle)
5. Our existing stack (MongoDB + etcd + reconcilers) already provides persistence, crash recovery, and leader election

## Decision

### 1. PipelineExecutor — DAG-Driven Inner Loop

Replace the one-step-per-reconcile pattern with a **PipelineExecutor** utility that runs all steps sequentially within a single invocation. The reconciler delegates to the executor; the executor self-drives through the DAG.

```
reconcile(session_id)
  → status routing: _handle_{status}()
  → handler ensures LifecyclePhaseHandler is active for this session
  → handler runs PipelineExecutor if a pipeline is defined
  → PipelineExecutor runs all steps in inner loop
  → progress persisted after each step (crash recovery)
  → on completion: status transition + etcd event
```

#### PipelineExecutor Responsibilities

| Concern | Implementation |
|---------|---------------|
| **DAG resolution** | Topological sort of steps by `needs` + skip evaluation |
| **Skip evaluation** | `simpleeval` library — safe Python expression evaluation, zero dependencies |
| **Step dispatch** | Handler lookup via `_step_{handler}()` naming convention |
| **Progress persistence** | After each step, persist to CPA via `update_pipeline_progress()` |
| **Retry** | Per-step `retry.max_attempts` and `retry.delay_seconds` |
| **Timeout** | Per-step `timeout_seconds` via `asyncio.wait_for()` |
| **Optional steps** | `optional: true` — failure doesn't block downstream steps |
| **Context injection** | `$SESSION`, `$DEFINITION`, `$WORKER`, `$STEPS` variables |
| **Output collection** | `outputs` section maps dot-path expressions to step result_data |

#### Expression Evaluation with `simpleeval`

`simpleeval` is a zero-dependency, single-file Python library (~30KB) that evaluates Python-like expressions via AST walking — no `eval()` or `exec()`. It provides:

- Safe sandboxing (blocks `_`-prefixed attributes, dangerous builtins)
- Python-native syntax matching YAML author expectations
- Configurable name handlers for `$SESSION`, `$DEFINITION`, etc.

```python
from simpleeval import SimpleEval

evaluator = SimpleEval()
evaluator.names = {
    "SESSION": session_read_model,
    "DEFINITION": definition_state,
    "WORKER": worker_read_model,
    "STEPS": completed_steps_data,
}

# skip_when expressions from YAML
evaluator.eval("not DEFINITION.form_qualified_name")  # → True if no FQN
evaluator.eval("not DEFINITION.port_template")         # → True if no ports
evaluator.eval("not SESSION.user_session_id")           # → True if no LDS session
```

Note: `$` prefix in YAML is convention for documentation clarity. The evaluator strips `$` before lookup.

#### PipelineResult

```python
@dataclass
class PipelineResult:
    """Result of a complete pipeline execution."""
    pipeline_name: str
    status: str  # "completed" | "failed" | "partial"
    steps_completed: int
    steps_failed: int
    steps_skipped: int
    duration_seconds: float
    outputs: dict[str, Any]  # Resolved output expressions
    error: str | None = None  # First fatal error
```

### 2. LifecyclePhaseHandler — Per-Session Background Tasks

Each lifecycle phase that involves multi-step work gets a **LifecyclePhaseHandler** — a managed `asyncio.Task` that self-drives the pipeline for a specific session.

```python
class LifecyclePhaseHandler:
    """Manages pipeline execution for one session in one lifecycle phase."""

    def __init__(
        self,
        session_id: str,
        pipeline_name: str,
        pipeline_def: dict,
        context: PipelineContext,
        executor: PipelineExecutor,
    ):
        self.session_id = session_id
        self.pipeline_name = pipeline_name
        self._pipeline_def = pipeline_def
        self._context = context
        self._executor = executor
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the handler as a background task."""
        if self._task and not self._task.done():
            return  # idempotent — already running
        self._task = asyncio.create_task(
            self._run(),
            name=f"pipeline:{self.pipeline_name}:{self.session_id}",
        )

    async def _run(self) -> None:
        """Execute the pipeline, handle completion/failure."""
        try:
            result = await self._executor.execute(
                pipeline_def=self._pipeline_def,
                context=self._context,
            )
            await self._on_complete(result)
        except asyncio.CancelledError:
            logger.info(f"Pipeline {self.pipeline_name} cancelled for {self.session_id}")
            raise
        except Exception as e:
            logger.error(f"Pipeline {self.pipeline_name} crashed for {self.session_id}: {e}")
            await self._on_error(e)

    async def _on_complete(self, result: PipelineResult) -> None:
        """Handle successful pipeline completion — trigger status transition."""
        # Implementation varies by pipeline type
        pass

    async def stop(self) -> None:
        """Cancel the handler gracefully."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
```

#### Reconciler Integration

The reconciler manages handlers via a `dict[str, LifecyclePhaseHandler]`:

```python
# In LabletReconciler
_active_handlers: dict[str, LifecyclePhaseHandler] = {}

async def _handle_instantiating(self, instance) -> ReconciliationResult:
    handler_key = f"{instance.id}:instantiate"

    if handler_key in self._active_handlers:
        handler = self._active_handlers[handler_key]
        if handler.is_running:
            return ReconciliationResult.success()  # handler is self-driving
        # Handler finished — clean up
        del self._active_handlers[handler_key]
        return ReconciliationResult.success()

    # No pipeline defined → error
    pipeline_def = self._get_pipeline_def(instance, "instantiate")
    if not pipeline_def:
        await self._api.fail_session(
            instance.id,
            reason="No 'instantiate' pipeline defined. Configure pipelines on the LabletDefinition.",
        )
        return ReconciliationResult.failed("No pipeline defined")

    # Start new handler
    handler = LifecyclePhaseHandler(
        session_id=instance.id,
        pipeline_name="instantiate",
        pipeline_def=pipeline_def,
        context=self._build_context(instance),
        executor=self._pipeline_executor,
    )
    self._active_handlers[handler_key] = handler
    await handler.start()
    return ReconciliationResult.success()
```

#### Leader Step-Down Cleanup

When the reconciler loses leadership, all active handlers are cancelled:

```python
async def _step_down(self) -> None:
    # Cancel all active pipeline handlers
    for key, handler in list(self._active_handlers.items()):
        await handler.stop()
    self._active_handlers.clear()
    # ... existing child service teardown ...
    await super()._step_down()
```

### 3. Concurrency Model — Watch Events, Per-Session Serialization, and Self-Driving

This section addresses three architectural questions:

1. How does a running `LifecyclePhaseHandler` coexist with incoming etcd watch events?
2. Should reconciliation be serialized per aggregate root?
3. With polling disabled, how does the system remain both reactive and proactive?

#### Current Reconciler Concurrency (Pre-ADR-034)

The `WatchTriggeredHostedService` base class provides two call paths into `reconcile()`:

| Path | Trigger | Scope | Concurrency |
|------|---------|-------|-------------|
| **Polling** | Timer every `reconcile_interval` | ALL non-terminal resources | Up to `max_concurrent` (10) via `asyncio.Semaphore` |
| **Watch** | etcd key change → debounce (0.5s) → drain-loop | Single resource by ID | **Sequential** — simple `for` loop |
| **Startup sweep** | Once on leader election | ALL non-terminal resources | Up to `max_concurrent` via polling path |

**Existing race condition**: The polling path checks `ResourceState.in_progress` before launching a reconcile task, but the watch path does **not** — it calls `_reconcile_single()` directly. A watch event and a polling cycle can reconcile the **same session concurrently** with no mutual exclusion.

For simple reconcile operations (check state, do one action, return), this race is mostly harmless — idempotent operations tolerate double-execution. But for `LifecyclePhaseHandler` management, the race can create duplicate handlers.

#### Per-Session Serialization via `asyncio.Lock`

**Decision**: Add a per-session `asyncio.Lock` to serialize reconciliation for the same aggregate root.

```python
class LabletReconciler(WatchTriggeredHostedService[LabletSessionReadModel]):
    _active_handlers: dict[str, LifecyclePhaseHandler] = {}
    _session_locks: dict[str, asyncio.Lock] = {}

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific session (lazy initialization)."""
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    async def reconcile(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Reconcile a single session — serialized per session_id."""
        lock = self._get_session_lock(instance.id)
        async with lock:
            return await self._reconcile_inner(instance)

    async def _reconcile_inner(self, instance: LabletSessionReadModel) -> ReconciliationResult:
        """Actual reconciliation logic — guaranteed single-threaded per session."""
        match instance.status:
            case "INSTANTIATING":
                return await self._handle_instantiating(instance)
            case "COLLECTING":
                return await self._handle_collecting(instance)
            # ... other status handlers ...
```

**Why per-session and not a global lock?**

| Approach | Throughput | Safety | Complexity |
|----------|-----------|--------|------------|
| **Global lock** (one at a time) | ❌ Sequential — 50 sessions = 50× latency | ✅ Simple | Low |
| **No lock** (current) | ✅ Concurrent | ❌ Handler duplication risk | Low |
| **Per-session lock** ✅ | ✅ Concurrent across sessions, serial per session | ✅ No duplication | Medium |

The lock is cheap — `asyncio.Lock` is non-blocking for non-contended cases (each session_id is a separate lock). Two reconciliations for _different_ sessions proceed concurrently. Two for the _same_ session queue correctly.

**Lock lifecycle**: Locks are lazily created and cleaned up during leader step-down:

```python
async def _step_down(self) -> None:
    for key, handler in list(self._active_handlers.items()):
        await handler.stop()
    self._active_handlers.clear()
    self._session_locks.clear()  # GC all locks on leadership loss
    await super()._step_down()
```

#### Watch + Handler Interaction Sequence

When a `LifecyclePhaseHandler` is actively running a pipeline and a new watch event arrives for the same session, the sequence is:

```
Timeline (single session: session-123)
────────────────────────────────────────────────────

t0: Watch event → status=INSTANTIATING
    reconcile(session-123) → acquires lock
      → _handle_instantiating() → no handler exists → create + start handler
      → handler.start() → asyncio.Task begins executing pipeline steps
      → return ReconciliationResult.success()
    → releases lock

t1: Handler is running step 3 of 9 (self-driving inner loop)
    Handler calls CPA: update_instantiation_progress(step=3, ...)
    CPA emits event → etcd projector writes /lcm/sessions/session-123/progress

t2: Watch event arrives for session-123 (from t1's etcd write)
    → added to _pending_reconciles set
    → debounced_reconcile() fires
    reconcile(session-123) → acquires lock
      → _handle_instantiating()
      → handler_key in _active_handlers? YES
      → handler.is_running? YES
      → return ReconciliationResult.success()  ← NO-OP
    → releases lock

t3: Handler is running step 7 of 9 (unaware of t2)
    (watch event was a no-op — handler is self-driving)

t4: Handler completes all 9 steps → _on_complete()
    → calls CPA: transition session INSTANTIATING → READY
    → CPA emits event → etcd writes /lcm/sessions/session-123/status=READY
    → handler task finishes naturally

t5: Watch event arrives for session-123 (from t4's status change)
    reconcile(session-123) → acquires lock
      → status is now READY → _handle_ready()
      → handler_key "session-123:instantiate" in _active_handlers? YES but done
      → clean up: del _active_handlers[handler_key]
      → _handle_ready() logic (no pipeline needed — acknowledge readiness)
      → return ReconciliationResult.success()
    → releases lock
```

**Key insight**: The handler IS the proactive loop. Watch events that arrive while a handler is running are intentional no-ops — the reconciler confirms the handler is alive and returns. No work is duplicated.

#### Self-Driving Without Polling — Reactive + Proactive Architecture

With polling **always disabled**, the system operates on two complementary mechanisms:

| Mechanism | Scope | Purpose | Trigger |
|-----------|-------|---------|---------|
| **etcd watch** (reactive) | Cross-step, cross-phase | Detect state transitions, launch/check handlers | External: CPA projector, admin action, another controller |
| **Inner loop** (proactive) | Within a single pipeline | Self-drive through all steps without external triggers | Internal: `PipelineExecutor.execute()` loop |

**Reactive path** — "Something changed, should I act?":

```
etcd key change → watch event → debounce → reconcile(session)
  → status routing → _handle_{status}()
  → check: handler running? → yes: no-op / no: start one
```

**Proactive path** — "I'm already acting, keep going":

```
LifecyclePhaseHandler._run()
  → PipelineExecutor.execute(pipeline_def, context)
    → for step in topological_order(steps):
        → evaluate skip_when
        → dispatch to _step_{handler}()
        → persist progress
        → collect outputs
    → return PipelineResult
  → _on_complete() → signal CPA → etcd write → triggers NEXT reactive cycle
```

**The handler replaces what polling would do.** In a polling model, each 30-second tick would re-enter `reconcile()` and advance one step. The handler instead runs a tight `async for` loop — it **is** the polling, just without the 30-second gaps.

**Lifecycle phase transitions are the bridge**: When a pipeline completes, the handler signals CPA (status transition), which writes to etcd, which triggers a watch event, which enters the reconciler for the **next** lifecycle phase. The chain is:

```
                ┌─── reactive ───┐      ┌── proactive ──┐
                │                │      │               │
watch event ──► reconcile() ──► handler ──► pipeline ──► steps
                                           │               │
                                           └── inner loop ─┘
                                                    │
                                              on_complete()
                                                    │
                                              CPA status change
                                                    │
                                              etcd projector write
                                                    │
                                              ┌─────▼─────┐
                                              │ watch event │ ◄── cycle repeats
                                              └────────────┘
```

#### Startup Recovery Without Polling

**Question**: If polling is disabled and the controller restarts, how are in-progress sessions recovered?

**Answer**: The **startup sweep** (existing mechanism) handles this. `WatchTriggeredHostedService` performs a one-time `_reconcile_all()` when it becomes leader. This lists all non-terminal sessions and reconciles each one. Sessions that were mid-pipeline will have their `instantiation_progress` checkpoint — the `PipelineExecutor` resumes from the last completed step.

```python
# In WatchTriggeredHostedService._step_up()
async def _step_up(self) -> None:
    """Called when this instance becomes leader."""
    await super()._step_up()
    # ... start watch stream ...
    # Startup sweep: reconcile all existing resources
    await self._reconcile_all()  # ← catches in-progress sessions
```

This means the system requires **exactly two mechanisms**:

1. **Startup sweep** — catch everything that exists (crash recovery)
2. **Watch events** — catch everything that changes (reactive)

No polling needed. The handler provides proactivity within a lifecycle phase.

#### Why Not a PipelineExecutor Loop That Mimics Polling?

A tempting alternative: have the `PipelineExecutor` run an infinite loop that periodically re-evaluates the session state, similar to a miniature polling reconciler:

```python
# ❌ Anti-pattern: executor-as-poller
async def execute_loop(self):
    while not self._cancelled:
        session = await self._fetch_current_state()
        result = await self._evaluate_and_run_next_step(session)
        if result.is_terminal:
            break
        await asyncio.sleep(5)  # mini-poll interval
```

**This is wrong because**:

1. **Unnecessary latency** — The executor knows the DAG; it doesn't need to re-discover what to do next
2. **Redundant state fetches** — Each iteration refetches session state that hasn't changed externally
3. **Violates separation of concerns** — The executor should execute a pipeline, not poll for work
4. **Duplicates reconciler responsibility** — The reconciler already handles "should I act?"; the executor handles "how do I act?"

The correct model is:

| Component | Responsibility | Loop? |
|-----------|---------------|-------|
| **Reconciler** | "Should I start/check a handler?" | No loop — event-driven (watch + startup sweep) |
| **LifecyclePhaseHandler** | "Is the pipeline running? Start/stop it." | No loop — one-shot task |
| **PipelineExecutor** | "Run all steps in DAG order." | Yes — `for step in dag` (finite, not infinite) |

The executor's loop is a **finite iteration over a DAG**, not an infinite polling loop. It terminates when all steps are complete (or one fails fatally). The reconciler never polls — it reacts to etcd events. The handler is a one-shot asyncio.Task — it runs the executor once and exits.

### 4. Pipeline Definitions — Inline in LabletDefinition YAML

Pipelines are defined inline in the LabletDefinition seed YAML under an optional `pipelines:` key. This key maps to a new `pipelines: dict | None` field on `LabletDefinitionState`.

#### Schema

```yaml
pipelines:
  {pipeline_name}:                    # e.g., "instantiate", "collect_evidence"
    description: str                  # Human-readable purpose
    trigger: "on_status:{status}"     # Which lifecycle status triggers this pipeline

    steps:
      - name: str                     # Unique step identifier
        handler: str                  # Maps to _step_{handler}() method
        description: str              # Human-readable purpose
        needs: [str]                  # DAG dependencies (step names)
        skip_when: str                # simpleeval expression → skip if truthy
        optional: bool                # If true, failure doesn't block downstream
        timeout_seconds: int          # asyncio.wait_for() timeout
        retry:                        # Optional retry configuration
          max_attempts: int
          delay_seconds: int

    outputs:                          # Dot-path expressions → pipeline results
      {key}: "$STEPS.{step_name}.{field}"
```

#### Context Variables

| Variable | Type | Description |
|----------|------|-------------|
| `$SESSION` | `LabletSessionReadModel` | The session being reconciled |
| `$DEFINITION` | `LabletDefinitionState` | The definition template (read-only) |
| `$WORKER` | Worker read model | The assigned worker |
| `$STEPS` | `dict[str, dict]` | Completed step `result_data` (DAG outputs) |

#### No Pipeline = Error

When a session enters a status that requires a pipeline (INSTANTIATING, COLLECTING, GRADING, STOPPING) but no matching pipeline is defined in the LabletDefinition:

1. The reconciler logs an error
2. The session transitions to an error state with a clear message: _"No '{pipeline_name}' pipeline defined. Configure pipelines on the LabletDefinition."_
3. The admin must add the pipeline to the definition and re-trigger

No hardcoded fallback pipeline. This forces explicit configuration.

### 5. Output Storage

Pipeline outputs are stored in two locations:

| Output Type | Storage Location | Access Path |
|-------------|-----------------|-------------|
| **Step metadata** | `LabletSession.instantiation_progress` (MongoDB) | Per-step status, result_data, timestamps |
| **Pipeline outputs** | `LabRecord` run history (appended as run record) | Cumulative execution history per lab |
| **File artifacts** | S3/RustFS bucket | `s3://{bucket_name}/{session_id}/{pipeline_name}/{artifact}` |
| **Score reports** | `ScoreReport` aggregate (via CPA command) | Created by `compute_grading` pipeline |

The `LabRecord` gains a `pipeline_runs` field — an append-only list of pipeline execution records:

```python
@dataclass
class PipelineRunRecord:
    pipeline_name: str           # "instantiate", "collect_evidence", etc.
    session_id: str              # Which session triggered this run
    started_at: datetime
    completed_at: datetime | None
    status: str                  # "completed" | "failed" | "cancelled"
    steps: list[dict]            # Per-step results
    outputs: dict[str, Any]      # Resolved output expressions
    error: str | None
```

### 6. LabletDefinition Decomposition Plan

The `LabletDefinitionState` aggregate is overloaded with 46 fields across 5+ responsibilities. This ADR initiates a decomposition:

#### Phase 1: Add `pipelines` (This ADR — Immediate)

Add `pipelines: dict | None` to `LabletDefinitionState`. Optional field, parsed from seed YAML.

#### Phase 2: Extract ContentSyncRecord (Separate ADR — Next)

Move content sync orchestration results out of the aggregate:

| Fields to Extract | Current Location | New Location |
|-------------------|-----------------|--------------|
| `upstream_sync_status` (unbounded blob) | `LabletDefinitionState` | `ContentSyncRecord` (child entity or separate aggregate) |
| `content_package_hash` | `LabletDefinitionState` | `ContentSyncRecord` |
| `upstream_version` | `LabletDefinitionState` | `ContentSyncRecord` |
| `upstream_date_published` | `LabletDefinitionState` | `ContentSyncRecord` |
| `upstream_instance_name` | `LabletDefinitionState` | `ContentSyncRecord` |
| `upstream_form_id` | `LabletDefinitionState` | `ContentSyncRecord` |
| `grade_xml_path` | `LabletDefinitionState` | `ContentSyncRecord` |
| `cml_yaml_path` | `LabletDefinitionState` | `ContentSyncRecord` |
| `cml_yaml_content` | `LabletDefinitionState` | `ContentSyncRecord` |
| `devices_json` | `LabletDefinitionState` | `ContentSyncRecord` |
| `last_synced_at` | `LabletDefinitionState` | `ContentSyncRecord` |
| `sync_status` | `LabletDefinitionState` | `ContentSyncRecord` |

**12 fields** move to `ContentSyncRecord`, leaving the definition with ~34 fields and a clear FK reference:

```python
# On LabletDefinitionState (after decomposition)
content_sync_record_id: str | None  # FK to ContentSyncRecord
```

#### Phase 3: UX Decomposition (Frontend — Follows Phase 2)

The Definition Details modal (see screenshot) reorganizes into:

| Tab/Section | Source | Before | After |
|-------------|--------|--------|-------|
| **Template** | LabletDefinitionState | Mixed with sync data | Clean: name, version, FQN, resources, ports |
| **Content Sync** | ContentSyncRecord | `upstream_sync_status` blob rendered inline | Separate panel/tab with service-by-service status |
| **Pipelines** | `LabletDefinitionState.pipelines` | Not shown | New tab showing pipeline DAGs with step configs |
| **Lifecycle** | LabletDefinitionState | Status + deprecation mixed | Status badge + deprecation section |

### 7. simpleeval Dependency

Add `simpleeval` to `lablet-controller/pyproject.toml`:

```toml
[tool.poetry.dependencies]
simpleeval = "^1.0"
```

Zero transitive dependencies. ~30KB. Pure Python.

## Implementation Plan

### Phase 1: Foundation (Sprint N)

| # | Task | Component | Effort |
|---|------|-----------|--------|
| 1.1 | Add `pipelines: dict \| None` to `LabletDefinitionState` | CPA domain | S |
| 1.2 | Update `LabletDefinitionCreatedDomainEvent` to carry `pipelines` | CPA domain | S |
| 1.3 | Update seeder to parse `pipelines` from YAML | CPA infrastructure | S |
| 1.4 | Add `pipelines` to `LabletDefinitionDto` | CPA application | S |
| 1.5 | Add `pipelines` to `LabletDefinitionReadModel` + `from_dict()` (definitions flow via HTTP API, not etcd) | lcm_core | S |
| 1.6 | Two seed files with pipeline definitions (done ✅) | CPA data | — |

### Phase 2: PipelineExecutor (Sprint N)

| # | Task | Component | Effort |
|---|------|-----------|--------|
| 2.1 | Create `PipelineExecutor` class in lablet-controller | lablet-controller | M |
| 2.2 | Add `simpleeval` dependency | lablet-controller | S |
| 2.3 | Implement DAG resolution with topological sort | lablet-controller | M |
| 2.4 | Implement `skip_when` evaluation via simpleeval | lablet-controller | S |
| 2.5 | Implement step dispatch, retry, timeout | lablet-controller | M |
| 2.6 | Implement `PipelineContext` with `$SESSION`, `$DEFINITION`, `$WORKER`, `$STEPS` | lablet-controller | S |
| 2.7 | Unit tests for executor (DAG, skip, retry, timeout, context) | lablet-controller | M |

### Phase 3: LifecyclePhaseHandler (Sprint N+1)

| # | Task | Component | Effort |
|---|------|-----------|--------|
| 3.1 | Create `LifecyclePhaseHandler` base class | lablet-controller | M |
| 3.2 | Add per-session `asyncio.Lock` to reconciler (`_session_locks`) | lablet-controller | S |
| 3.3 | Implement `_active_handlers` management in reconciler | lablet-controller | M |
| 3.4 | Refactor `_handle_instantiating()` to delegate to handler | lablet-controller | L |
| 3.4 | Implement `_handle_collecting()` with handler delegation | lablet-controller | M |
| 3.5 | Implement `_handle_grading()` with handler delegation | lablet-controller | M |
| 3.6 | Refactor `_handle_stopping()` to use teardown pipeline | lablet-controller | M |
| 3.7 | Leader step-down: cancel all active handlers | lablet-controller | S |
| 3.8 | Unit + integration tests | lablet-controller | L |

### Phase 4: Output Storage & LabRecord Integration (Sprint N+1)

| # | Task | Component | Effort |
|---|------|-----------|--------|
| 4.1 | Add `PipelineRunRecord` to LabRecord aggregate | CPA domain | M |
| 4.2 | Create `AppendPipelineRunCommand` | CPA application | S |
| 4.3 | Wire executor completion → CPA command | lablet-controller | S |
| 4.4 | S3 artifact upload for file outputs (evidence, screenshots) | lablet-controller | M |

### Phase 5: LabletDefinition Decomposition (Sprint N+2)

| # | Task | Component | Effort |
|---|------|-----------|--------|
| 5.1 | Design `ContentSyncRecord` aggregate/child entity (separate ADR) | Architecture | M |
| 5.2 | Create `ContentSyncRecord` domain entity | CPA domain | M |
| 5.3 | Migrate 12 fields from LabletDefinitionState | CPA domain | L |
| 5.4 | Update ContentSyncService to write to new entity | lablet-controller | M |
| 5.5 | Update read models and DTOs | CPA application | M |
| 5.6 | Database migration script | CPA infrastructure | M |
| 5.7 | Update API endpoints | CPA api | M |

### Phase 6: UX Redesign (Sprint N+2)

| # | Task | Component | Effort |
|---|------|-----------|--------|
| 6.1 | Redesign Definition Details modal with tabs | CPA UI | L |
| 6.2 | Add Pipelines tab with DAG visualization | CPA UI | L |
| 6.3 | Move Content Sync to separate panel/tab | CPA UI | M |
| 6.4 | Add pipeline execution status to Session detail | CPA UI | M |
| 6.5 | Real-time SSE events for pipeline step progress | CPA + lablet-controller | M |

## Consequences

### Positive

- **Pipeline stall eliminated**: Inner loop executes all steps in one go (~30s instead of ~4.5min)
- **Extensible**: New pipelines added via YAML definition, not code changes
- **Observable**: Per-step progress, timing, and status visible in real-time
- **Crash-safe**: Progress persisted after each step; resumed from last checkpoint on restart
- **Clean separation**: Definition = template, ContentSyncRecord = operational state, Pipeline = execution
- **No new scheduling paradigm**: Consistent with ADR-011 — reconcilers + asyncio.Tasks
- **Polling-free**: Watch events + startup sweep + self-driving handlers — no periodic timer needed
- **Concurrency-safe**: Per-session `asyncio.Lock` prevents handler duplication from overlapping watch/poll paths
- **Admin-first**: No magic defaults — explicit pipeline configuration required

### Negative

- **Breaking change**: Existing definitions without `pipelines` will error when sessions run
- **Migration effort**: Phase 5 decomposition touches many files across CPA
- **simpleeval dependency**: New library in lablet-controller (mitigated: zero-dep, single file)
- **Handler lifecycle complexity**: Managing asyncio.Tasks per session requires careful cancellation

### Risks

| Risk | Mitigation |
|------|-----------|
| Handler memory leak (tasks not cleaned up) | Leader step-down cancels all; periodic GC of completed handlers |
| Per-session lock accumulation | Lazy creation + clear on step-down; locks are ~100 bytes each |
| Watch event storm during pipeline | Handler check is O(1) dict lookup — no-op reconciles are cheap |
| simpleeval security | Server-side only, expressions from admin-authored YAML, not user input |
| Pipeline YAML schema evolution | Version field on pipeline (`pipeline_version: "1.0"`) |
| Decomposition breaks existing API clients | Backward-compatible DTO: keep fields on DTO, source from ContentSyncRecord |

## Appendix A: Comparison — One-Step-Per-Reconcile vs. PipelineExecutor

| Aspect | ADR-031 (Current) | ADR-034 (Proposed) |
|--------|-------------------|-------------------|
| Steps per reconcile | 1 | All (inner loop) |
| Time for 9 steps | ~4.5 min (30s × 9 polls) | ~30 sec |
| Progress persistence | ✅ After each step | ✅ After each step |
| Crash recovery | ✅ Resume from checkpoint | ✅ Resume from checkpoint |
| etcd projector needed | ✅ Required (missing = stall) | ❌ Not needed within pipeline (self-driving) |
| Polling required | ✅ Fallback drives progress | ❌ Watch + startup sweep only |
| Concurrency safety | ⚠️ Soft `in_progress` flag | ✅ Per-session `asyncio.Lock` |
| Reconciler complexity | Medium (dispatch per step) | Low (delegate to handler) |
| Pipeline definition | Hardcoded in reconciler | YAML in LabletDefinition |
| New pipeline effort | New code in reconciler | New YAML + step handlers |

## Appendix B: Full Pipeline YAML Examples

See seed files:

- `data/seeds/lablet_definitions/exam-associate-auto-v1.1-lab-2.5.1.yaml` — Full LDS pipeline (4 pipelines, 9+4+3+4 steps)
- `data/seeds/lablet_definitions/exam-professional-enterprise-v1.0-lab-1.1.yaml` — No-LDS pipeline (3 pipelines, skip_when pruning)
