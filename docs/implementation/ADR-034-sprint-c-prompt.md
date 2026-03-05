# ADR-034 Sprint C Implementation — Follow-Up Session Prompt

> **Purpose:** Copy-paste the prompt below to bootstrap a fresh AI agent session for implementing ADR-034 Phase 3 (LifecyclePhaseHandler + Reconciler Integration).
>
> **Prerequisites completed (Sprint A + Sprint B):**
>
> - `pipelines: dict | None` field added to `LabletDefinitionReadModel` + `from_dict()`
> - `simpleeval ^1.0` dependency added to lablet-controller (1.0.3 installed)
> - `PipelineContext` dataclass at `application/models/pipeline_context.py`
> - `PipelineResult` dataclass at `application/models/pipeline_result.py`
> - `PipelineExecutor` class at `application/services/pipeline_executor.py` (DAG sort, skip_when, retry, timeout, output resolution, progress persistence)
> - 48 unit tests at `tests/test_pipeline_executor.py` — all passing
> - 259 total tests passing (48 new + 211 existing), lint clean
>
> **Key decisions from Sprint A/B:**
>
> - AD-PIPELINE-006: `$` prefix must be stripped from skip_when expressions before simpleeval evaluation
> - AD-PIPELINE-007: No auto-teardown on pipeline failure — reconciler retries with resumability
> - AD-PIPELINE-008: Internal `terminate_session` endpoint for system-initiated termination
> - AD-PIPELINE-009: No backward compat — all definitions must have pipelines, seed files mandatory

---

## The Prompt

