# ADR-039: SSE Race Condition Fix

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-10 |
| **Deciders** | Platform Team |
| **Related ADRs** | [ADR-013](./ADR-013-sse-protocol-improvements.md) (SSE Protocol), [ADR-001](./ADR-001-api-centric-state-management.md) (API-Centric State) |
| **Knowledge Refs** | AD-SSE-RACE-001 |

## Context

When a user creates a new LabletSession via the frontend, the session appears stuck in **PENDING** status until the user manually clicks Refresh, at which point it shows **INSTANTIATING**. The expected behavior is that status transitions appear in real-time via SSE.

### Root Cause Analysis

Tracing the full event chain revealed a **classic race condition** between HTTP polling and SSE-driven state updates:

```
T+0ms     POST /api/v1/sessions → 201 Created (PENDING)
T+100ms   SSE: lablet.session.created → store.upsertSession({status: PENDING})
T+500ms   loadSessions() → GET /api/v1/sessions → replaceAll (stale PENDING data)  ← OVERWRITES SSE
T+500ms   etcd watch → resource-scheduler assigns worker
T+1000ms  SSE: lablet.session.status.changed → store.upsertSession({status: SCHEDULED})  ← OVERWRITTEN
T+1000ms  etcd watch → lablet-controller starts instantiation
T+1500ms  SSE: lablet.session.status.changed → store.upsertSession({status: INSTANTIATING})  ← OVERWRITTEN
```

The `replaceAll` at T+500ms overwrites the SSE-driven `upsertSession` updates with stale HTTP data fetched before the backend completed the PENDING → SCHEDULED → INSTANTIATING chain (~1–1.5s via two 0.5s etcd watch debounces).

### Secondary Issues Discovered

1. **Timeslot extended handler**: Used `data.timeslot` instead of actual backend field `data.new_timeslot_end`
2. **Score recorded handler**: Used `data.score`/`data.grading_result` instead of `data.score_report_id`/`data.grade_result`
3. **Dead eventMap entries**: 9 per-status wire types (`lablet.session.scheduled`, `.instantiating`, etc.) that the backend never emits — backend uses single `lablet.session.status.changed`
4. **Minimal created SSE payload**: `lablet.session.created` event lacked status, definition, and timeslot info

## Decision

Implement a **7-fix remediation** addressing the race condition root cause and secondary data shape issues.

### Fix 1: HTTP Create Response Upsert

Immediately populate the store from the HTTP 201 response after session creation, rather than waiting for SSE or a deferred GET:

```javascript
// lablet-modals.js — setupCreateLabletSessionModal()
if (result && result.id) {
    store.dispatch('sessions', 'upsertSession', result);
}
```

### Fix 2: Timestamp-Guarded `mergeAll` Reducer

Replace `replaceAll` (destructive overwrite) with a new `mergeAll` reducer that protects SSE-updated fields using a `_sseUpdatedAt` timestamp:

```javascript
// sessionsSlice.js
mergeAll(sessions) {
    const sseProtectedFields = ['status', 'pipeline_progress', 'worker_id',
                                 'desired_status', '_sseUpdatedAt'];
    for (const session of sessions) {
        const existing = state.byId[session.id];
        if (existing?._sseUpdatedAt) {
            const sseAge = Date.now() - existing._sseUpdatedAt;
            if (sseAge < 5000) {
                // Merge HTTP data but preserve SSE-driven fields
                const preserved = {};
                for (const f of sseProtectedFields) {
                    if (existing[f] !== undefined) preserved[f] = existing[f];
                }
                state.byId[session.id] = { ...session, ...preserved };
                continue;
            }
        }
        // No SSE protection — full replace
        state.byId[session.id] = session;
    }
}
```

The `upsertSession` action (used by SSE handlers) now stamps `_sseUpdatedAt = Date.now()`.

### Fix 3: Deferred Reload (500ms → 3000ms)

Increase the `UI_SESSION_CREATED` reload delay from 500ms to 3000ms, allowing the PENDING → SCHEDULED → INSTANTIATING chain to complete before the next HTTP poll.

### Fix 4: Enriched `created` SSE Payload

Add `status`, `definition_name`, `definition_version`, `timeslot_start`, `timeslot_end`, and `reservation_id` to the `lablet.session.created` SSE event payload.

### Fix 5: Timeslot Extended Data Shape Fix

Align the SSE handler field name: `data.timeslot` → `data.new_timeslot_end`.

### Fix 6: Score Recorded Field Names Fix

Align the SSE handler field names: `data.score` → `data.score_report_id`, `data.grading_result` → `data.grade_result`.

### Fix 7: Dead eventMap Cleanup

Comment out 9 dead per-status wire type entries (`lablet.session.scheduled`, `.instantiating`, `.ready`, `.running`, `.collecting`, `.grading`, `.stopping`, `.stopped`, `.archived`) — the backend emits a single `lablet.session.status.changed` wire type for all transitions.

## Rationale

### Why timestamp-guarded merge instead of just increasing delay?

A longer delay alone is fragile — network variability or server load can shift the race window. The `_sseUpdatedAt` guard ensures SSE-driven fields are **never** overwritten by stale HTTP data within a 5-second window, regardless of timing.

### Why keep the deferred reload at all?

The HTTP reload ensures the store has a complete picture of all sessions (not just the one created). It also fetches server-enriched fields that aren't in the SSE payload.

### Why not use SSE exclusively (no HTTP polling)?

SSE provides incremental updates, not full state snapshots. The HTTP endpoint returns enriched DTOs with computed fields, relations, and filtering. Both channels complement each other.

## Consequences

### Positive

- **Immediate feedback**: Session appears in the UI within ~100ms of creation (HTTP response upsert)
- **No stale overwrites**: SSE-driven status updates survive HTTP polling cycles
- **Covers all transitions**: The `LABLET_SESSION_STATUS_CHANGED` handler is generic — works for every lifecycle state
- **Data correctness**: Timeslot and score handlers now match actual backend payloads
- **Cleaner codebase**: Dead eventMap entries removed, reducing confusion

### Negative

- **5-second SSE protection window**: During this window, HTTP data for protected fields is discarded; if SSE delivers incorrect data, it won't be corrected until the window expires
- **Increased complexity**: `mergeAll` is more complex than `replaceAll`

### Risks

- **Clock skew**: `_sseUpdatedAt` uses `Date.now()` (client clock); not an issue since comparisons are relative (elapsed time)

## Implementation Notes

### Files Modified

| File | Change |
|------|--------|
| `control-plane-api/ui/src/scripts/ui/lablet-modals.js` | Store import + HTTP 201 upsert |
| `control-plane-api/ui/src/scripts/app/slices/sessionsSlice.js` | `mergeAll` reducer, `_sseUpdatedAt` stamping |
| `control-plane-api/ui/src/scripts/components/pages/SessionsPageV2.js` | 500ms → 3000ms deferred reload |
| `control-plane-api/ui/src/scripts/app/sse/sseAdapter.js` | Timeslot + score field name fixes |
| `control-plane-api/ui/src/scripts/app/sse/eventMap.js` | Dead entries commented out |
| `control-plane-api/application/events/domain/lablet_session_sse_handlers.py` | Enriched created payload |

### Testing

- All 1133 existing tests pass (no regressions)
- Manual verification: Create session → status transitions appear in real-time without Refresh

## Related Documents

- [Real-Time Updates Architecture](../realtime-updates.md)
- [ADR-013: SSE Protocol Improvements](./ADR-013-sse-protocol-improvements.md)
- [LabletSession Lifecycle Flow](../lablet-session-lifecycle-flow.md)
