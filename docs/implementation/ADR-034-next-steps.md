# ADR-034 Implementation — Next Steps

| Attribute | Value |
|-----------|-------|
| **Status** | Active |
| **Created** | 2026-03-02 |
| **Parent ADR** | [ADR-034](../architecture/adr/ADR-034-pipeline-executor-lifecycle-handlers.md) |
| **Last Updated** | 2026-03-04 |

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
| `LabletDefinitionReadModel.pipelines` field | `lcm_core/domain/entities/read_models/` | ✅ Sprint A |
| `simpleeval` dependency | `lablet-controller/pyproject.toml` | ✅ Sprint A |
| `PipelineExecutor` class | `lablet-controller/application/` | ✅ Sprint B |
| `PipelineContext` dataclass | `lablet-controller/application/` | ✅ Sprint B |
| `PipelineResult` dataclass | `lablet-controller/application/` | ✅ Sprint B |
| `LifecyclePhaseHandler` class | `lablet-controller/application/` | ✅ Sprint C |
| Per-session `asyncio.Lock` on reconciler | `lablet_reconciler.py` | ✅ Sprint C |
| Internal `terminate_session` endpoint | CPA + lcm_core client | ✅ Sprint C |
| Pipeline resumability (executor) | `pipeline_executor.py` | ✅ Sprint C |
| Teardown step handlers | `lablet_reconciler.py` | ❌ Sprint D |
| Pipeline SSE events + projectors | CPA | ❌ Sprint E |
| Pipeline progress UI | CPA frontend | ❌ Sprint E |
| `PipelineRunRecord` on `LabRecord` | `control-plane-api/domain/entities/` | ❌ Sprint E |

### What DOES Exist (Reusable)

| Component | Location | Reusability |
|-----------|----------|-------------|
| 9 `_step_*` handler methods | `lablet_reconciler.py` L864–L1271 | ✅ Keep — executor dispatches to these |
| `_build_default_progress()` | ~~`lablet_reconciler.py`~~ | ✅ REMOVED (Sprint C, AD-PIPELINE-009) |
| `_next_executable_step()` | ~~`lablet_reconciler.py`~~ | ✅ REMOVED (Sprint C, AD-PIPELINE-009) |
| `_is_pipeline_complete()` | ~~`lablet_reconciler.py`~~ | ✅ REMOVED (Sprint C, AD-PIPELINE-009) |
| `_get_step_result_data()` | `lablet_reconciler.py` | ✅ Kept — simplified for dict-of-dicts format |
| `_handle_instantiating()` | `lablet_reconciler.py` L540–L640 | ✅ REWRITTEN (Sprint C — fire-and-check pattern) |
| `_definition_cache` | `lablet_reconciler.py` | ✅ Keep — now includes pipelines |
| `test_instantiation_pipeline.py` | `tests/` (880 lines, 41 tests) | ✅ REWRITTEN (Sprint C — dict-of-dicts progress) |
| `PipelineExecutor` | `application/services/pipeline_executor.py` (577 lines) | ✅ Sprint B + graphlib refactor |
| `LifecyclePhaseHandler` | `application/services/lifecycle_phase_handler.py` (246 lines) | ✅ Sprint C |
| `PipelineResult` | `application/models/pipeline_result.py` (38 lines) | ✅ Sprint B + max_retries |
| Pipeline helpers | `lablet_reconciler.py` L770–L860 | ✅ Sprint C — _get_pipeline_def,_build_pipeline_context, _build_step_dispatcher |

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
**No backward compatibility** — all definitions MUST have pipelines (AD-PIPELINE-009).
**Seed files are mandatory deliverables.**

**Full prompt:** See `docs/implementation/ADR-034-sprint-c-prompt.md`

#### C0: Fix PipelineExecutor — _persist_progress + resumability

- Fix `_persist_progress()` to call CPA with per-step params (not bulk dict)
- Add pipeline resumability: `execute()` accepts `existing_progress`, skips completed steps
- Add `max_retries: int` to PipelineResult (from pipeline_def)

#### C1: Create `LifecyclePhaseHandler` class

- Managed `asyncio.Task` wrapper — `start()`, `stop()`, `is_running`, `result`
- Does NOT auto-terminate on failure — stores result for reconciler to inspect
- Reconciler decides: retry or terminate based on max_retries

#### C2: Add per-session `asyncio.Lock` to reconciler

- `_session_locks: dict[str, asyncio.Lock]` with lazy init
- `reconcile()` → `_reconcile_inner()` wrapped in lock

#### C3: Add `_active_handlers` management to reconciler