```
I need to implement ADR-034 Sprint C for the Lablet Cloud Manager project.
Read the implementation guide at docs/implementation/ADR-034-next-steps.md (lines 217–318)
and the full ADR at docs/architecture/adr/ADR-034-pipeline-executor-lifecycle-handlers.md
(§2 LifecyclePhaseHandler, §3 Concurrency Model) before implementing.

### Context

Sprint C wires the PipelineExecutor (created in Sprint B) into the LabletReconciler via
managed background tasks. The goal is to replace the current one-step-per-reconcile pattern
in `_handle_instantiating()` with a self-driving LifecyclePhaseHandler that runs the full
pipeline DAG as a single asyncio.Task.

**Architecture summary (ADR-034 §2–§3):**
- LifecyclePhaseHandler: Managed asyncio.Task wrapper that calls PipelineExecutor.execute()
- Per-session asyncio.Lock: Prevents duplicate handlers from watch+polling race conditions
- The reconciler's _handle_instantiating() becomes a "fire-and-check" pattern:
  check if handler exists → if running return success → if done clean up → else start new one

### Key Architectural Decisions (AD-PIPELINE-007/008/009)

**AD-PIPELINE-007 — No auto-teardown on pipeline failure; reconciler retries:**
Pipeline failures do NOT auto-trigger teardown. Failed sessions stay in their current status
(e.g. INSTANTIATING). The reconciler's poll loop with exponential backoff provides
pipeline-level retry. The PipelineExecutor supports **resumability** — it skips
already-completed steps and re-executes from the failed step. After `max_retries`
(configurable per pipeline in seed YAML) are exhausted, the session is terminated.

**Failure recovery model:**
| Failure Type    | Example                          | Recovery |
|-----------------|----------------------------------|----------|
| Transient       | CML API timeout, network blip    | Step-level retry (already in executor) |
| Environmental   | Worker rebooting, license expired | Pipeline-level retry via reconciler backoff |
| Definitional    | No topology YAML, bad config     | User fixes definition, reconciler retries |
| Resource        | No ports, worker full            | Reconciler waits, retries on next cycle |

**AD-PIPELINE-008 — Internal terminate_session endpoint:**
The lablet-controller currently has NO way to terminate a session via CPA. The public
`terminate_session` endpoint requires user auth. The internal `transition_session` endpoint
explicitly rejects TERMINATED as a target. Sprint C must add:
1. A new internal endpoint: `POST /api/internal/lablet-sessions/{id}/terminate`
2. A new CPA client method: `terminate_session(session_id, terminated_by, reason)`
This reuses the existing `TerminateLabletSessionCommand` which handles port release and
capacity release. Used only for unrecoverable situations (max retries exhausted,
timeslot expiry, admin force-kill).

**AD-PIPELINE-009 — No backward compatibility:**
All LabletDefinitions MUST have `pipelines` defined. No legacy fallback path.
The existing `_build_default_progress`, `_next_executable_step`, `_is_pipeline_complete`
static helpers are REMOVED. Seed files are mandatory deliverables with validated handler
names and pipeline-level `max_retries` / `retry_backoff` fields.

### Critical Integration Gap — _persist_progress API Mismatch (MUST FIX)

The PipelineExecutor._persist_progress() currently calls:
  await context.api.update_instantiation_progress(session_id=..., progress=full_dict)

But the real ControlPlaneApiClient.update_instantiation_progress() expects per-step params:
  async def update_instantiation_progress(self, session_id, step_name, step_status, result_data, error)

Sprint B tests use AsyncMock so this mismatch was not caught. Sprint C must fix
`_persist_progress()` to pass individual step params.

### Existing Code References

**Files to modify:**
- `src/lablet-controller/application/hosted_services/lablet_reconciler.py` (2009 lines)
  - __init__: Lines 97–195 — constructor with all injected services
  - _step_down: Lines 230–251 — leadership teardown
  - reconcile: Lines 372–445 — main dispatch by session status
  - _handle_instantiating: Lines 497–575 — CURRENT implementation (to be REPLACED)
  - _build_default_progress: Lines 702–732 — static helper (to be REMOVED)
  - _next_executable_step: Lines 731–749 — static helper (to be REMOVED)
  - _is_pipeline_complete: Lines 750–753 — static helper (to be REMOVED)
  - _get_step_result_data: Lines 756–760 — static helper (to be REMOVED)
  - _step_content_sync: Line 767 — first step handler
    (signature: `async def _step_content_sync(self, instance, progress)`)
  - Other _step_* handlers: Lines 804–1144 (9 handlers total)
  - _get_definition: Lines 1738–1759 — cached definition lookup

- `src/lablet-controller/application/services/pipeline_executor.py` (528 lines)
  - StepDispatcher type alias: Line 37
  - execute() method: Lines 87–230
  - _persist_progress: Lines 491–507 — MUST FIX API call signature

- `src/core/lcm_core/integration/clients/control_plane_client.py` (1585 lines)
  - update_instantiation_progress: Lines 354–394 — per-step signature
  - transition_session: Lines 248–270 — rejects TERMINATED
  - mark_session_ready: Lines 302–328 — INSTANTIATING → READY
  - NO terminate_session method exists — MUST ADD

- `src/control-plane-api/api/controllers/internal_sessions_controller.py`
  - transition_session: rejects TERMINATED ("Use .../terminate instead")
  - NO internal terminate endpoint — MUST ADD

- `src/control-plane-api/data/seeds/lablet_definitions/` — two seed YAML files to update

**Files to create:**
- `src/lablet-controller/application/services/lifecycle_phase_handler.py` (NEW)
- `src/lablet-controller/tests/test_lifecycle_phase_handler.py` (NEW)
- `src/lablet-controller/tests/test_reconciler_concurrency.py` (NEW)

**Files to adapt:**
- `src/lablet-controller/tests/test_instantiation_pipeline.py` (879 lines)
  - Existing _handle_instantiating tests MUST be rewritten (no legacy path)
  - make_reconciler() fixture needs _active_handlers, _session_locks, _pipeline_executor
  - make_instance() / make_definition() fixtures — keep as-is

**Reference files (read-only):**
- `src/lablet-controller/application/models/pipeline_context.py` — PipelineContext dataclass
- `src/lablet-controller/application/models/pipeline_result.py` — PipelineResult dataclass
- `src/lablet-controller/tests/test_pipeline_executor.py` — 48 tests (executor patterns)
- `src/core/lcm_core/infrastructure/hosted_services/reconciliation_hosted_service.py`
  — ReconciliationResult API (success/requeue/failed/skip class methods)
- `src/control-plane-api/application/commands/lablet_session/terminate_lablet_session_command.py`
  — TerminateLabletSessionCommandHandler (port release, capacity release, domain events)
- `src/core/lcm_core/domain/enums/lablet_session_status.py` — LabletSessionStatus enum
  (12 values: PENDING→SCHEDULED→INSTANTIATING→READY→RUNNING→COLLECTING→GRADING→
  STOPPING→STOPPED→ARCHIVED, plus TERMINATED and EXPIRED)

### Sprint C Tasks

#### C0: Fix PipelineExecutor — _persist_progress + resumability

**File:** `src/lablet-controller/application/services/pipeline_executor.py`

**Part A — Fix _persist_progress API mismatch:**

Update `_persist_progress()` signature to pass per-step params:

    async def _persist_progress(
        self, context, step_name, step_status, result_data=None, error=None
    ) -> None:
        await context.api.update_instantiation_progress(
            session_id=context.session.id,
            step_name=step_name,
            step_status=step_status,
            result_data=result_data,
            error=error,
        )

Update ALL call sites in `execute()` to pass step_name, step_status, result_data, error
instead of the full progress dict.

**Part B — Add pipeline resumability (AD-PIPELINE-007):**

The `execute()` method must accept optional `existing_progress` and skip completed steps:

    async def execute(
        self,
        pipeline_def: dict[str, Any],
        context: PipelineContext,
        step_dispatcher: StepDispatcher,
        existing_progress: dict[str, Any] | None = None,  # NEW
    ) -> PipelineResult:

When `existing_progress` is provided:
- Steps with status "completed" → skip, but restore their result_data into
  `context.steps_data[step_name]` (needed by downstream skip_when / output resolution)
- Steps with status "skipped" → skip
- Steps with status "failed" or "pending" or "in_progress" → re-execute

This enables the reconciler to resume a pipeline from where it failed.

**Part C — Read pipeline-level max_retries:**

The pipeline_def may contain `max_retries` (int, default 0 = unlimited) and
`retry_backoff` (int seconds, default 30). The executor itself does NOT enforce
pipeline-level retries — that's the reconciler's responsibility. But the executor
should include `pipeline_def.get("max_retries", 0)` in the returned PipelineResult
so the reconciler can check it.

Add to PipelineResult:
    max_retries: int = 0  # From pipeline def, 0 = unlimited

#### C1: Create LifecyclePhaseHandler class

**File:** `src/lablet-controller/application/services/lifecycle_phase_handler.py` (NEW)

As specified in ADR-034 §2. Key behaviors:
- `__init__(session_id, pipeline_name, pipeline_def, context, executor,
   step_dispatcher, on_complete=None, on_error=None)` — stores params, task=None
- `start()` → creates `asyncio.create_task(self._run(),
   name=f"pipeline:{pipeline_name}:{session_id}")`
- `_run()` → calls `self._executor.execute(pipeline_def, context, step_dispatcher)`,
   then `_on_complete(result)` or `_on_error(exc)`
- `stop()` → cancels task gracefully (cancel + await + catch CancelledError)
- `is_running` property → `self._task is not None and not self._task.done()`
- `result` property → returns PipelineResult if task completed, else None
- `pipeline_attempt` property → tracks how many times this handler has been started

The executor.execute() takes 3 args: (pipeline_def, context, step_dispatcher).
The step_dispatcher must be passed into the handler since the executor needs it.

**_on_complete callback (pipeline finished — success or failure):**
- result.status == "completed":
  → call context.api.mark_session_ready(session_id) for "instantiate" pipeline
  → for other pipelines, call appropriate transition
- result.status == "failed":
  → Do NOT auto-terminate. Just log and let the handler finish.
  → The reconciler will detect handler.is_running == False on next cycle,
    check the result, increment retry counter, and either restart or terminate.
- result.status == "partial" (some optional steps failed):
  → Treat as "completed" — proceed with transition.

**_on_error callback (unhandled exception in executor):**
- Log the exception at ERROR level.
- Do NOT auto-terminate. Let the reconciler handle it on next cycle.

This design keeps the handler simple — it runs the pipeline, stores the result,
and lets the reconciler make all lifecycle decisions.

#### C2: Add per-session asyncio.Lock to reconciler

**File:** `src/lablet-controller/application/hosted_services/lablet_reconciler.py`

Changes:
1. Add `self._session_locks: dict[str, asyncio.Lock] = {}` in __init__
2. Add `_get_session_lock(self, session_id: str) -> asyncio.Lock` method (lazy init)
3. Rename current `reconcile()` body to `_reconcile_inner()` (lines 372–445)
4. New `reconcile()` wraps `_reconcile_inner()` in
   `async with self._get_session_lock(instance.id):`
5. Clear `_session_locks` in `_step_down()`

The `reconcile()` method is called by the base class WatchTriggeredHostedService —
keep the signature `async def reconcile(self, instance) -> ReconciliationResult`.

#### C3: Add _active_handlers management to reconciler

**File:** `src/lablet-controller/application/hosted_services/lablet_reconciler.py`

Changes:
1. Add imports: `LifecyclePhaseHandler`, `PipelineExecutor`
2. Add `self._active_handlers: dict[str, LifecyclePhaseHandler] = {}` in __init__
3. Add `self._pipeline_executor = PipelineExecutor()` in __init__
4. Add `self._pipeline_retry_counts: dict[str, int] = {}` in __init__
   — tracks how many times each handler_key has been restarted

5. Add `_get_pipeline_def(self, instance, pipeline_name) -> dict | None`:
   - Get definition via `self._get_definition(instance.definition_id)`
   - Return `definition.pipelines.get(pipeline_name)` if pipelines exist
   - Return None if no definition or no pipelines

6. Add `_build_pipeline_context(self, instance) -> PipelineContext`:
   - Build PipelineContext from instance + reconciler state
   - Pass: instance (session), cached definition, worker_ip, cml_username, cml_password,
     self._api, self._cml_labs, self._lds, steps_data={}

7. Add `_build_step_dispatcher(self) -> StepDispatcher`:
   - Return closure that dispatches to self._step_* methods:
     async def dispatch(handler_name, session, progress):
         method = getattr(self, f"_step_{handler_name}", None)
         if not method:
             raise ValueError(f"Unknown step handler: {handler_name}")
         result = await method(session, progress)
         return result.get("result_data", {})
   - The existing _step_* methods return {"step": name, "status": ..., "result_data": ...}
     but PipelineExecutor expects the dispatcher to return just the result_data dict

8. Update `_step_down()`: Cancel all active handlers before existing teardown:
     for key, handler in list(self._active_handlers.items()):
         await handler.stop()
     self._active_handlers.clear()
     self._session_locks.clear()
     self._pipeline_retry_counts.clear()

#### C4: Refactor _handle_instantiating() — pipeline delegation only

**File:** `src/lablet-controller/application/hosted_services/lablet_reconciler.py`

Replace lines 497–575 with the new delegation pattern. NO backward compatibility —
all definitions MUST have pipelines (AD-PIPELINE-009).

The NEW _handle_instantiating():

1. Compute handler_key = f"{instance.id}:instantiate"

2. If handler_key in _active_handlers:
   a. handler = self._active_handlers[handler_key]
   b. If handler.is_running → return ReconciliationResult.success() (self-driving)
   c. If handler finished:
      - result = handler.result
      - del self._active_handlers[handler_key]
      - If result.status == "completed" or "partial" → return success (transition
        already happened in _on_complete)
      - If result.status == "failed":
        · retry_count = self._pipeline_retry_counts.get(handler_key, 0) + 1
        · max_retries = result.max_retries (from pipeline_def, 0 = unlimited)
        · If max_retries > 0 and retry_count >= max_retries:
          → call self._api.terminate_session(instance.id, "lablet-controller",
            f"Pipeline failed after {retry_count} attempts: {result.error}")
          → return ReconciliationResult.failed("Max pipeline retries exhausted")
        · Else:
          → self._pipeline_retry_counts[handler_key] = retry_count
          → Fall through to step 3 (restart pipeline with resumability)

3. Get pipeline_def = self._get_pipeline_def(instance, "instantiate")

4. If no pipeline_def:
   → call self._api.terminate_session(instance.id, "lablet-controller",
     "No 'instantiate' pipeline defined in LabletDefinition")
   → return ReconciliationResult.failed("No pipeline defined")

5. Start new handler:
   - context = self._build_pipeline_context(instance)
   - Restore existing progress from instance.instantiation_progress (resumability):
     · If instance.instantiation_progress has steps, pass it to executor
     · This allows completed steps to be skipped on retry
   - step_dispatcher = self._build_step_dispatcher()
   - handler = LifecyclePhaseHandler(
       session_id=instance.id,
       pipeline_name="instantiate",
       pipeline_def=pipeline_def,
       context=context,
       executor=self._pipeline_executor,
       step_dispatcher=step_dispatcher,
     )
   - self._active_handlers[handler_key] = handler
   - await handler.start()
   - return ReconciliationResult.success()

Also REMOVE these legacy static helpers (no longer needed):
- _build_default_progress
- _next_executable_step
- _is_pipeline_complete
- _get_step_result_data

#### C5: Add internal terminate endpoint + CPA client method

**File:** `src/control-plane-api/api/controllers/internal_sessions_controller.py`

Add new endpoint to the internal sessions controller:

    @post(
        "/{session_id}/terminate",
        summary="Terminate Session (Internal)",
        tags=["Internal - Sessions"],
        status_code=200,
    )
    async def terminate_session_internal(
        self,
        session_id: session_id_annotation,
        request: TerminateSessionInternalRequest,
        api_key: str = Depends(verify_internal_api_key),
    ) -> dict[str, Any]:
        command = TerminateLabletSessionCommand(
            session_id=session_id,
            terminated_by=request.terminated_by,
            reason=request.reason,
        )
        result = await self.mediator.execute_async(command)
        return self.process(result)

Add request model:

    @dataclass
    class TerminateSessionInternalRequest:
        terminated_by: str = "lablet-controller"
        reason: str | None = None

This reuses the existing TerminateLabletSessionCommandHandler which already handles
port release, capacity release, and domain events.

**File:** `src/core/lcm_core/integration/clients/control_plane_client.py`

Add new client method:

    async def terminate_session(
        self,
        session_id: str,
        terminated_by: str = "lablet-controller",
        reason: str | None = None,
    ) -> dict[str, Any]:
        result = await self._request(
            "POST",
            f"/api/internal/lablet-sessions/{session_id}/terminate",
            json={"terminated_by": terminated_by, "reason": reason},
        )
        return dict(result) if result else {}

#### C6: Update seed files with max_retries and validated handler names

**Files:**
- `src/control-plane-api/data/seeds/lablet_definitions/exam-associate-auto-v1.1-lab-2.5.1.yaml`
- `src/control-plane-api/data/seeds/lablet_definitions/exam-professional-enterprise-v2.0-lab-1.1.yaml`

Changes for BOTH seed files:

1. Add pipeline-level `max_retries` and `retry_backoff` to each pipeline:
     pipelines:
       instantiate:
         description: ...
         trigger: on_status:instantiating
         max_retries: 3
         retry_backoff: 30
         steps: [...]

2. Validate that ALL handler names in the `instantiate` pipeline match existing
   `_step_*` methods in lablet_reconciler.py. Current valid handlers:
   content_sync, variables, lab_resolve, ports_alloc, tags_sync,
   lab_binding, lab_start, lds_provision, mark_ready

3. For pipelines with handlers that DON'T exist yet (collect_evidence, compute_grading,
   teardown), keep the pipeline definitions but mark ALL their steps as handler TBD
   with a comment. This documents the intended pipeline structure without requiring
   non-existent handlers:
     teardown:
       description: ...
       trigger: on_status:stopping
       max_retries: 1
       retry_backoff: 10
       steps:
         - name: stop_lab
           handler: stop_lab          # TBD: Sprint D — decompose from _handle_stopping()
           description: Stop the CML lab
           timeout_seconds: 120

4. Ensure seed files load correctly by running the CPA seeder or test suite.

**These seed files are mandatory Sprint C deliverables.**

#### C7: Tests

**File:** `src/lablet-controller/tests/test_pipeline_executor.py`

Update TestProgressPersistence tests (3 tests) to assert the new per-step
`update_instantiation_progress(session_id=..., step_name=..., step_status=..., ...)`
signature. Add tests for resumability:
- test_resume_skips_completed_steps
- test_resume_retries_failed_step
- test_resume_restores_completed_step_data_to_context

**File:** `src/lablet-controller/tests/test_instantiation_pipeline.py`

REWRITE _handle_instantiating tests (no legacy path). New tests:
- test_handle_instantiating_starts_handler_with_pipeline
- test_handle_instantiating_running_handler_returns_success
- test_handle_instantiating_completed_handler_cleans_up_and_succeeds
- test_handle_instantiating_failed_handler_increments_retry
- test_handle_instantiating_max_retries_terminates_session
- test_handle_instantiating_no_pipeline_terminates_session
- test_handle_instantiating_resumes_from_existing_progress

Update make_reconciler() fixture to include _active_handlers, _session_locks,
_pipeline_executor, _pipeline_retry_counts, _get_pipeline_def, _build_pipeline_context,
_build_step_dispatcher.

**File:** `src/lablet-controller/tests/test_lifecycle_phase_handler.py` (NEW)

Test categories:
- Lifecycle: start/stop/is_running/double-start idempotency
- Completion: _on_complete stores result, does not auto-terminate
- Failure: _on_error logs exception, handler finishes (no auto-terminate)
- Cancellation: stop() during execution cancels cleanly
- Result: result property returns PipelineResult after completion

Target: 15–20 tests, all pure async.

**File:** `src/lablet-controller/tests/test_reconciler_concurrency.py` (NEW)

Test categories:
- Lock creation: _get_session_lock returns same lock for same session_id
- Lock isolation: different session_ids get different locks
- Serialization: concurrent reconcile calls for same session execute sequentially
- Handler deduplication: rapid reconcile calls don't create duplicate handlers
- Step-down cleanup: _step_down cancels all handlers and clears locks

Target: 8–12 tests, async with asyncio synchronization.

**File:** `src/control-plane-api/tests/...` (NEW or existing)

Test for the new internal terminate endpoint:
- test_terminate_session_internal_success
- test_terminate_session_internal_already_terminated
- test_terminate_session_internal_requires_api_key

### Implementation Order

1. C0 — Fix _persist_progress + add resumability + PipelineResult.max_retries (executor)
2. C5 — Internal terminate endpoint + CPA client method (CPA side, independent)
3. C1 — Create LifecyclePhaseHandler (no reconciler dependency)
4. C2 — Add per-session locks (small reconciler change)
5. C3 — Add _active_handlers, helper methods, _step_down updates
6. C4 — Refactor _handle_instantiating (depends on C1, C2, C3, C5)
7. C6 — Update seed files (depends on C4 being clear about handler names)
8. C7 — All tests (after implementation is complete)

### Implementation Guidelines

- Use `lcm-senior-architect` mode conventions
- All imports at module level (no inline imports), except TYPE_CHECKING
- Black formatting (line-length 200 in lablet-controller, 120 in control-plane-api — check pyproject.toml)
- Ruff linting (rules E, F, W, I, UP)
- Run `make lint` and `make test` in BOTH lablet-controller AND control-plane-api
- Store architectural decisions for design choices made
- Register new files with add_file_context
- Store relevant knowledge while working through this step by step
- Ask clarifications along the way — do not invent, verify accuracy
- Be aware of response length limits — prepare follow-up prompts when needed

### Validation

After implementation:
- [ ] _persist_progress calls CPA with per-step params matching real API signature
- [ ] Pipeline resumability: executor skips completed steps, retries failed step
- [ ] PipelineResult includes max_retries from pipeline def
- [ ] LifecyclePhaseHandler start/stop/is_running work correctly
- [ ] Handler does NOT auto-terminate on failure — reconciler decides
- [ ] Per-session locks prevent duplicate handler creation
- [ ] _handle_instantiating delegates to handler (no legacy fallback)
- [ ] _handle_instantiating resumes pipeline from existing progress on retry
- [ ] _handle_instantiating terminates session after max_retries exhausted
- [ ] _handle_instantiating terminates session if no pipeline defined
- [ ] Internal terminate endpoint works with API key auth
- [ ] CPA client terminate_session() method works
- [ ] Legacy helpers removed: _build_default_progress, _next_executable_step, etc.
- [ ] Seed files have max_retries, validated handler names, TBD markers for future handlers
- [ ] Seed files load correctly via CPA seeder
- [ ] _step_down cancels all active handlers and clears locks + retry counts
- [ ] All existing tests updated (no legacy path tests)
- [ ] New tests: ~50–65 additional tests all passing
- [ ] `make lint` and `make test` pass in lablet-controller
- [ ] `make lint` and `make test` pass in control-plane-api
```

