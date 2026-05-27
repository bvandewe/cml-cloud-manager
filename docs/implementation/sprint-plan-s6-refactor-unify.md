# Sprint 6: Reconciler Refactor & Frontend Unification

> **Effort:** 2–3 sessions
> **Dependencies:** Sprint 5 (all pipelines finalized — reconciler shape stable)
> **Services:** lablet-controller, control-plane-api (frontend)
> **Status:** ⬜ Not Started

## Objective

Decompose the ~1,300-line reconciler into focused, testable modules. Unify frontend ResourceState display across all views. Add operator visibility into background reconciliation activity.

## Tasks

### S6.1 — Split Reconciler Into Smaller Classes

**Problem:** `lablet_reconciler.py` at ~1,300 lines is the largest single class. While it already delegates to helper modules (`lab_record_helpers`, `lab_resolution`, `lds_helpers`, `observation_helpers`, `run_history`), the core orchestration logic can be further decomposed.

**Scope:**

- [ ] Audit reconciler methods and group by concern:
  - **Session lifecycle orchestration** (create/transition/terminate)
  - **Lab resolution & binding** (match/create/bind labs)
  - **Pipeline dispatch** (which pipeline to run, when)
  - **Status routing** (map states to handlers)
- [ ] Extract 2–3 focused classes:
  - `SessionLifecycleOrchestrator` — session state machine transitions
  - `PipelineDispatcher` — decide and launch pipeline execution
  - `LabletReconciler` — reduced to coordination layer calling orchestrators
- [ ] Maintain existing test coverage — refactor must not break tests
- [ ] Keep `WatchTriggeredHostedService` base and leader election unchanged

**Files:**

- `src/lablet-controller/application/hosted_services/lablet_reconciler.py` (refactor)
- `src/lablet-controller/application/hosted_services/session_lifecycle.py` (create)
- `src/lablet-controller/application/hosted_services/pipeline_dispatcher.py` (create)
- `src/lablet-controller/tests/` (update imports, verify all pass)

**Acceptance Criteria:**

- Reconciler class under 400 lines
- Each extracted class has single responsibility
- All existing tests pass without modification (or minimal import updates)
- Tests: 5+ for new orchestrator/dispatcher classes

---

### S6.2 — Track 3: Frontend ResourceState Unification

**Problem:** Different pages display session/worker/lab lifecycle states inconsistently — different badge colors, different state names, different formatting.

**Scope:**

- [ ] Audit state display across all pages:
  - Workers datatable + details modal
  - Sessions datatable + details modal
  - Lab Records datatable + details modal
  - Definitions datatable + details modal
- [ ] Create unified `ResourceStateBadge` component with consistent color mapping:
  - Green: RUNNING, READY, ACTIVE
  - Blue: PENDING, INSTANTIATING, SCHEDULING
  - Yellow: STOPPING, COLLECTING, GRADING, SYNCING
  - Red: FAILED, ERROR, TERMINATED
  - Gray: STOPPED, ARCHIVED, UNKNOWN
- [ ] Create shared `TimedResourceDisplay` component for time-bounded resources:
  - Shows remaining time, progress bar, expiry warning
  - Used by Sessions, Workers (if time-bounded), Definitions (if valid_until set)
- [ ] Replace per-page badge logic with unified component

**Files:**

- `src/control-plane-api/static/src/components/shared/ResourceStateBadge.ts` (create)
- `src/control-plane-api/static/src/components/shared/TimedResourceDisplay.ts` (create)
- All page components (update to use shared components)

**Acceptance Criteria:**

- Consistent badge colors across all pages for equivalent states
- TimedResource display shows countdown/progress consistently
- Tests: 5+ vitest tests for badge/display components

---

### S6.3 — Add Activity Indicator During Reconciliation

**Problem:** No visual feedback when the system is actively reconciling a session (background pipeline running).

**Scope:**

- [ ] Emit SSE event type `reconciliation.active` / `reconciliation.idle` per session
- [ ] Show spinner/pulse animation on session row during active reconciliation
- [ ] Clear indicator when reconciliation completes or errors

**Files:**

- `src/lablet-controller/application/hosted_services/lablet_reconciler.py` (emit events)
- `src/control-plane-api/static/src/services/sseAdapter.ts` (handle event)
- `src/control-plane-api/static/src/stores/sessionSlice.ts` (reconciling flag)
- Frontend: Session datatable row indicator

---

### S6.4 — Add Discovery Countdown Indicator

**Problem:** Operators don't know when the next auto-discovery/refresh cycle will run.

**Scope:**

- [ ] Expose next-run timestamps from background jobs via API endpoint:
  - `GET /api/admin/jobs/status` → `{ "labs_refresh": { "next_run": "...", "last_run": "..." }, ... }`
- [ ] Display countdown in Workers and Sessions nav views
- [ ] Use a small progress bar or text countdown

**Files:**

- `src/control-plane-api/api/controllers/admin_controller.py` (or create)
- Frontend: Nav view header area

---

### S6.5 — Fix SSE Blocking Backend Auto-Reload

**Problem:** SSE connections block Uvicorn's auto-reload during development, requiring manual server restart.

**Scope:**

- [ ] Review `SSEEventRelay._shutdown_event` behavior during reload
- [ ] Ensure all SSE generator loops check shutdown event with short timeout
- [ ] Add `SIGTERM`/`SIGINT` handler to force-close SSE connections
- [ ] Verify with `make run` that file changes trigger clean reload

**Files:**

- `src/control-plane-api/application/services/sse_event_relay.py`
- `src/control-plane-api/api/controllers/events_controller.py`

---

## Completion Checklist

- [ ] Reconciler under 400 lines, tests pass
- [ ] Consistent badges across all pages
- [ ] Activity and countdown indicators visible
- [ ] SSE auto-reload works in dev mode
- [ ] `make test` passes (lablet-controller + CPA)
- [ ] `make lint` passes
- [ ] New tests: 15+
- [ ] Commits: one per task
