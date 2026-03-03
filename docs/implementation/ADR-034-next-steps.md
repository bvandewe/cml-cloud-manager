# ADR-034 Implementation — Next Steps

| Attribute | Value |
|-----------|-------|
| **Status** | Active |
| **Created** | 2026-03-02 |
| **Parent ADR** | [ADR-034](../architecture/adr/ADR-034-pipeline-executor-lifecycle-handlers.md) |
| **Last Updated** | 2026-03-02 |

## 1. Current State Summary

### Phase 1 Audit (Foundation)

| Task | Status | Evidence |
|------|--------|----------|
| 1.1 — `pipelines: dict \| None` on `LabletDefinitionState` | ✅ DONE | `control-plane-api/domain/entities/lablet_definition.py` |
| 1.2 — `LabletDefinitionCreatedDomainEvent` carries `pipelines` | ✅ DONE | `control-plane-api/domain/events/lablet_definition_events.py` |
| 1.3 — Seeder parses `pipelines` from YAML | ✅ DONE | `control-plane-api/infrastructure/seeding/lablet_definition_seeder.py` |
| 1.4 — `pipelines` in `LabletDefinitionDto` + mapper | ✅ DONE | `control-plane-api/application/dtos/lablet_definition_dto.py` |
| 1.5 — ~~etcd projector~~ → `LabletDefinitionReadModel.pipelines` | ❌ **REFRAMED** | See §2 below |
| 1.6 — Two seed files with pipeline definitions | ✅ DONE | `data/seeds/lablet_definitions/exam-*.yaml` |

### Critical Discovery: Task 1.5 Reframed

The original ADR-034 Phase 1 Task 1.5 said _"Update etcd projector to include `pipelines` in definition keys."_ This was based on a wrong assumption. **LabletDefinitions do NOT flow through etcd.** They flow through an HTTP API:

```
lablet-controller → GET /api/internal/lablet-definitions/{id} → CPA → JSON response
                  → LabletDefinitionReadModel.from_dict(data)
                  → stored in _definition_cache (never invalidated)
```

**The real gap is:** `LabletDefinitionReadModel` (in `lcm_core`) does **NOT** have a `pipelines` field. Without it, the `PipelineExecutor` cannot access pipeline definitions from the cached definition.

### What Does NOT Exist Yet

| Component | Location | Status |
|-----------|----------|--------|
| `LabletDefinitionReadModel.pipelines` field | `lcm_core/domain/entities/read_models/` | ❌ Missing |
| `simpleeval` dependency | `lablet-controller/pyproject.toml` | ❌ Not added |
| `PipelineExecutor` class | `lablet-controller/application/` | ❌ Not created |
| `PipelineContext` dataclass | `lablet-controller/application/` | ❌ Not created |
| `PipelineResult` dataclass | `lablet-controller/application/` | ❌ Not created |
| `LifecyclePhaseHandler` class | `lablet-controller/application/` | ❌ Not created |
| Per-session `asyncio.Lock` on reconciler | `lablet_reconciler.py` | ❌ Not added |
| `PipelineRunRecord` on `LabRecord` | `control-plane-api/domain/entities/` | ❌ Not created |

### What DOES Exist (Reusable)

| Component | Location | Reusability |
|-----------|----------|-------------|
| 9 `_step_*` handler methods | `lablet_reconciler.py` L582–L2009 | ✅ Keep — executor dispatches to these |
| `_build_default_progress()` | `lablet_reconciler.py` | ⚠️ Replace with pipeline YAML parsing |
| `_next_executable_step()` | `lablet_reconciler.py` | ⚠️ Replace with DAG topological sort |
| `_is_pipeline_complete()` | `lablet_reconciler.py` | ⚠️ Replace with PipelineResult check |
| `_get_step_result_data()` | `lablet_reconciler.py` | ✅ Keep — used by step handlers |
| `_handle_instantiating()` | `lablet_reconciler.py` L497–L577 | 🔄 Refactor to delegate to handler |
| `_definition_cache` | `lablet_reconciler.py` | ✅ Keep — now includes pipelines |
| 879-line test file | `tests/test_instantiation_pipeline.py` | 🔄 Adapt tests for PipelineExecutor |

