# Sprint 1: Critical UX Fixes

> **Effort:** 1–2 sessions
> **Dependencies:** None — can start immediately
> **Services:** control-plane-api (frontend)
> **Status:** ⬜ Not Started

## Objective

Fix high-visibility frontend bugs that impact daily operator experience. These are low-risk, high-impact changes that clear noise from the backlog.

## Tasks

### S1.1 — Fix LabRecord ↔ LabletSession Binding Display

**Problem:** The relationship between LabRecords and LabletSessions is not visible from both sides in the UI. Workers' and Labs' "Linked Lablets" section shows nothing, and Sessions show "No lablet bindings yet." even when bindings exist.

**Scope:**

- [ ] Audit the `labRecords` store and `sessions` store for cross-reference data
- [ ] Workers' Details modal > Labs tab: show linked LabletSession(s) per LabRecord
- [ ] Sessions' Details modal: show bound LabRecord(s) with worker name and lab status
- [ ] Verify SSE events propagate binding changes in real-time

**Files likely touched:**

- `src/control-plane-api/static/src/components/workers/WorkerDetailsModal.ts` (Labs tab)
- `src/control-plane-api/static/src/components/sessions/SessionDetailsModal.ts`
- `src/control-plane-api/static/src/stores/labRecordSlice.ts`
- `src/control-plane-api/static/src/stores/sessionSlice.ts`

**Acceptance Criteria:**

- LabRecord rows in Worker Details show linked session name/status
- Session Details shows bound LabRecord(s) with worker name, lab status badge
- Changes propagate via SSE without page reload

---

### S1.2 — Use Worker.name in Lab Records Views

**Problem:** Lab Records tables and detail views display `worker_id` (UUID) instead of the human-readable `Worker.name`. UUIDs are unreadable for operators.

**Scope:**

- [ ] Replace `worker_id` display with `worker.name` in Lab Records datatable
- [ ] Add `worker_id` as info icon tooltip (Bootstrap tooltip)
- [ ] Ensure worker name is available in Lab Record DTOs or resolvable via workers store

**Files likely touched:**

- `src/control-plane-api/static/src/pages/LabRecordsPage.ts` (or equivalent datatable config)
- `src/control-plane-api/static/src/stores/labRecordSlice.ts` (enrichment)

**Acceptance Criteria:**

- Lab Records table shows `Worker.name` column instead of UUID
- Hovering info icon shows full `worker_id` in tooltip
- No additional API calls (resolve from existing workers store)

---

### S1.3 — Fix extend_session Warning Banner

**Problem:** After a successful `extend_session` API call, the session still seems to expire earlier than expected.

**Scope:**

- [ ] Identify the warning banner component and its trigger condition
- [ ] Ensure the backend returns a
- [ ] Verify banner reappears when session approaches new expiry

**Files likely touched:**

- `src/control-plane-api/static/src/components/sessions/SessionWarningBanner.ts` (or similar)
- `src/control-plane-api/static/src/stores/sessionSlice.ts` (state update on extend)

**Acceptance Criteria:**

- Warning banner disappears within 2s of successful extension
- Banner reappears when new expiry is within threshold

---

### S1.4 — Verify Fleet Capacity for Imported Workers

**Problem:** Workers imported without templates have `declared_capacity = null`, causing Fleet Capacity panel to show incorrect totals. Auto-detect fallback was added but needs end-to-end verification.

**Scope:**

- [ ] Verify `UpdateWorkerCmlDataCommand` correctly derives capacity from `all_cpu_count` / `all_memory`
- [ ] Verify DTO mapper fallback populates `declared_capacity` when null
- [ ] Verify frontend `selectFleetCapacity` handles derived capacity correctly
- [ ] Add integration test if gap found

**Files likely touched:**

- `src/control-plane-api/application/commands/update_worker_cml_data_command.py`
- `src/control-plane-api/application/dtos/worker_dtos.py`
- Frontend capacity selectors (already fixed — verify)

**Acceptance Criteria:**

- Imported workers without templates show derived capacity in Fleet panel
- No NaN/null values in capacity totals

---

## Completion Checklist

- [ ] All 4 tasks implemented and manually verified
- [ ] Existing tests pass (`make test` in CPA)
- [ ] New vitest tests for any new frontend logic
- [ ] Commit: `fix: sprint 1 — critical UX fixes`
