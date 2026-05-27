# Sprint 4: Timeslot & Scheduling Fixes

> **Effort:** 1–2 sessions
> **Dependencies:** Sprint 3 (definition as TimedResource enables definition-aware scheduling)
> **Services:** resource-scheduler, control-plane-api (frontend)
> **Status:** ⬜ Not Started

## Objective

Fix scheduling correctness issues. Bad placements waste expensive `m5zn.metal` instance time and require manual intervention. These fixes ensure sessions are placed on capable workers with valid timeslots.

## Tasks

### S4.1 — Fix Timeslot Handling

**Problem:** Timeslot logic has unresolved issues (root TODO: "Fix timeslot"). Needs investigation to determine exact failures.

**Scope:**

- [ ] Investigate current timeslot failures:
  - Sessions with past `timeslot_start` not expired?
  - Timeslot extension edge cases?
  - TimeslotManager → SchedulerHostedService handoff gaps?
- [ ] Fix identified issues
- [ ] Add regression tests

**Discovery Steps:**

1. Review `TimeslotManagerHostedService` logic for edge cases
2. Review `SchedulerHostedService` timeslot filtering
3. Check CPA's `ExtendSessionCommand` and `ExpireSessionCommand`
4. Test with manual session creation at various timeslot boundaries

**Files likely touched:**

- `src/resource-scheduler/application/hosted_services/timeslot_manager.py`
- `src/resource-scheduler/application/hosted_services/scheduler.py`
- `src/control-plane-api/application/commands/session/` (timeslot commands)

---

### S4.2 — Validate Worker Supports Required Node/Image Definitions

**Problem:** The scheduler assigns sessions to workers without verifying the worker has the required CML node definitions and image definitions from the `cml.yml` topology.

**Scope:**

- [ ] Extend `list_resources()` or placement scoring to check worker's `node_definitions` against session's topology requirements
- [ ] If a topology requires `iosv` node definition but worker only has `iosvl2`, reject that placement
- [ ] Add scoring penalty for workers missing optional image definitions
- [ ] Return clear error message when no worker can satisfy requirements

**Pattern:** Resource-scheduler already queries CPA for worker data. Add node_definition compatibility check to the scoring function.

**Files likely touched:**

- `src/resource-scheduler/application/services/scoring.py` (or equivalent)
- `src/resource-scheduler/application/services/placement.py`
- `src/resource-scheduler/tests/` (scoring tests)

**Acceptance Criteria:**

- Session with `cml.yml` requiring `iosv` only placed on workers that have `iosv` node def
- Clear error when no compatible worker available
- Tests: 3+ tests (compatible, incompatible, partial match)

---

### S4.3 — Limit Available Regions in "Create Session" Modal

**Problem:** The "Create Lablet Session" modal shows all AWS regions, but the system only has workers deployed in specific regions.

**Scope:**

- [ ] Query available regions from workers store (distinct `aws_region` values from running workers)
- [ ] Populate region dropdown with only available regions
- [ ] Show "(no workers)" indicator for regions without running workers
- [ ] Default to region with most available capacity

**Files likely touched:**

- Frontend: Create Session modal component
- `src/control-plane-api/static/src/stores/workerSlice.ts` (selector for available regions)

**Acceptance Criteria:**

- Only regions with running workers are selectable
- Region selector shows worker count per region

---

### S4.4 — Add LabRecord Decision to Placement Preview

**Problem:** The "Placement Preview" command shows scheduling intent but not the resulting LabRecord decision — whether it matched an existing lab or would create a new one.

**Scope:**

- [ ] Extend placement preview response to include:
  - `lab_decision`: "reuse_existing" | "create_new"
  - `matched_lab_id`: (if reusing existing)
  - `reason`: explanation of matching logic
- [ ] Update frontend Placement Preview display with decision details

**Files likely touched:**

- `src/resource-scheduler/api/controllers/` (preview endpoint)
- `src/resource-scheduler/application/services/placement.py` (decision output)
- Frontend: Placement Preview component

**Acceptance Criteria:**

- Preview shows whether lab will be reused or created
- If reusing, shows matched lab ID and match reason

---

## Completion Checklist

- [ ] All 4 tasks implemented
- [ ] `make test` passes (resource-scheduler + CPA)
- [ ] `make lint` passes
- [ ] New tests: 8+ across scheduler and CPA
- [ ] Commit: `fix: sprint 4 — timeslot and scheduling correctness`