---

## 2. Recommended Implementation Order

### Sprint A: Complete Foundation (Phase 1.5 + Phase 2 Prep)

**Goal:** Close the data flow gap so pipeline definitions reach the lablet-controller.

#### A1: Add `pipelines` to `LabletDefinitionReadModel` (lcm_core)

**File:** `src/core/lcm_core/domain/entities/read_models/lablet_definition_read_model.py`

**Changes:**

1. Add field: `pipelines: dict | None = None`
2. Update `from_dict()`: add `pipelines=data.get("pipelines")`
3. No new imports needed — `dict` and `None` are builtins, `Any` already imported

**Validation:**

- Run lcm_core tests (if any)
- Run lablet-controller tests to confirm no regressions
- Manually verify: start CPA, call `GET /api/internal/lablet-definitions/{id}` for a seeded definition → confirm `pipelines` present in JSON response

**Acceptance criteria:**

- [ ] `LabletDefinitionReadModel` has `pipelines: dict | None = None`
- [ ] `from_dict()` parses `pipelines` from API response
- [ ] Existing tests still pass

#### A2: Add `simpleeval` dependency to lablet-controller

**File:** `src/lablet-controller/pyproject.toml`

**Changes:**

```toml
[tool.poetry.dependencies]
simpleeval = "^1.0"  # Safe expression evaluation for skip_when (ADR-034)
```

**Then:** `cd src/lablet-controller && poetry lock && poetry install`

**Acceptance criteria:**

- [ ] `poetry show simpleeval` shows version ≥1.0
- [ ] `python -c "from simpleeval import SimpleEval; print('OK')"` works in the venv

#### A3: Update ADR-034 Phase 1 Task 1.5 description

**File:** `docs/architecture/adr/ADR-034-pipeline-executor-lifecycle-handlers.md`

**Changes:** Rewrite task 1.5 in the implementation plan table:

```
| 1.5 | Add `pipelines` to `LabletDefinitionReadModel` + `from_dict()` | lcm_core | S |
```

---

### Sprint B: PipelineExecutor (Phase 2)

**Goal:** Create the DAG execution engine — pure logic, no reconciler integration yet.

#### B1: Create `PipelineContext` dataclass

**File:** `src/lablet-controller/application/models/pipeline_context.py` (new)

```python
@dataclass
class PipelineContext:
    """Immutable context available to all pipeline steps."""
    session: LabletSessionReadModel
    definition: LabletDefinitionReadModel
    worker_ip: str
    worker_cml_username: str
    worker_cml_password: str
    api: ControlPlaneApiClient  # For CPA calls
    cml: CmlLabsSpi             # For CML API calls
    lds: LdsSpi | None          # For LDS calls (None if no LDS)
    steps_data: dict[str, dict] # Accumulated step result_data
```

**Key decision:** `PipelineContext` replaces the implicit dependency on `self._api`, `self._cml_api`, `self._lds_api` that step handlers currently use via `self`. Step handlers will need to receive context as a parameter.

#### B2: Create `PipelineResult` dataclass

**File:** `src/lablet-controller/application/models/pipeline_result.py` (new)

```python
@dataclass
class PipelineResult:
    pipeline_name: str
    status: str  # "completed" | "failed" | "partial"
    steps_completed: int
    steps_failed: int
    steps_skipped: int
    duration_seconds: float
    outputs: dict[str, Any]
    error: str | None = None
```

#### B3: Create `PipelineExecutor` class

**File:** `src/lablet-controller/application/services/pipeline_executor.py` (new)

This is the core implementation. Key methods:

| Method | Purpose |
|--------|---------|
| `execute(pipeline_def, context, step_dispatcher) → PipelineResult` | Main entry point — runs DAG inner loop |
| `_resolve_dag(steps) → list[dict]` | Topological sort of steps by `needs` |
| `_evaluate_skip(expr, context) → bool` | `simpleeval`-based `skip_when` evaluation |
| `_execute_step(step, context, dispatcher) → StepResult` | Dispatch + retry + timeout |
| `_resolve_outputs(output_defs, steps_data) → dict` | Dot-path expression resolution |

**Critical design constraint:** The executor does NOT import `LabletReconciler`. It receives a `step_dispatcher` callable (or protocol) that maps step handler names to async functions. This keeps the executor testable in isolation.

```python
# Step dispatcher protocol
StepDispatcher = Callable[[str, LabletSessionReadModel, dict], Awaitable[dict]]

# Usage in executor:
result = await step_dispatcher(step["handler"], context.session, progress)
```

**Implementation notes:**

1. **DAG resolution:** Use Kahn's algorithm (BFS topological sort). Detect cycles → raise `PipelineDefinitionError`
2. **Skip evaluation:** Strip `$` prefix from variable references, map to context attributes
3. **Retry:** Simple loop with `asyncio.sleep(delay_seconds)` between attempts
4. **Timeout:** `asyncio.wait_for(coro, timeout=step["timeout_seconds"])`
5. **Optional steps:** On failure of an optional step, mark as `failed` but continue to next step (only if the failed step is not in any downstream step's `needs`)
6. **Progress persistence:** After each step, call `context.api.update_instantiation_progress()`

#### B4: Unit tests for PipelineExecutor

**File:** `src/lablet-controller/tests/test_pipeline_executor.py` (new)

**Test categories:**

| Category | Tests |
|----------|-------|
| DAG resolution | Linear chain, diamond, cycle detection, single step |
| Skip evaluation | True → skip, False → execute, missing var → error, complex expressions |
| Retry | Success on retry, max attempts exceeded |
| Timeout | Step completes in time, step exceeds timeout |
| Optional steps | Optional failure doesn't block, required failure blocks |
| Outputs | Dot-path resolution, missing step data → None |
| Context injection | `$SESSION`, `$DEFINITION`, `$WORKER`, `$STEPS` available |
| End-to-end | Full 9-step instantiate pipeline mock, partial failure scenarios |

**Target:** 30–40 unit tests, all pure async (no real services).

---

### Sprint C: LifecyclePhaseHandler + Reconciler Integration (Phase 3)

**Goal:** Wire the executor into the reconciler via managed background tasks.

#### C1: Create `LifecyclePhaseHandler` class

**File:** `src/lablet-controller/application/services/lifecycle_phase_handler.py` (new)

As specified in ADR-034 §2. Key behaviors:

- `start()` → creates `asyncio.Task`
- `_run()` → calls `PipelineExecutor.execute()`, then `_on_complete()` or `_on_error()`
- `stop()` → cancels task gracefully
- `is_running` property → `self._task and not self._task.done()`

#### C2: Add per-session `asyncio.Lock` to reconciler

**File:** `src/lablet-controller/application/hosted_services/lablet_reconciler.py`

**Changes:**

1. Add `_session_locks: dict[str, asyncio.Lock] = {}` alongside `_definition_cache`
2. Add `_get_session_lock(session_id) → asyncio.Lock` method
3. Wrap `reconcile()` body in `async with lock:`
4. Clear locks in `_step_down()`

#### C3: Add `_active_handlers` management to reconciler

**File:** `src/lablet-controller/application/hosted_services/lablet_reconciler.py`

**Changes:**

1. Add `_active_handlers: dict[str, LifecyclePhaseHandler] = {}`
2. Add `_get_pipeline_def(instance, pipeline_name) → dict | None` — looks up `pipelines` from cached definition
3. Add `_build_pipeline_context(instance) → PipelineContext` — constructs context from reconciler state
4. Update `_step_down()` → cancel all active handlers

#### C4: Refactor `_handle_instantiating()` to delegate to handler

**File:** `src/lablet-controller/application/hosted_services/lablet_reconciler.py`

**This is the critical refactor.** Replace the current L497–L577 implementation:

**Before (current):** Monolithic — bootstrap progress, find next step, dispatch, persist.

**After (new):**

```python
async def _handle_instantiating(self, instance) -> ReconciliationResult:
    handler_key = f"{instance.id}:instantiate"

    # Check for existing handler
    if handler_key in self._active_handlers:
        handler = self._active_handlers[handler_key]
        if handler.is_running:
            return ReconciliationResult.success()  # self-driving
        del self._active_handlers[handler_key]
        return ReconciliationResult.success()

    # Get pipeline definition from LabletDefinition
    pipeline_def = self._get_pipeline_def(instance, "instantiate")
    if not pipeline_def:
        await self._api.fail_session(instance.id, reason="No 'instantiate' pipeline defined")
        return ReconciliationResult.failed("No pipeline defined")

    # Start new handler
    context = self._build_pipeline_context(instance)
    handler = LifecyclePhaseHandler(
        session_id=instance.id,
        pipeline_name="instantiate",
        pipeline_def=pipeline_def,
        context=context,
        executor=self._pipeline_executor,
    )
    self._active_handlers[handler_key] = handler
    await handler.start()
    return ReconciliationResult.success()
```

#### C5: Adapt `_step_*` handlers for new dispatch interface

**Current signature:** `async def _step_content_sync(self, instance, progress) → dict`

**New signature:** The step handlers need to work with the `PipelineContext` and return a standardized `StepResult`. Two approaches:

**Option A — Adapter pattern (least disruption):** Keep existing step handlers unchanged. The `PipelineExecutor` wraps the dispatch call to pass `(instance, progress)` extracted from context.

**Option B — Refactor step handlers (cleaner):** Update all 9 step handlers to accept `PipelineContext` instead of `(instance, progress)`. This is more work but aligns with the long-term vision.

**Recommendation:** Start with Option A for the `instantiate` pipeline. Refactor incrementally as other pipelines are added.

#### C6: Update test suite

**Files:**

- Adapt `tests/test_instantiation_pipeline.py` — existing tests for `_handle_instantiating` need updating
- Add `tests/test_lifecycle_phase_handler.py` — handler start/stop/cancel/completion tests
- Add `tests/test_reconciler_concurrency.py` — per-session lock tests, handler deduplication

---

### Sprint D: Additional Pipeline Handlers (Phase 3 cont.)

**Goal:** Implement `_handle_collecting()`, `_handle_grading()`, `_handle_stopping()` — all following the same handler delegation pattern established in Sprint C.

These are lower priority because:

1. The `instantiate` pipeline is the immediate stall fix
2. `collect_evidence` and `compute_grading` step handlers don't exist yet (Phase 5: Grading Integration)
3. `teardown` steps partially exist but aren't structured as a pipeline

#### D1: Implement `_handle_collecting()` with handler delegation

#### D2: Implement `_handle_grading()` with handler delegation

#### D3: Implement `_handle_stopping()` (teardown pipeline) with handler delegation

#### D4: Create stub step handlers for evidence collection and grading

---

### Sprint E: Output Storage & LabRecord Integration (Phase 4)

**Goal:** Store pipeline execution history on the LabRecord aggregate.

#### E1: Add `PipelineRunRecord` to LabRecord aggregate (CPA domain)

#### E2: Create `AppendPipelineRunCommand` (CPA application)

#### E3: Wire `LifecyclePhaseHandler._on_complete()` → CPA command

#### E4: S3 artifact upload for file outputs

---

### Sprint F: Definition Decomposition (Phase 5) — Separate ADR

**Goal:** Extract ContentSyncRecord from LabletDefinition. This warrants its own ADR.

### Sprint G: UX Redesign (Phase 6) — Separate scope

**Goal:** Tabbed definition detail modal, pipeline DAG visualization, SSE for step progress.

---

## 3. Dependency Chain

```
Sprint A (Foundation)
  ├── A1: LabletDefinitionReadModel.pipelines  ← MUST be first
  ├── A2: simpleeval dependency               ← MUST be before B3
  └── A3: ADR-034 errata                      ← housekeeping

Sprint B (PipelineExecutor) — depends on A1, A2
  ├── B1: PipelineContext
  ├── B2: PipelineResult
  ├── B3: PipelineExecutor class              ← core deliverable
  └── B4: Unit tests                          ← validates B1-B3

Sprint C (Integration) — depends on B3
  ├── C1: LifecyclePhaseHandler
  ├── C2: Per-session asyncio.Lock
  ├── C3: _active_handlers management
  ├── C4: _handle_instantiating refactor      ← critical path
  ├── C5: Step handler adapter
  └── C6: Test suite updates

Sprint D (More Pipelines) — depends on C4
Sprint E (Output Storage) — depends on C1
Sprint F (Decomposition) — independent
Sprint G (UX) — depends on E1
```

**Critical path:** A1 → A2 → B3 → C4

---

## 4. Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| Step handler refactoring breaks existing tests | Adapter pattern (Option A) avoids changing step signatures |
| Definition cache doesn't include `pipelines` for old definitions | `pipelines` defaults to `None` — `_handle_instantiating` checks and fails gracefully |
| Per-session lock deadlock | Locks are per-session (no nesting) — deadlock only possible if same session awaits itself (impossible in single-threaded asyncio) |
| PipelineExecutor too tightly coupled to reconciler | Executor receives a `step_dispatcher` callable — fully testable without reconciler |
| simpleeval security | Expressions authored by admins only (seed YAML), not user input; simpleeval blocks `_`-prefixed attrs |

---

## 5. Session Handoff Notes

### Decisions Stored This Session

- **AD-PIPELINE-002**: PipelineExecutor with DAG inner loop (no polling)
- **AD-PIPELINE-003**: LifecyclePhaseHandler as managed asyncio.Task
- **AD-PIPELINE-004**: simpleeval for skip_when evaluation
- **AD-PIPELINE-005**: Per-session asyncio.Lock for concurrency safety

### Key Files Modified This Session

| File | Change |
|------|--------|
| `control-plane-api/domain/entities/lablet_definition.py` | Added `pipelines: dict \| None` |
| `control-plane-api/domain/events/lablet_definition_events.py` | Added `pipelines` to domain event |
| `control-plane-api/application/dtos/lablet_definition_dto.py` | Added `pipelines` to DTO + mapper |
| `control-plane-api/infrastructure/seeding/lablet_definition_seeder.py` | Parse `pipelines` from YAML |
| `tests/integration/test_mongo_lablet_definition_repository.py` | Fixed 17 test calls |
| `docs/architecture/adr/ADR-034-...md` | Created — 726 lines |

### Architectural Insights Discovered

1. **Definition data flow is HTTP, not etcd.** Task 1.5 was misframed. The lablet-controller fetches definitions via `GET /api/internal/lablet-definitions/{id}`, not from etcd keys. Only session data flows through etcd watches.

2. **Definition cache is never invalidated.** The `_definition_cache` on the reconciler persists for the process lifetime. If a definition's pipeline is updated in CPA, the lablet-controller must be restarted (or the cache needs invalidation logic — deferred).

3. **9 step handlers already use dynamic dispatch.** `getattr(self, f"_step_{step_name}")` is the existing pattern. The PipelineExecutor just needs to wrap this in a `step_dispatcher` callable.

4. **Existing pipeline tests cover helpers, not the executor pattern.** The 879-line test file tests `_build_default_progress`, `_next_executable_step`, step handlers — but all assume the current monolithic `_handle_instantiating`. New tests needed for PipelineExecutor.