- `_active_handlers: dict[str, LifecyclePhaseHandler]`
- `_pipeline_retry_counts: dict[str, int]` — tracks restart count
- `_build_step_dispatcher()` — adapter wrapping `_step_*` methods
- `_step_down()` cancels all handlers, clears locks + retry counts

#### C4: Refactor `_handle_instantiating()` — pipeline delegation only

- No legacy fallback — definitions without pipelines → terminate session
- Completed handler → check result → retry or terminate based on max_retries
- Resume from existing progress (executor resumability)
- REMOVE legacy helpers: `_build_default_progress`, `_next_executable_step`, etc.

#### C5: Add internal terminate endpoint + CPA client method

- New internal endpoint: `POST /api/internal/lablet-sessions/{id}/terminate`
- New CPA client method: `terminate_session(session_id, terminated_by, reason)`
- Reuses existing `TerminateLabletSessionCommand` (port + capacity release)

#### C6: Update seed files with max_retries and validated handler names

- Add `max_retries` and `retry_backoff` at pipeline level
- Validate handler names match existing `_step_*` methods
- Mark future handlers (teardown, evidence, grading) as TBD
- **Mandatory deliverables — seed files must load correctly**

#### C7: Tests (~50–65 new tests)

- Rewrite `test_instantiation_pipeline.py` (no legacy path)
- New `test_lifecycle_phase_handler.py` (15–20 tests)
- New `test_reconciler_concurrency.py` (8–12 tests)
- Update `test_pipeline_executor.py` (persist + resumability tests)
- New CPA tests for internal terminate endpoint

---

### Sprint D: Additional Pipeline Handlers + Teardown (Phase 3 cont.)

**Goal:** Implement pipeline delegation for `_handle_stopping()`, `_handle_collecting()`,
`_handle_grading()` and decompose the inline teardown logic into step handlers.

#### D1: Decompose `_handle_stopping()` into step handlers

- `_step_stop_lab` — Stop the CML lab
- `_step_wipe_lab` — Wipe lab state for reuse
- `_step_deregister_lds` — Archive LDS session
- `_step_archive` — Transition session to ARCHIVED

#### D2: Wire `_handle_stopping()` to LifecyclePhaseHandler + teardown pipeline

#### D3: Create stub step handlers for evidence collection

- `_step_capture_configs`, `_step_capture_screenshots`, `_step_export_pcaps`,
  `_step_package_evidence`

#### D4: Create stub step handlers for grading

- `_step_load_rubric`, `_step_evaluate`, `_step_record_score`

#### D5: Wire `_handle_collecting()` and `_handle_grading()` to pipeline delegation

#### D6: Tests for all new step handlers and delegation paths

#### D7: Remove TBD markers from seed files — all handlers now exist

---

### Sprint E: UX, SSE Events, Queries & Frontend (Phase 4)

**Goal:** Improve user experience with real-time pipeline progress, extended queries,
and frontend enhancements.

#### E1: Pipeline Progress SSE Events

- New CloudEvent types: `pipeline.step.completed.v1`, `pipeline.step.failed.v1`,
  `pipeline.started.v1`, `pipeline.completed.v1`, `pipeline.retry.v1`
- Wire PipelineExecutor to emit events via context.api or event bus
- SSE projector broadcasts to subscribed UI clients

#### E2: Pipeline Progress Projectors (CPA Read Side)

- `PipelineExecutionProjector` — listens to pipeline CloudEvents
- `PipelineExecutionRecord` read model (session_id, pipeline_name, status, steps[],
  started_at, completed_at, duration_seconds, retry_count, outputs, error)
- MongoDB collection `pipeline_executions` with indexes on session_id, status, started_at

#### E3: Extended Queries

- `GET /api/pipeline-executions?session_id=...` — executions for a session
- `GET /api/pipeline-executions?pipeline_name=...&status=...` — filtered by name/status
- `GET /api/pipeline-executions?from=...&to=...` — datetime range
- `GET /api/pipeline-executions/{id}/steps` — step-level detail
- `GET /api/pipeline-executions/stats` — aggregated stats (avg duration, failure rate)
- `GET /api/lablet-sessions/{id}/pipeline-history` — all pipeline runs for a session

#### E4: Frontend Pipeline Progress UI

- Session detail: pipeline progress panel with real-time SSE updates
- Session list: pipeline status indicator column
- Retry/terminate buttons for failed pipelines
- Pipeline timeline visualization with timing bars
- Toast notifications for pipeline completed/failed

#### E5: Admin Dashboard Enhancements

- Pipeline health overview: success/failure rates, avg duration trends
- Active pipelines panel: currently running handlers
- Failed pipelines queue: sessions awaiting retry/intervention
- Bulk retry/terminate actions for admin users

#### E6: Session Recovery UX

