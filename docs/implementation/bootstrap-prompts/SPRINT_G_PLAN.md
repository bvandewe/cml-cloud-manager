# Sprint G: Pipeline Observability & Control Endpoints

**Predecessor:** Sprint F (Generic Pipeline Resumability) — completed
**ADR:** ADR-034 (Pipeline Executor Architecture)
**Status:** PLANNED
**Estimated Tests:** ~25 new

---

## 1. Motivation

After Sprints A–F, the pipeline execution engine is **functionally complete**:

- DAG-based step orchestration with topological sort, retry, timeout, skip_when
- Fire-and-check reconciliation across 4 lifecycle phases (instantiate, teardown, collect_evidence, compute_grading)
- Generic `pipeline_progress` persistence via CPA (`UpdatePipelineProgressCommand`)
- SSE broadcast of bulk `pipeline_progress_updated` events
- Frontend pipeline sub-tabs with dynamic labels and step-level progress bars
- Resumability across all 4 handlers via `_get_existing_progress()` (Sprint F)

**What's missing:** The system is **opaque to operators**. There are:

- ❌ No query endpoints for pipeline execution history
- ❌ No admin control (retry, cancel) from the lablet-controller API
- ❌ No `PipelineExecutionRecord` read model for auditing
- ❌ No granular CloudEvents for per-step progress (only bulk SSE)
- ❌ No admin pipeline status column in the frontend session list

This sprint delivers **observability** and **control** over the pipeline layer.

---

## 2. Scope

### G1: Pipeline Execution Read Model (CPA)

**Goal:** Create a `PipelineExecutionRecord` that captures each pipeline run as an auditable entity.

**New files:**

- `control-plane-api/domain/entities/pipeline_execution_record.py` — Dataclass: `session_id`, `pipeline_name`, `status`, `steps: list[dict]`, `started_at`, `completed_at`, `duration_seconds`, `outputs: dict`, `error: str | None`, `attempt: int`
- `control-plane-api/integration/repositories/mongo_pipeline_execution_repository.py` — Motor-backed repository
- `control-plane-api/domain/repositories/pipeline_execution_repository.py` — Abstract interface

**Changes:**

- `UpdatePipelineProgressCommandHandler` — also upsert a `PipelineExecutionRecord` when a pipeline starts or completes (detect via step status transitions)

**MongoDB collection:** `pipeline_executions` with indexes on `(session_id, pipeline_name)` and `(session_id, started_at)`

**Patterns to follow:**

- Match `LabRecord` / `LabRunRecord` entity patterns (see `control-plane-api/domain/entities/`)
- Repository interface in `domain/repositories/`, implementation in `integration/repositories/`
- Register via DI in `main.py::create_app()`

### G2: Pipeline Query Endpoints (CPA)

**Goal:** Expose pipeline execution data via REST API.

**New queries (self-contained per pattern):**

- `application/queries/lablet_session/get_pipeline_progress_query.py`
  - `GetPipelineProgressQuery(session_id: str)` → returns current `pipeline_progress` dict
  - Handler fetches from `LabletSession` aggregate state
- `application/queries/lablet_session/list_pipeline_executions_query.py`
  - `ListPipelineExecutionsQuery(session_id: str, pipeline_name: str | None)` → returns list of `PipelineExecutionRecord`
  - Handler queries `PipelineExecutionRepository`

**Controller endpoints (extend existing or new):**

- `GET /api/lablet-sessions/{id}/pipeline-progress` — current progress (all pipelines)
- `GET /api/lablet-sessions/{id}/pipeline-executions` — execution history
- Both go through `SessionsController` or a new `PipelineController`

**Reference patterns:**

- Existing query: `application/queries/lablet_session/get_lablet_session_query.py`
- Existing internal controller: `api/controllers/internal_sessions_controller.py`
- The query handler returns `OperationResult[T]`; controller uses `self.process(result)`

### G3: Controller Pipeline Endpoints (lablet-controller)

**Goal:** Give operators admin control over running pipelines.

**Extend `AdminController` (`lablet-controller/api/controllers/admin_controller.py`):**

