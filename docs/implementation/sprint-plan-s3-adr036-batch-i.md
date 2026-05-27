# Sprint 3: ADR-036 Batch I — LabletDefinition → TimedResourceState

> **Effort:** 1–2 sessions
> **Dependencies:** ADR-036 Batches A–G complete (✅)
> **Services:** lcm-core, control-plane-api
> **Status:** ⬜ Not Started

## Objective

Promote `LabletDefinitionState` from raw `AggregateState[str]` to `TimedResourceState` (Layer 2 of the resource hierarchy). This is the **last aggregate** to join the unified resource model per ADR-036, closing the architecture gap before Phase 5 grading integration.

**Decision Reference:** AD-I0 (already recorded in Knowledge Manager)

## Context

The resource hierarchy (ADR-036) defines:

- **Layer 1** — `ResourceState`: spec/status, state_history with StateTransition, `_record_transition()`
- **Layer 2** — `TimedResourceState(ResourceState)`: adds `timeslot_start`, `timeslot_end`, `owner_id`, time-bounded lifecycle
- **Layer 3** — `ManagedLifecycleState(TimedResourceState)`: adds `desired_status`, reconciliation tracking

All aggregates (CMLWorker, LabletSession, LabRecord) already migrated. LabletDefinition is the last one.

## Tasks

### S3.1 — Promote LabletDefinitionState Base Class

**Scope:**

- [ ] Change `LabletDefinitionState` base class from `AggregateState[str]` to `TimedResourceState`
- [ ] Add required fields: `owner_id`, `created_at`, `updated_at`
- [ ] Initialize `state_history: list[StateTransition]` in `__init__`
- [ ] Ensure `id` field mapping is preserved (string-based IDs)

**Pattern Reference:** Follow `LabRecordState` migration (Batch G) — same pattern.

**Files:**

- `src/control-plane-api/domain/entities/lablet_definition.py`
- `src/core/lcm_core/domain/entities/resource.py` (verify base class API)
- `src/core/lcm_core/domain/entities/timed_resource.py` (verify Layer 2 API)

---

### S3.2 — Wire `_record_transition()` into Dispatch Handlers

**Scope:**

- [ ] Audit all `@dispatch` handlers in `LabletDefinitionState`
- [ ] Add `self._record_transition(old_status, new_status, reason)` calls in each handler that changes status
- [ ] Map definition statuses to StateTransition entries (e.g., `draft → syncing → ready → archived`)

**Files:**

- `src/control-plane-api/domain/entities/lablet_definition.py` (dispatch handlers)

---

### S3.3 — Add Time-Bounded Fields and Owner

**Scope:**

- [ ] Map `created_by` → `owner_id` (or add `owner_id` alongside)
- [ ] Add `valid_from` / `valid_until` for definition expiry support
- [ ] Wire into domain events: `LabletDefinitionCreatedDomainEvent` should carry `owner_id`
- [ ] Update `LabletDefinitionRepository` query methods if needed

**Files:**

- `src/control-plane-api/domain/entities/lablet_definition.py`
- `src/control-plane-api/domain/events/` (definition events)
- `src/control-plane-api/integration/repositories/` (definition repository)

---

### S3.4 — Track and Display Definition Revision + Last Updated

**Scope:**

- [ ] Expose `state_version` as `revision` in LabletDefinition DTOs
- [ ] Add `last_updated` (from `updated_at` or latest state_history entry)
- [ ] Update Definitions datatable to show revision number and last-updated timestamp
- [ ] Update Definition Details modal with version info

**Files:**

- `src/control-plane-api/application/dtos/` (definition DTOs)
- `src/control-plane-api/application/queries/` (definition queries — mapper)
- Frontend: Definitions page datatable columns + detail modal

---

### S3.5 — Update Seeds and Tests

**Scope:**

- [ ] Update YAML seed files in `data/seeds/` to include new fields (`owner_id`, etc.)
- [ ] Add/update unit tests for LabletDefinitionState with ResourceState assertions
- [ ] Verify `state_history` populated correctly through lifecycle
- [ ] Run full CPA test suite to detect regressions

**Files:**

- `src/control-plane-api/data/seeds/` (definition seed files)
- `src/control-plane-api/tests/domain/test_lablet_definition.py` (add/update)

---

## Acceptance Criteria

- [ ] `LabletDefinitionState` extends `TimedResourceState`
- [ ] All dispatch handlers call `_record_transition()`
- [ ] `state_history` tracks full lifecycle in MongoDB documents
- [ ] Definition DTOs expose `revision` and `last_updated`
- [ ] Frontend shows revision and last-updated columns
- [ ] Existing seeds load without errors
- [ ] `make test` passes (CPA + core)
- [ ] `make lint` passes

## Completion

- Commit: `feat: ADR-036 batch I — promote LabletDefinition to TimedResourceState`
- Store AD-I0 completion in Knowledge Manager
- Update `IMPLEMENTATION_STATUS.md`
