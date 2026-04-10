# TODO

## ~~Track 1: Fix Lab Provisioning (lab_resolve + lab_start) — CRITICAL~~ ✅ COMPLETE

All 4 bugs verified fixed in production code. Stale tests remediated with 16 new/rewritten
tests covering ghost detection, definition_id matching, ORPHANED marking, and preference ordering.

### ~~Bug 1: Topology matching uses `node_count` instead of `definition_id`~~ ✅

- **Status**: Already fixed — `_try_reuse_existing_lab()` filters on `lr.based_on_definition_id != instance.definition_id`
- **Tests**: `TestTryReuseExistingLab` rewritten (10 tests) in `test_phase9_lab_discovery.py`

### ~~Bug 2: No CML lab existence verification before reuse binding~~ ✅

- **Status**: Already fixed — calls `get_lab()` per candidate, marks ORPHANED on `None`
- **Tests**: Ghost detection tested (skip + fallthrough + ORPHANED marking) in `test_phase9_lab_discovery.py`

### ~~Bug 3: `_register_lab_record` doesn't set `based_on_definition_id`~~ ✅

- **Status**: Already fixed — lab_entry includes `"based_on_definition_id": instance.definition_id or None`
- **Tests**: `TestRegisterLabRecord` assertion added in `test_instantiation_pipeline.py`

### ~~Bug 4: `_step_lab_start` doesn't verify lab existence before polling~~ ✅

- **Status**: Already fixed — `if lab_state is None:` guard with ORPHANED marking
- **Tests**: `TestStepLabStart` class (5 tests) added in `test_instantiation_pipeline.py`

## ~~Track 2: SSE Event Coverage Gaps — MODERATE~~ ✅ COMPLETE

All gaps resolved in prior session — architecture doc §5 updated with ✅ markers.

- [x] Add EXPIRED state SSE handler + etcd projector in CPA
- [x] Add missing sseAdapter.ts mappings: `score.recorded`, `timeslot.extended`, `ports.released`
- [x] Wire `pipeline.progress` and `desired_status.changed` to store dispatch

## Track 3: Frontend ResourceState Unification — LOW

- [ ] Audit page → store → component wiring for all session lifecycle states
- [ ] Unify TimedResource display across dashboard and detail views

## Issues

- [ ] Split the huge reconciliator class into smaller more manageable classes: /Users/bvandewe/Documents/Work/Systems/Mozart/src/microservices/lablet-cloud-manager/src/lablet-controller/application/hosted_services/lablet_reconciler.py
