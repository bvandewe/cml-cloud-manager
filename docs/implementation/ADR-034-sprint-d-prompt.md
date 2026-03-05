# ADR-034 Implementation — Sprint D Session Prompt

> **Purpose:** Copy-paste this prompt to bootstrap a fresh AI agent session for implementing ADR-034 Sprint D (Teardown Pipeline + Evidence/Grading Stubs).
>
> **Prerequisites completed (Sprints A–C):**
>
> - `PipelineExecutor` with graphlib DAG, simpleeval skip_when, retry/timeout (577 lines)
> - `LifecyclePhaseHandler` — managed asyncio.Task wrapper (246 lines)
> - `_handle_instantiating()` — fire-and-check pattern with pipeline delegation
> - Per-session `asyncio.Lock`, `_active_handlers`, `_pipeline_retry_counts`
> - Pipeline helpers: `_get_pipeline_def()`, `_build_pipeline_context()`, `_build_step_dispatcher()`
> - Internal `POST /api/internal/lablet-sessions/{id}/terminate` endpoint
> - `PipelineResult.max_retries` for retry budget tracking
> - 126 tests across 4 files (all green)
> - 10 architectural decisions (AD-PIPELINE-002 through AD-PIPELINE-010)

---

## The Prompt

```
I need to implement ADR-034 Sprint D for the Lablet Cloud Manager project.
Read the implementation guide at docs/implementation/ADR-034-next-steps.md first.

### Context

Sprint D extends the pipeline-driven lifecycle pattern (established in Sprint C for
_handle_instantiating) to three more session statuses: STOPPING, COLLECTING, and GRADING.

The fire-and-check delegation pattern is fully established:
- Reconciler creates a LifecyclePhaseHandler with pipeline_def from the seed YAML
- Handler runs as a managed asyncio.Task using PipelineExecutor
- Reconciler checks handler status on each reconcile cycle (is_running? result?)
- Failed handlers get retried up to max_retries, then terminate the session

**Critical file:** `src/lablet-controller/application/hosted_services/lablet_reconciler.py`
**Reference pattern:** `_handle_instantiating()` (lines ~540–640) — copy this pattern for D2/D5.
**Seed files with pipeline definitions (already complete):**
- `src/control-plane-api/data/seeds/lablet_definitions/exam-associate-auto-v1.1-lab-2.5.1.yaml`
- `src/control-plane-api/data/seeds/lablet_definitions/exam-professional-enterprise-v1.0-lab-1.1.yaml`

### Sprint D Tasks

#### D1: Create 4 teardown step handlers

Create these new `_step_*` methods in the `lablet_reconciler.py` PIPELINE STEPS section.
Each follows the same signature pattern as existing step handlers:
`async def _step_X(self, instance: LabletSessionReadModel, progress: dict[str, Any]) -> dict[str, Any]`

Return format: `{"step": "step_name", "status": "completed"|"failed", "result_data": {...}}`

**1. `_step_stop_lab(instance, progress)`**
   - Get lab state via `self._cml_labs.get_lab_state()`
   - If BOOTED → call `self._cml_labs.stop_lab()` → poll `get_lab_state()` in a loop
     (every 5 seconds, up to timeout_seconds) until STOPPED or DEFINED_ON_CORE
   - If already STOPPED/DEFINED_ON_CORE → return immediately
   - If STARTED/QUEUED → poll until state changes
   - If no cml_lab_id → return success (nothing to stop)
   - Return: `{"lab_state": "STOPPED"}`
   - **CRITICAL:** Unlike the current _handle_stopping() which uses requeue for multi-cycle
     waiting, the pipeline step runs inside an asyncio.Task and can poll in a loop.
     Use `asyncio.sleep(5)` between polls. The PipelineExecutor's per-step `timeout_seconds`
     (120s from seed YAML) provides the outer timeout.

**2. `_step_deregister_lds(instance, progress)`**
   - Delegate to existing `self._archive_lds_session(instance)` helper (L1858)
   - If no LDS session → return success (no-op)
   - The step is `optional: true` in seed YAML, so failures won't block the pipeline
   - Return: `{"lds_archived": True}`

**3. `_step_wipe_lab(instance, progress)`**
   - Call `self._cml_labs.wipe_lab()` to reset lab to DEFINED_ON_CORE
   - Call `self._update_lab_record_status(cml_lab_id, worker_id, "wiped")`
   - If no cml_lab_id → return success (nothing to wipe)
   - Return: `{"lab_wiped": True}`

**4. `_step_archive(instance, progress)`**
   - Transition session to ARCHIVED: `self._api.transition_session(session_id, ARCHIVED, reason)`
   - Increment `self._labs_stopped` counter
   - Return: `{"archived_at": datetime.now(utc).isoformat()}`

#### D2: Wire `_handle_stopping()` to LifecyclePhaseHandler

Replace the current inline `_handle_stopping()` (lines ~1438–1525) with the
fire-and-check pattern from `_handle_instantiating()`.

Key changes:
- handler_key = `f"{instance.id}:teardown"`
- pipeline_name = `"teardown"` (matches the YAML key in seed files)
- Check existing handler → get pipeline_def → start new handler
- For progress resumability: teardown has no existing progress field on the read
  model, so pass `existing_progress=None` for now (no resumability for teardown in Sprint D)
- The existing `_archive_lds_session()` and `_record_lab_run_completed()` calls at
  the top of the current `_handle_stopping()` should move INTO the pipeline:
  - `_record_lab_run_completed` → call in `_step_archive` (or as a separate step
    if you prefer — but keep it simple, fold into `_step_archive`)
  - `_archive_lds_session` → now handled by `_step_deregister_lds`

#### D3: Create 4 stub step handlers for evidence collection

These are stubs that return success with placeholder data. They'll be fully
implemented when the evidence collection subsystem is built (Sprint F+).

**1. `_step_capture_configs(instance, progress)`**
   - Stub: log "capture_configs not yet implemented" → return `{"configs": [], "note": "stub"}`

**2. `_step_capture_screenshots(instance, progress)`**
   - Stub: `{"screenshots": [], "note": "stub"}`

**3. `_step_export_pcaps(instance, progress)`**
   - Stub: `{"pcaps": [], "note": "stub"}`

**4. `_step_package_evidence(instance, progress)`**
   - Stub: `{"evidence_uri": None, "note": "stub — no evidence collected yet"}`

#### D4: Create 3 stub step handlers for grading

Same stub pattern:

**1. `_step_load_rubric(instance, progress)`**
   - Stub: `{"rubric_loaded": False, "note": "stub"}`

**2. `_step_evaluate(instance, progress)`**
   - Stub: `{"score": None, "note": "stub — grading engine not implemented"}`

**3. `_step_record_score(instance, progress)`**
   - Stub: `{"score_report_id": None, "note": "stub"}`

#### D5: Wire `_handle_collecting()` and `_handle_grading()` + routing

**5a: Create `_handle_collecting()`**
   - Same fire-and-check pattern, pipeline_name = `"collect_evidence"`
   - handler_key = `f"{instance.id}:collect_evidence"`
   - existing_progress = None (no resume for stubs)

**5b: Create `_handle_grading()`**
   - Same fire-and-check pattern, pipeline_name = `"compute_grading"`
   - handler_key = `f"{instance.id}:compute_grading"`

**5c: Add status routing in `_reconcile_inner()`**
   Add handlers for COLLECTING and GRADING statuses in the if/elif chain (~L486–L497):
   ```python
   elif status == LabletSessionStatus.COLLECTING:
       return await self._handle_collecting(instance)
   elif status == LabletSessionStatus.GRADING:
       return await self._handle_grading(instance)
   ```

**5d: Update worker_ip validation**
   The early validation at ~L467 that checks for worker_ip currently only handles
   INSTANTIATING. Add COLLECTING, GRADING, and STOPPING to this check since they
   all need CML API access (COLLECTING and GRADING need to reach the lab for
   evidence/configs; STOPPING needs to stop/wipe the lab).

**5e: Update `_handle_running()` transition target**
   Currently, `_handle_running()` transitions expired sessions directly to STOPPING.
   With the full lifecycle pipeline, the flow should be:
   RUNNING → COLLECTING → GRADING → STOPPING (if definition has those pipelines)

   However, this is a design choice. For Sprint D, keep the existing RUNNING → STOPPING
   transition as-is. The COLLECTING/GRADING statuses will be triggered by external events
   (e.g., instructor ends session, auto-submission timer) in a future sprint. Sprint D only
   ensures the handlers EXIST so that if a session arrives in COLLECTING/GRADING status,
   the reconciler can handle it.

#### D6: Tests

Create `tests/test_teardown_pipeline.py` with tests for:

**Teardown step handlers (~15-20 tests):**

- `_step_stop_lab`: lab is BOOTED → polls until STOPPED; already STOPPED → immediate success;
  no cml_lab_id → success; poll timeout (mock slow response)
- `_step_deregister_lds`: with LDS session → archives; no LDS → no-op success;
  archive fails → raises (executor treats as failure, but step is optional)
- `_step_wipe_lab`: wipes and updates status; no cml_lab_id → success
- `_step_archive`: transitions to ARCHIVED; returns archived_at timestamp

**Stub handlers (~7 tests):**

- Each of the 7 stub handlers returns expected structure with "note": "stub"

**Delegation tests (~10-15 tests):**

- `_handle_stopping`: no handler → starts handler; handler running → returns success;
  handler completed → returns success; handler failed → retries; max retries → terminates;
  no teardown pipeline in definition → terminates
- `_handle_collecting`: same pattern with "collect_evidence" pipeline
- `_handle_grading`: same pattern with "compute_grading" pipeline
- Status routing: COLLECTING/GRADING statuses correctly dispatched

**Pattern:** Follow the fixture style in `tests/test_instantiation_pipeline.py`:

- `make_instance` fixture with `object.__new__(LabletReconciler)`
- AsyncMock for services (`_api`, `_cml_labs`, `_lds`)
- `pytest.mark.asyncio` (auto mode configured in pytest.ini)

#### D7: Validate seed files load with all handlers

- Write a test that loads each seed YAML file, extracts all pipeline definitions,
  collects all `handler` names across all steps, and asserts that
  `hasattr(reconciler, f"_step_{handler_name}")` is True for every handler.
- This is a meta-test that prevents drift between seed definitions and code.

### Implementation Guidelines

- Use `lcm-senior-architect` mode conventions
- All imports at module level (no inline imports)
- Black formatting (line-length 200)
- Ruff linting (rules E, F, W, I, UP)
- Run `make lint` and `make test` in lablet-controller after changes
- Store architectural decisions for any design choices made
- Register new files with add_file_context

### Key Design Decisions to Remember

- AD-PIPELINE-007: No auto-terminate on failure — reconciler retries with resumability
- AD-PIPELINE-008: Internal terminate endpoint for system-initiated termination
- AD-PIPELINE-009: No backward compat — all definitions MUST have pipelines
- AD-PIPELINE-010: graphlib.TopologicalSorter for DAG resolution

### Existing Infrastructure (DO NOT recreate)

These already exist and are tested:

- `PipelineExecutor` at `application/services/pipeline_executor.py` (577 lines)
- `LifecyclePhaseHandler` at `application/services/lifecycle_phase_handler.py` (246 lines)
- `PipelineContext` at `application/models/pipeline_context.py`
- `PipelineResult` at `application/models/pipeline_result.py`
- `_get_pipeline_def()`, `_build_pipeline_context()`, `_build_step_dispatcher()` helpers
- `_get_step_result_data()` helper for progress dict lookup
- `_active_handlers`, `_session_locks`, `_pipeline_retry_counts` on reconciler
- `_step_down()` with resilient handler cleanup (already handles any number of handlers)

### Validation

After implementation:

1. Run `make lint` in lablet-controller → must pass clean
2. Run `make test` in lablet-controller → ALL tests must pass (existing 126 + new Sprint D tests)
3. Verify: `_handle_stopping()` no longer has inline stop/wipe/archive logic
4. Verify: seed file handler names all resolve to `_step_*` methods (D7 meta-test)
5. Store architectural decisions for any design choices made

```

