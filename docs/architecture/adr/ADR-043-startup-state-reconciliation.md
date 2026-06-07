# ADR-043: Startup State Reconciliation and Discovery Separation

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-06-04 |
| **Deciders** | Platform Team |
| **Related ADRs** | [ADR-031](./ADR-031-checkpoint-instantiation-pipeline.md) (Checkpoint Pipeline), [ADR-014](./ADR-014-worker-orphan-detection.md) (Orphan Detection) |
| **Knowledge Refs** | AD-031, AD-043, AD-021 |

## Context

### External EC2 State Changes

CML workers run on AWS EC2 instances that can be stopped, terminated, or modified by
external means (AWS Console, cost automation, scheduled events, AWS maintenance). The LCM
application cannot assume that stored resource states are correct after a restart; it must
verify all resources against their actual state on boot.

### Current Behavior

The `WatchTriggeredHostedService` base class (AD-031) already runs a one-time startup
reconciliation sweep on leader election. However, this sweep calls `list_resources()` which
**filters out terminal statuses** (STOPPED, TERMINATED, FAILED, etc.) on the assumption that
terminal resources don't need reconciliation.

This creates gaps when the controller is down:

1. A **STOPPED** worker with `desired_status=RUNNING` won't be picked up (desired-state
   divergence missed).
2. A **STOPPED** worker whose EC2 was terminated externally remains stale indefinitely.
3. A **RUNNING** record whose EC2 was stopped is caught (non-terminal → `_handle_running`
   detects mismatch), but only because the filter happens to include it.

### Design Questions Resolved

1. **Should reconciliation always verify current state and conditions (e.g. timeline validity)?**
   → Yes. The reconciliation loop is the single authority for state alignment. It must verify
   the source of truth (EC2 API) rather than trusting stored status, especially at startup.

2. **Should discovery processes be extended to include state validation?**
   → No. Discovery ("What exists?") and reconciliation ("Is it correct?") remain separate
   concerns. Discovery feeds data to the reconciler; mixing validation into discovery would
   violate SRP and create overlapping ownership of state transitions.

## Decision

### 1. Startup Full-Sync for Worker-Controller

Add a **startup full-sync mode** to the worker-controller reconciler. When the startup
sweep runs, `list_resources()` returns ALL workers (including STOPPED) so the reconciler
can verify EC2 state and desired-state alignment for every worker.

**Mechanism:**

- Add a `_startup_sweep_active: bool` flag to `WatchTriggeredHostedService`.
- Set it `True` before the sweep, `False` after.
- Subclasses can check `self._startup_sweep_active` in `list_resources()` to adjust
  their filtering logic.

### 2. STOPPED Worker EC2 Verification

When a STOPPED worker is reconciled during the startup sweep, verify its EC2 instance state:

- If EC2 is terminated → transition to TERMINATED.
- If EC2 is running → transition to RUNNING (unexpected restart detected).
- If desired_status differs from current → initiate appropriate transition.
- If at rest (EC2 stopped, desired=stopped) → no-op (success).

### 3. Discovery Remains Separate

Discovery processes (worker discovery, lab discovery) continue to focus exclusively on
existence/absence detection. They do not perform state validation. They already fire early
at startup (5s delay) to provide fresh data for the reconciler.

### 4. Lablet-Controller Already Covered

The lablet-controller's startup sweep (AD-031) reconciles all non-terminal sessions. Since
lablet sessions depend on worker state (worker_ip resolution), the worker-controller's
startup sweep MUST complete before the lablet-controller acts on sessions requiring worker
connectivity. This is naturally ordered by the initial delay settings
(worker-controller: 2s sweep delay; lablet-controller: 2s sweep delay + worker_ip
enrichment retries).

## Consequences

### Positive

- **Correctness**: All stored states verified against reality on every boot.
- **Resilience**: External EC2 operations (manual stops, cost automation, maintenance)
  detected within seconds of leader election.
- **Separation preserved**: Discovery stays focused on existence; reconciliation owns
  state alignment.
- **Minimal blast radius**: Only the startup sweep is broadened; steady-state polling
  continues to filter terminal workers for efficiency.

### Negative

- **Startup load**: First reconciliation cycle processes more workers (all vs non-terminal).
  Mitigated by `max_concurrent_reconciles=5` semaphore.
- **EC2 API calls at boot**: One `describe_instances` per stopped worker. Acceptable given
  m5zn.metal instances are few (typically < 20).

### Neutral

- No API contract changes to Control Plane API.
- No new configuration required (uses existing `startup_reconcile_enabled` flag).
- Pattern is consistent with how the lablet-controller already operates.

## Implementation

### Files Modified

| File | Change |
|------|--------|
| `src/core/lcm_core/infrastructure/hosted_services/watch_triggered_hosted_service.py` | Add `_startup_sweep_active` flag |
| `src/worker-controller/application/hosted_services/worker_reconciler.py` | Broaden `list_resources()` during startup; add EC2 verification to `_handle_stopped()` |
| `src/core/tests/test_watch_triggered_hosted_service.py` | Test startup flag lifecycle |
| `src/worker-controller/tests/` | Test startup full-sync behavior |

### Startup Sequence (Updated)

```
┌─── Leader Election ───────────────────────────────────────────────┐
│  1. _become_leader()                                               │
│  2. Start watch loop (etcd prefix monitoring)                      │
│  3. Start metrics loop (independent, periodic)                     │
│  4. Start discovery loop (independent, periodic)                   │
│  5. _startup_reconcile_sweep():                                    │
│     a. Set _startup_sweep_active = True                            │
│     b. _reconcile_all() → list_resources() returns ALL workers     │
│     c. For each worker: verify EC2 state, align desired state      │
│     d. Set _startup_sweep_active = False                           │
│  6. Resume normal polling/watch (list_resources filters terminals)  │
└────────────────────────────────────────────────────────────────────┘
```