- `POST /admin/sessions/{session_id}/retry-pipeline` — Clears the handler from `_active_handlers`, resets retry count, reconcile loop will restart
- `POST /admin/sessions/{session_id}/cancel-pipeline` — Calls `handler.stop()` on the `LifecyclePhaseHandler`, removes from `_active_handlers`
- `GET /admin/sessions/{session_id}/pipeline-status` — Returns handler state: `{pipeline_name, is_running, attempt, started_at, result_status}`
- `GET /admin/active-handlers` — Lists all entries in `_active_handlers` with status

**Key implementation details:**

- The reconciler's `_active_handlers: dict[str, LifecyclePhaseHandler]` is the single source of truth for in-flight pipelines
- `LifecyclePhaseHandler` already has `is_running`, `result`, `pipeline_attempt`, `stop()` — all needed for these endpoints
- The AdminController already has access to the reconciler via DI (see existing `trigger-reconcile` endpoint)
- Need `require_admin` dependency for auth on all new endpoints

### G4: Frontend Pipeline Progress Panel (CPA UI)

**Goal:** Surface pipeline status and admin controls in the session detail page.

**Changes to existing files:**

- `ui/src/scripts/app/sse/sseAdapter.js` — Already handles `pipeline_progress_updated`; ensure it dispatches to the detail panel component
- Session detail page — Add a "Pipeline" tab or section:
  - Step-by-step progress bars (from `pipeline_progress` dict)
  - Per-pipeline status badge (running/completed/failed)
  - Retry/cancel action buttons (call G3 endpoints via fetch)
- Session list page — Add pipeline status indicator column (small badge showing current pipeline state)

**Data flow:**

1. Session detail page fetches `GET /api/lablet-sessions/{id}/pipeline-progress` on load
2. SSE `pipeline_progress_updated` events update the UI reactively
3. Retry/cancel buttons call lablet-controller `/admin/sessions/{id}/retry-pipeline` or `/cancel-pipeline`

**Reference:**

- Existing SSE event map: `ui/src/scripts/app/sse/sseEventMap.js`
- Existing session detail: `ui/src/scripts/app/pages/sessionDetailPage.js` (if exists)
- Bootstrap 5 progress bars + badges pattern already used in worker monitoring

### G5: Granular Pipeline CloudEvents (CPA → SSE)

**Goal:** Emit per-step CloudEvents for fine-grained SSE reactivity.

**New event types:**

- `pipeline.step.started.v1` — when a step begins execution
- `pipeline.step.completed.v1` — when a step finishes successfully
- `pipeline.step.failed.v1` — when a step fails
- `pipeline.completed.v1` — when all steps in a pipeline finish

**Emission point:** `UpdatePipelineProgressCommandHandler` — detect step status transitions and emit appropriate CloudEvent

**SSE adapter changes:** Add handlers in `sseEventMap.js` for the new event types → update reactive store

---

## 3. Dependencies & Order

```
G1 (Read Model) ──┐
                   ├── G2 (Query Endpoints) ── G4 (Frontend)
G5 (CloudEvents) ─┘                              │
                                                  │
G3 (Admin Endpoints) ─────────────────────────────┘
```

- G1 and G5 can be done in parallel
- G2 depends on G1 (queries need the repository)
- G3 is independent (operates on in-memory `_active_handlers`)
- G4 depends on G2 (query endpoints) and G3 (admin actions)

**Recommended implementation order:** G3 → G1 → G5 → G2 → G4

G3 is the quickest win — it only touches the lablet-controller (no CPA changes) and gives operators immediate control. G1 introduces the new read model. G5 can be wired while G1 is fresh. G2 exposes G1 data. G4 ties everything together in the UI.

---

## 4. File Inventory

### Files to Create

| File | Service | Purpose |
|------|---------|---------|
| `domain/entities/pipeline_execution_record.py` | CPA | Read model for pipeline runs |
| `domain/repositories/pipeline_execution_repository.py` | CPA | Abstract repository interface |
| `integration/repositories/mongo_pipeline_execution_repository.py` | CPA | MongoDB implementation |
| `application/queries/lablet_session/get_pipeline_progress_query.py` | CPA | Query: current pipeline progress |
| `application/queries/lablet_session/list_pipeline_executions_query.py` | CPA | Query: execution history |
| `tests/test_pipeline_execution_queries.py` | CPA | Tests for G1+G2 |
| `tests/test_pipeline_admin_endpoints.py` | LC | Tests for G3 |