---

## Sprint D Risk Analysis

| Risk | Mitigation |
|------|-----------|
| `_step_stop_lab` polling loop blocks executor | PipelineExecutor's per-step `timeout_seconds` (120s) wraps the step in `asyncio.wait_for()` — poll loop is bounded |
| Stub handlers may mask integration issues | Stubs return structured data matching pipeline output definitions — real implementations replace in Sprint F+ |
| `_handle_running()` → COLLECTING transition not yet wired | Sprint D only creates the handlers; lifecycle triggers are Sprint E+ |
| _record_lab_run_completed migration | Fold into `_step_archive` to avoid adding a 5th teardown step — or create a separate `_step_record_run` step |
| Three new fire-and-check handlers increase reconciler size | All three follow identical patterns — consider a `_create_pipeline_handler()` helper to DRY |

## Sprint D Estimated Scope

| Component | Estimate |
|-----------|----------|
| 4 teardown step handlers | ~120 lines |
| 7 stub step handlers (evidence + grading) | ~70 lines |
| 3 delegation handlers (stopping/collecting/grading) | ~180 lines (copy pattern from _handle_instantiating) |
| Status routing + worker_ip updates | ~15 lines |
| Test file (`test_teardown_pipeline.py`) | ~600-800 lines, ~40-50 tests |
| **Total** | ~400 production lines + ~700 test lines |
