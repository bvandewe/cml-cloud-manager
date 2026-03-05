# Worker Capacity Resolution

## Objective

Investigate and fix why the placement engine incorrectly rejects the running EPM CML DEV worker for new sessions, recommending unnecessary scale-up. Fix the capacity tracking bugs that cause phantom-allocated capacity to accumulate on workers.

## Current Symptom

From `resource-scheduler.log` (March 3, 2026):

```
Worker EPM CML DEV v0.1.8 - Jan 2026: no declared_capacity, derived from cml_system_info: cpu=48, mem=188GB, storage=247GB
Worker EPM CML DEV v0.1.8 - Jan 2026: using API capacity (cpu=24, mem=140GB, storage=7GB)
Worker EPM CML DEV v0.1.8 - Jan 2026 excluded: insufficient capacity or session limit reached
Scaling up with default 'multi-sessions' template.
No eligible workers for instance 11973c48-253e-4d93-bc72-96f5d3421321, recommending scale_up with template multi-sessions
```

The worker has **only 7GB storage available** out of 247GB. CPU (24 avail) and memory (140GB avail) are fine. The placement engine correctly rejects — the bug is upstream in how `allocated_capacity` accumulates without proper release.

## Root Cause Analysis (Already Completed)

Three capacity tracking bugs were identified:

### Bug 1: `ExpireLabletSessionCommand` Leaks Capacity (CRITICAL)

**File:** `src/control-plane-api/application/commands/expire_lablet_session_command.py`

When a session expires (timeslot end), the handler calls `ReleaseCapacityCommand` **without resource values**:

```python
ReleaseCapacityCommand(
    worker_id=session.state.worker_id,
    session_id=request.session_id,
    # cpu_cores, memory_gb, storage_gb all default to 0!
)
```

Since `ReleaseCapacityCommand` has `cpu_cores: int = 0, memory_gb: int = 0, storage_gb: int = 0` as defaults, this **removes the session_id from `session_ids` but does NOT reduce `allocated_capacity`**. Every expired session leaves phantom capacity permanently allocated.

### Bug 2: `TerminateLabletSessionCommand` Possible Parameter Mismatch

**File:** `src/control-plane-api/application/commands/terminate_lablet_session_command.py`

The terminate handler passes `instance_id` instead of `session_id`:

```python
ReleaseCapacityCommand(
    worker_id=session.state.worker_id,
    instance_id=session.id(),  # ⚠️ ReleaseCapacityCommand expects session_id, not instance_id
    cpu_cores=cpu_cores,
    memory_gb=memory_gb,
    storage_gb=storage_gb,
)
```

Verify whether this is a real bug or a field alias. If `instance_id` is not a valid field on `ReleaseCapacityCommand`, the release silently fails.

### Bug 3: No Capacity Release for `completed` or `failed` Sessions

No handler for `completed` or `failed` session status explicitly calls `ReleaseCapacityCommand`. If sessions reach these states without going through `terminate`, capacity leaks.

## What Was Already Fixed (Prior Session — AD-CONFIG-001)

- ✅ `src/worker-controller/config/aws_regions.yaml` — Replaced placeholder SG/subnet with real values (`sg-0c509ac3094df5a77`, `subnet-1f765943`)
- ✅ `src/control-plane-api/data/seeds/system_settings/default.yaml` — Updated stale AMI (`cisco-cml2.9-lablet-v0.1.8`), instance type (`m5zn.metal`), SG, subnet, AMI IDs

## Tasks for This Session

### Phase 1: Diagnose Current State

1. **Query the running CPA** for the EPM CML DEV worker document:
   - `GET /api/internal/workers` or check MongoDB directly
   - Inspect `allocated_capacity`, `session_ids`, `declared_capacity`, `cml_system_info`
   - Count how many sessions are assigned vs. how many are actually active

2. **Query sessions** to find stale ones:
   - `GET /api/internal/sessions` or check MongoDB
   - Look for sessions in `scheduled`, `assigned`, `instantiating` that have been stuck
   - Check if any `expired`, `completed`, `failed` sessions still appear in the worker's `session_ids`

3. **Check CML directly** (optional):
   - `GET http://54.81.105.239/api/v0/system_stats` — Actual resource usage
   - `GET http://54.81.105.239/api/v0/labs` — Active labs on the worker
   - Compare CML-reported usage vs. CPA-tracked `allocated_capacity`

### Phase 2: Fix Capacity Release Bugs

4. **Fix `ExpireLabletSessionCommand`** — Pass actual resource values to `ReleaseCapacityCommand`:
   - Look up the LabletDefinition's `resource_requirements` (same pattern as `TerminateLabletSessionCommand`)
   - Pass `cpu_cores`, `memory_gb`, `storage_gb` to the release command