---

## Sprint D — Follow-Up: Additional Pipeline Handlers + Teardown

> **Scope:** Implement pipeline delegation for `_handle_stopping()`, `_handle_collecting()`,
> `_handle_grading()` following the same pattern established in Sprint C.

**Tasks:**

- D1: Decompose `_handle_stopping()` inline logic into `_step_stop_lab`, `_step_wipe_lab`,
  `_step_deregister_lds`, `_step_archive` step handlers
- D2: Wire `_handle_stopping()` to use LifecyclePhaseHandler + teardown pipeline
- D3: Create stub `_step_capture_configs`, `_step_package_evidence` etc. for collect_evidence
- D4: Create stub `_step_load_rubric`, `_step_evaluate`, `_step_record_score` for grading
- D5: Wire `_handle_collecting()` and `_handle_grading()` to pipeline delegation
- D6: Tests for all new step handlers and pipeline delegation paths
- D7: Remove TBD markers from seed files — all handlers now exist

---

## Sprint E — Follow-Up: UX, SSE Events, Queries & Frontend

> **Scope:** Improve the user experience throughout entity lifecycle with real-time
> pipeline progress, extended queries, and frontend enhancements.

**E1: Pipeline Progress SSE Events**

Pipeline step completion/failure must be broadcast to connected UI clients via SSE.