- "Retry Pipeline" action on failed sessions
- "View Pipeline Logs" — step-by-step execution log
- "Manual Override" — skip a failed step and continue (admin only)

---

### Sprint F: Output Storage & LabRecord Integration (Phase 5)

**Goal:** Store pipeline execution history on the LabRecord aggregate.

#### F1: Add `PipelineRunRecord` to LabRecord aggregate (CPA domain)

#### F2: Create `AppendPipelineRunCommand` (CPA application)

#### F3: Wire `LifecyclePhaseHandler._on_complete()` → CPA command

#### F4: S3 artifact upload for file outputs

---

### Sprint G: Definition Decomposition (Phase 6) — Separate ADR

**Goal:** Extract ContentSyncRecord from LabletDefinition. This warrants its own ADR.

---

## 3. Dependency Chain

```
Sprint A (Foundation) ✅ DONE
  ├── A1: LabletDefinitionReadModel.pipelines  ✅
  └── A2: simpleeval dependency                ✅

Sprint B (PipelineExecutor) ✅ DONE — depends on A1, A2
  ├── B1: PipelineContext                      ✅
  ├── B2: PipelineResult                       ✅
  ├── B3: PipelineExecutor class               ✅ (48 tests)
  └── B4: Unit tests                           ✅

Sprint C (Integration) ✅ DONE — 126 tests, 8 tasks complete
  ├── C0: Fix _persist_progress + resumability     ✅
  ├── C1: LifecyclePhaseHandler (246 lines)         ✅
  ├── C2: Per-session asyncio.Lock                  ✅
  ├── C3: _active_handlers management               ✅
  ├── C4: _handle_instantiating refactor            ✅ (fire-and-check pattern)
  ├── C5: Internal terminate endpoint (CPA)         ✅
  ├── C6: Seed files + max_retries                  ✅
  └── C7: Test suite (126 tests across 4 files)     ✅
  └── Bonus: graphlib refactor (AD-PIPELINE-010)    ✅

Sprint D (Teardown + More Pipelines) 🎯 CURRENT — depends on C4
  ├── D1: Decompose _handle_stopping into step handlers
  ├── D2: Wire _handle_stopping to LifecyclePhaseHandler
  ├── D3: Stub step handlers for evidence collection
  ├── D4: Stub step handlers for grading
  ├── D5: Wire _handle_collecting + _handle_grading
  ├── D6: Tests for all new handlers + delegation
  └── D7: Validate seed files load with all handlers

Sprint E (UX & Observability) — depends on C4
  ├── SSE events for pipeline progress
  ├── Pipeline execution projectors + queries
  └── Frontend pipeline progress UI

Sprint F (Output Storage) — depends on D
Sprint G (Definition Decomposition) — independent
```

**Critical path:** A1 → A2 → B3 → C0 → C4 → C5

---

## 4. Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| Step handler refactoring breaks existing tests | Adapter pattern wraps existing `_step_*` signatures — no signature changes needed |
| Definition without pipelines at runtime | No backward compat (AD-PIPELINE-009) — terminate with clear error. Seed files must be updated. |
| Failed pipeline stalls session | Reconciler retries with backoff up to max_retries, then terminates via internal endpoint (AD-PIPELINE-007, AD-PIPELINE-008) |
| Per-session lock deadlock | Locks are per-session (no nesting) — deadlock only possible if same session awaits itself (impossible in single-threaded asyncio) |
| PipelineExecutor too tightly coupled to reconciler | Executor receives a `step_dispatcher` callable — fully testable without reconciler |
| simpleeval security | Expressions authored by admins only (seed YAML), not user input; simpleeval blocks `_`-prefixed attrs |
| Definition cache never invalidated | `_definition_cache` persists for process lifetime — requires restart on pipeline changes (cache invalidation deferred) |

---

## 5. Session Handoff Notes

### Decisions Stored Across Sessions

- **AD-PIPELINE-002**: PipelineExecutor with DAG inner loop (no polling)
- **AD-PIPELINE-003**: LifecyclePhaseHandler as managed asyncio.Task
- **AD-PIPELINE-004**: simpleeval for skip_when evaluation
- **AD-PIPELINE-005**: Per-session asyncio.Lock for concurrency safety
- **AD-PIPELINE-006**: Strip `$` prefix from skip_when expressions (simpleeval limitation)
- **AD-PIPELINE-007**: No auto-teardown on failure — reconciler retries with resumability
- **AD-PIPELINE-008**: Internal terminate_session endpoint for system-initiated termination
- **AD-PIPELINE-009**: No backward compat — all definitions must have pipelines, seed files mandatory
- **AD-PIPELINE-010**: Replace manual Kahn's algorithm with `graphlib.TopologicalSorter` (stdlib, CPython 3.9+)

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