5. **Fix `TerminateLabletSessionCommand`** — Verify the `instance_id` vs `session_id` parameter:
   - If it's a bug, fix to use `session_id=session.id()`
   - If `instance_id` works (field alias), document why

6. **Add capacity release to session completion/failure paths**:
   - Ensure `CompleteLabletSessionCommand` (if exists) calls `ReleaseCapacityCommand`
   - Ensure `FailLabletSessionCommand` (if exists) calls `ReleaseCapacityCommand`
   - If these commands don't exist, identify what transitions sessions to `completed`/`failed` and add release there

### Phase 3: Add Capacity Reset/Recalculation

7. **Create a `RecalculateWorkerCapacityCommand`**:
   - Iterates the worker's `session_ids`
   - For each, looks up the session's definition `resource_requirements`
   - Sums to get the correct `allocated_capacity`
   - Replaces the current (possibly inflated) value
   - This is the "repair" command for data that's already drifted

8. **Add an internal API endpoint** for capacity recalculation:
   - `POST /api/internal/workers/{worker_id}/recalculate-capacity`
   - Can be called manually or by a periodic cleanup job

### Phase 4: Clean Up Stale Data

9. **Remove stale workers** from MongoDB:
   - The `lablet-cmlvm-20nodes` worker (`i-0c8cb22875e8f99e7`) is **Stopped** in a different VPC — should be cleaned from CPA if present
   - Verify the cleanup mechanism (`CleanupHostedService`) handles this, or remove manually

10. **Reset EPM CML DEV worker's capacity**:
    - After fixing the bugs, run the recalculation command
    - Verify placement engine now accepts the worker

### Phase 5: Tests & Verification

11. **Write tests** for the capacity release fixes:
    - Test `ExpireLabletSessionCommand` releases correct capacity values
    - Test `TerminateLabletSessionCommand` uses correct parameter name
    - Test `RecalculateWorkerCapacityCommand` correctly recomputes from active sessions

12. **Run placement preview** to verify:
    - After capacity reset, the worker should accept new sessions
    - `POST /api/scheduling/preview` with the exam definition should return `action=assign`

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/resource-scheduler/application/services/placement_engine.py` | Capacity check: `_check_resource_capacity()`, `_get_effective_declared_capacity()` |
| `src/control-plane-api/domain/entities/cml_worker.py` | Aggregate: `assign_session()`, `unassign_session()`, `allocated_capacity`, `available_capacity` |
| `src/control-plane-api/application/commands/allocate_capacity_command.py` | Allocates capacity + ports when session placed |
| `src/control-plane-api/application/commands/release_capacity_command.py` | Releases capacity + ports — accepts `session_id`, `cpu_cores`, `memory_gb`, `storage_gb` |
| `src/control-plane-api/application/commands/expire_lablet_session_command.py` | **BUG**: Calls release with 0 resource values |
| `src/control-plane-api/application/commands/terminate_lablet_session_command.py` | **BUG?**: Uses `instance_id` instead of `session_id` |
| `src/control-plane-api/application/commands/schedule_lablet_session_command.py` | Allocates capacity after placement decision |
| `src/control-plane-api/data/seeds/system_settings/default.yaml` | ✅ Fixed — real AWS values |
| `src/worker-controller/config/aws_regions.yaml` | ✅ Fixed — real SG/subnet |

## Capacity Data Flow

```
PlacementEngine                    CPA (MongoDB)                  CML Worker
     │                                  │                              │
     │ GET /internal/workers            │                              │
     │─────────────────────────────────>│                              │
     │   { allocated_capacity:          │                              │
     │     {cpu:24, mem:48, stor:240},  │                              │
     │     cml_system_info:             │                              │
     │     {cpu:48, mem:188GB,          │                              │
     │      storage:247GB},             │                              │
     │     session_ids: [...] }         │                              │
     │<─────────────────────────────────│                              │
     │                                  │                              │
     │ available = declared - allocated │                              │
     │ = {cpu:24, mem:140, stor:7}      │                              │
     │ required = {cpu:4, mem:8, stor:50}                              │
     │ → REJECTED (storage: 50 > 7)    │                              │
     │                                  │                              │
     │ decision: scale_up              │                              │
```

**The fix target:** Ensure `allocated_capacity` accurately reflects ONLY active sessions, not leaked phantom allocations from expired/terminated sessions that failed to release.

## Environment Notes

- **EPM CML DEV worker**: `i-019159ed0b8bbfb33`, m5zn.metal, Running, `54.81.105.239` (default VPC)
- **lablet-cmlvm-20nodes**: `i-0c8cb22875e8f99e7`, m5zn.metal, **Stopped** (lablets_prod VPC) — stale, should be cleaned
- **Docker stack**: Volume-mounted source, changes take effect immediately
- **CML credentials**: `admin` / `trackNMC50` (from `.env`)
- **CPA internal API**: `http://localhost:8080/api/internal/`