- Add new CloudEvent types for pipeline progress:
  - `pipeline.step.completed.v1` — step_name, step_status, result_data, duration
  - `pipeline.step.failed.v1` — step_name, error, attempt, max_attempts
  - `pipeline.started.v1` — pipeline_name, session_id, step_count
  - `pipeline.completed.v1` — pipeline_name, status, duration_seconds, outputs
  - `pipeline.retry.v1` — pipeline_name, retry_count, max_retries, reason
- Wire PipelineExecutor to emit events after each step (via context.api or event bus)
- SSE projector in CPA receives events and broadcasts to subscribed UI clients
- UI can subscribe to pipeline progress for a specific session

**E2: Pipeline Progress Projectors (CPA Read Side)**

Create read-side projectors that maintain queryable pipeline execution history:

- `PipelineExecutionProjector` — listens to pipeline CloudEvents, stores execution records
- Read model: `PipelineExecutionRecord` (session_id, pipeline_name, status, steps[], started_at,
  completed_at, duration_seconds, retry_count, outputs, error)
- Storage: MongoDB collection `pipeline_executions`
- Indexes: session_id, pipeline_name, status, started_at

**E3: Extended Queries**

New query endpoints for pipeline observability:

- `GET /api/pipeline-executions?session_id=...` — executions for a session
- `GET /api/pipeline-executions?pipeline_name=instantiate&status=failed` — failed instantiations
- `GET /api/pipeline-executions?from=...&to=...` — executions in datetime range
- `GET /api/pipeline-executions/{id}/steps` — step-level detail for an execution
- `GET /api/pipeline-executions/stats` — aggregated stats (avg duration, failure rate, etc.)
- `GET /api/lablet-sessions/{id}/pipeline-history` — all pipeline runs for a session

