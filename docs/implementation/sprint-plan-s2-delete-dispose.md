# Sprint 2: Delete & Dispose Commands

> **Effort:** 2 sessions
> **Dependencies:** None — can start immediately (parallel with Sprint 1)
> **Services:** control-plane-api (backend + frontend)
> **Status:** ⬜ Not Started

## Objective

Fill critical CRUD gaps. Without delete/dispose operations, operators cannot manage resource lifecycle end-to-end, and orphaned labs accumulate costs on expensive EC2 instances.

## Tasks

### S2.1 — Fix "Delete LabRecord" (Stop → Wipe → Delete Flow)

**Problem:** Current delete only issues a POST to `/delete` without first stopping and wiping the CML lab. This can leave orphaned labs running on workers.

**Scope:**

- [ ] Implement `DeleteLabRecordCommand` as a multi-step orchestration:
  1. If lab is running → stop it (await stopped state)
  2. Wipe lab data on CML worker
  3. Delete LabRecord aggregate
- [ ] Add confirmation dialog in frontend with "Stop & Wipe" warning
- [ ] Handle edge cases: lab already stopped, lab not found on worker (ORPHANED)
- [ ] Emit appropriate domain events for each step

**Pattern Reference:** Follow existing `StopLabRecordCommand` + `WipeLabRecordCommand` patterns. The delete command should orchestrate them in sequence.

**Files likely touched:**

- `src/control-plane-api/application/commands/lab_record/delete_lab_record_command.py` (modify)
- `src/control-plane-api/api/controllers/lab_records_controller.py` (endpoint)
- Frontend: LabRecords datatable action button + confirmation modal

**Acceptance Criteria:**

- Delete button triggers stop → wipe → delete sequence
- Confirmation dialog warns about data loss
- LabRecord removed from store after successful deletion
- SSE event broadcasts removal to other clients
- Tests: 3+ unit tests (happy path, already-stopped, orphaned)

---

### S2.2 — Add "Delete LabletDefinition" Command

**Problem:** No way to remove lablet definitions. Old/obsolete definitions clutter the UI and could be accidentally selected for new sessions.

**Scope:**

- [ ] Create `DeleteLabletDefinitionCommand` + handler
- [ ] Guard: cannot delete if active sessions reference this definition
- [ ] Soft-delete pattern: mark as `ARCHIVED` state first, then allow hard delete of archived definitions
- [ ] Add controller endpoint `DELETE /api/definitions/{id}`
- [ ] Add delete action to Definitions datatable in frontend

**Pattern Reference:** Follow `CreateLabletDefinitionCommand` for handler structure. Check `LabletSessionState.definition_id` for active references.

**Files to create/modify:**

- `src/control-plane-api/application/commands/definition/delete_lablet_definition_command.py` (create)
- `src/control-plane-api/api/controllers/definitions_controller.py` (add endpoint)
- `src/control-plane-api/domain/entities/lablet_definition.py` (add ARCHIVED event if needed)
- Frontend: Definitions datatable action column

**Acceptance Criteria:**

- DELETE endpoint returns 204 on success
- Returns 409 Conflict if active sessions reference this definition
- Archived definitions hidden from "Create Session" definition picker
- Tests: 4+ unit tests (happy, in-use guard, archive, hard-delete)

---

### S2.3 — Add "Dispose Orphaned Labs" Command + UI Button

**Problem:** Labs marked ORPHANED (no matching CML lab on worker) accumulate in the database. Operators need a bulk cleanup action.

**Scope:**

- [ ] Create `DisposeOrphanedLabsCommand` + handler
  - Query all LabRecords with status `ORPHANED`
  - Delete each from database (no CML API call needed — already orphaned)
  - Return count of disposed records
- [ ] Add bulk action button to Labs view toolbar ("Dispose Orphaned")
- [ ] Add confirmation dialog showing count before disposal

**Files to create/modify:**

- `src/control-plane-api/application/commands/lab_record/dispose_orphaned_labs_command.py` (create)
- `src/control-plane-api/api/controllers/lab_records_controller.py` (add endpoint)
- Frontend: Labs page toolbar button

**Acceptance Criteria:**

- Endpoint returns `{ "disposed_count": N }` on success
- Only ORPHANED records are affected (guard against other statuses)
- Confirmation dialog shows count and list preview
- Tests: 3+ unit tests (happy, no orphans, mixed statuses)

---

### S2.4 — Fix Tag CRUD Full Stack

**Problem:** Tag management (create, update, delete tags on workers/sessions) is broken or incomplete in the frontend-to-backend flow.

**Scope:**

- [ ] Audit existing Tag command/query implementations
- [ ] Verify API endpoints respond correctly (test with curl/Swagger)
- [ ] Fix frontend Tag CRUD UI (add/remove tags on worker/session detail modals)
- [ ] Ensure tags persist through aggregate state and survive SSE updates

**Files likely touched:**

- `src/control-plane-api/application/commands/` (tag-related commands)
- `src/control-plane-api/api/controllers/` (tag endpoints)
- Frontend: Tag component(s) in detail modals

**Acceptance Criteria:**

- Tags can be added, edited, deleted from Worker and Session detail modals
- Tags persist after page reload
- Tags visible in datatable columns

---

## Completion Checklist

- [ ] All 4 tasks implemented
- [ ] `make test` passes in CPA
- [ ] `make lint` passes
- [ ] New tests added for each command (target: 12+ new tests)
- [ ] Commit: `feat: sprint 2 — delete and dispose commands`