### Files to Modify

| File | Service | Changes |
|------|---------|---------|
| `application/commands/lablet_session/update_pipeline_progress_command.py` | CPA | Upsert PipelineExecutionRecord + emit CloudEvents |
| `main.py` | CPA | Register new repository in DI |
| `api/controllers/sessions_controller.py` or new controller | CPA | Add G2 query endpoints |
| `api/controllers/admin_controller.py` | LC | Add G3 pipeline control endpoints |
| `ui/src/scripts/app/sse/sseEventMap.js` | CPA UI | Add granular pipeline event handlers |
| Session detail page JS | CPA UI | Pipeline progress panel |

### Reference Files (Read Only)

| File | Purpose |
|------|---------|
| `lablet-controller/application/hosted_services/lablet_reconciler.py` | `_active_handlers` dict, `LifecyclePhaseHandler` usage |
| `lablet-controller/application/services/lifecycle_phase_handler.py` | `is_running`, `result`, `stop()`, `pipeline_attempt` |
| `control-plane-api/application/commands/lablet_session/update_pipeline_progress_command.py` | Current handler — emission point for G5 |
| `core/lcm_core/domain/entities/read_models/lablet_session_read_model.py` | `pipeline_progress` and `desired_status` fields |
| `control-plane-api/domain/entities/lab_record.py` | Pattern for entity + repository |

---

## 5. Test Plan

### G1+G2 Tests (CPA — `test_pipeline_execution_queries.py`)

- `TestPipelineExecutionRecord` — constructor, from_dict, edge cases (~4 tests)
- `TestGetPipelineProgressQuery` — success, not found, empty progress (~3 tests)
- `TestListPipelineExecutionsQuery` — success, filtered by pipeline_name, empty result (~3 tests)
- `TestUpdatePipelineProgressCreatesRecord` — verify upsert on start/complete (~3 tests)
- **Subtotal:** ~13 tests

### G3 Tests (LC — `test_pipeline_admin_endpoints.py`)

- `TestRetryPipeline` — clears handler, resets retry count, returns 200 (~3 tests)
- `TestCancelPipeline` — calls handler.stop(), removes from active, returns 200 (~3 tests)
- `TestPipelineStatus` — returns handler state, 404 for unknown session (~3 tests)
- `TestActiveHandlers` — lists all, empty case (~2 tests)
- **Subtotal:** ~11 tests

### G5 Tests

- `TestGranularCloudEvents` — verify event emission on step transitions (~4 tests)
- **Subtotal:** ~4 tests

**Total: ~28 new tests**

---

## 6. Acceptance Criteria

- [ ] `GET /api/lablet-sessions/{id}/pipeline-progress` returns current pipeline_progress dict
- [ ] `GET /api/lablet-sessions/{id}/pipeline-executions` returns execution history
- [ ] `POST /admin/sessions/{id}/retry-pipeline` clears handler and allows reconcile loop to restart
- [ ] `POST /admin/sessions/{id}/cancel-pipeline` stops running handler
- [ ] `GET /admin/sessions/{id}/pipeline-status` returns handler state
- [ ] `GET /admin/active-handlers` lists all in-flight handlers
- [ ] Pipeline step CloudEvents emitted and received via SSE
- [ ] All existing tests pass (403 LC, 954+ CPA)
- [ ] ≥25 new tests added

---

## 7. Current Test Baselines

| Service | Passed | Skipped | Pre-existing Failures |
|---------|--------|---------|----------------------|
| lablet-controller | 403 | 27 | 0 |
| control-plane-api | 954 | 0 | 2 (pre-existing) |
| lcm-core (frontend) | 124 | 0 | 2 (pre-existing) |

---

## 8. What to Defer

- **PipelineRunRecord on LabRecord** (ADR-034 §5 Output Storage) — wait until G1 patterns stabilize
- **Definition Decomposition** (ADR-034 Sprint G original) — separate ADR, XL effort
- **WorkflowExecutor** (Root TODO) — far-future
- **Admin Dashboard UX** (Sprint E §E5) — defer until G4 baseline exists
- **Session Recovery UX** (Sprint E §E6) — defer until admin controls proven