**E4: Frontend Pipeline Progress UI**

- Session detail page: Add pipeline progress panel showing step-by-step progress
  with real-time updates via SSE (step name, status icon, duration, error message)
- Session list page: Add pipeline status indicator column (running/completed/failed/retrying)
- Pipeline retry button: Allow user to manually trigger pipeline retry for failed sessions
- Pipeline terminate button: Allow user to force-terminate a failed session
- Pipeline timeline visualization: Show step execution sequence with timing bars
- Toast notifications: Pipeline completed/failed alerts via SSE

**E5: Admin Dashboard Enhancements**

- Pipeline health overview: Success/failure rates by pipeline type, avg duration trends
- Active pipelines panel: Currently running handlers with session info
- Failed pipelines queue: List of sessions with failed pipelines awaiting retry/intervention
- Retry/terminate bulk actions for admin users

**E6: Session Recovery UX**

- "Retry Pipeline" action on failed sessions — resets failed step to pending, triggers reconcile
- "View Pipeline Logs" — step-by-step execution log with timestamps and errors
- "Manual Override" — skip a failed step and continue (admin only)
- Visual diff: Compare expected vs actual pipeline state

---

## Full Sprint Roadmap

| Sprint | Focus | Deliverables |
|--------|-------|-------------|
| **A** ✅ | Foundation | pipelines field on ReadModel, simpleeval dependency |
| **B** ✅ | PipelineExecutor | DAG engine, skip_when, retry, timeout, 48 tests |
| **C** 🎯 | Reconciler Integration | LifecyclePhaseHandler, per-session locks, _handle_instantiating delegation, internal terminate endpoint, seed files, ~50 tests |
| **D** | Additional Handlers | Teardown step decomposition, collect/grade stubs, all pipelines delegated |
| **E** | UX & Observability | SSE events, projectors, extended queries, frontend pipeline progress |
