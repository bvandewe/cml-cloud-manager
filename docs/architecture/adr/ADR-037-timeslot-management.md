# ADR-037: Timeslot Management Service

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-11 |
| **Deciders** | B. Vandeweyer |
| **Related ADRs** | [ADR-006](ADR-006-resource-scheduler-ha-coordination.md), [ADR-020](ADR-020-session-entity-model.md), [ADR-036](ADR-036-resource-management-abstraction-layer.md) |
| **Sprint** | H (resource-scheduler) |

## 1. Context

LabletSessions support **timeslot-based scheduling** — each session can specify a `timeslot_start` and `timeslot_end` that define when the session should be active. Two gaps existed in the scheduling pipeline:

1. **Premature scheduling**: The SchedulerHostedService's reconciliation loop processes all PENDING sessions indiscriminately, without considering whether a session's timeslot is approaching. Sessions with timeslots far in the future would be scheduled immediately, wasting worker resources.

2. **Missed timeslots**: If a PENDING session's `timeslot_start` passes without being scheduled (e.g., due to capacity constraints), the session remains PENDING indefinitely. There was no mechanism to expire these stale sessions.

The existing TimeslotWatcherService in lablet-controller handles SCHEDULED→INSTANTIATING and RUNNING→STOPPING transitions but does **not** manage the PENDING phase. This created a gap where timeslot awareness was missing for pre-scheduling decisions.

## 2. Decision

Introduce a **TimeslotManagerHostedService** in the resource-scheduler as a separate, leader-elected background service that:

1. **Gates scheduling** by writing etcd trigger keys only for PENDING sessions whose `timeslot_start` is within a configurable look-ahead window (`timeslot_lead_time_minutes`, default: 35 min).
2. **Expires missed timeslots** by calling CPA to expire PENDING sessions whose `timeslot_start + grace_period` has passed.
3. **Provides admin visibility** via three query endpoints for operators to monitor timeslot distribution.

### Key Design Choices

#### Separate Hosted Service (not part of SchedulerHostedService)

The TimeslotManager is implemented as its own hosted service rather than extending the SchedulerHostedService because:

- **Different cadence**: Scheduling reconciliation runs on a 30s interval; timeslot scanning runs every 60s. Coupling them would force a single interval or add complexity for dual-rate logic.
- **Different concerns**: The scheduler handles placement decisions (filter → score → select). The TimeslotManager handles temporal gating and expiry enforcement — orthogonal responsibilities.
- **Independent leader election**: Both services use etcd leader election but with separate keys (`/lcm/resource-scheduler/leader` vs `/lcm/timeslot-manager/leader`). This means both can be leader on the same instance simultaneously, which is the desired behavior (same instance handles both scheduling and timeslot management).
- **Independent failure modes**: A crash in timeslot scanning should not disrupt the main scheduling loop, and vice versa.

#### etcd Trigger Keys for Scheduling Activation

When a session's timeslot is approaching, the TimeslotManager writes an etcd key (`/lcm/sessions/{session_id}/state = "PENDING"`) with a 120s TTL lease. This wakes the SchedulerHostedService's etcd watch handler, which processes the session for placement. This approach:

- Reuses the existing etcd watch infrastructure — no new watch patterns needed
- Provides natural deduplication via the TTL lease (key auto-cleans up)
- Follows the same pattern as TimeslotWatcherService in lablet-controller

#### CPA-Side Filtering (Server-Side MongoDB)

The TimeslotManager queries CPA's `get_sessions_with_imminent_deadlines()` endpoint, which performs server-side MongoDB filtering using indexed queries. This avoids fetching all sessions to the resource-scheduler and filtering locally.

#### Deduplication Sets

The service maintains in-memory sets (`_triggered_session_ids`, `_expired_session_ids`) to avoid redundant etcd writes or CPA expiry calls on subsequent scans. These sets are pruned when sessions disappear from the CPA response (i.e., they've been scheduled/expired/terminated).

## 3. Configuration

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `timeslot_manager_enabled` | `TIMESLOT_MANAGER_ENABLED` | `true` | Enable/disable the service |
| `timeslot_manager_interval_seconds` | `TIMESLOT_MANAGER_INTERVAL_SECONDS` | `60` | Scan interval in seconds |
| `timeslot_expiry_grace_minutes` | `TIMESLOT_EXPIRY_GRACE_MINUTES` | `5` | Grace period before expiring missed timeslots |
| `timeslot_lead_time_minutes` | `TIMESLOT_LEAD_TIME_MINUTES` | `35` | Look-ahead window for approaching sessions |

## 4. Admin Endpoints (Sprint H3)

Three read-only endpoints on the resource-scheduler's AdminController:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/timeslots/status` | TimeslotManager statistics (scan count, triggers, expirations, tracking sets) |
| `GET` | `/api/admin/timeslots/approaching` | Live-queries CPA for PENDING sessions within the lead time window |
| `GET` | `/api/admin/timeslots/expired` | Live-queries CPA for PENDING sessions past their timeslot |
| `GET` | `/api/admin/timeslots/landscape` | 24-hour histogram of PENDING/SCHEDULED sessions bucketed by timeslot_start hour |

## 5. Lifecycle & Architecture

```
TimeslotManagerHostedService
├── start_async()
│   └── _leader_loop()                    # etcd leader election (separate key)
│       └── _scan_loop()                  # Periodic scan when leader
│           └── _run_scan()               # Single scan cycle
│               ├── CPA.get_sessions_with_imminent_deadlines()
│               ├── _trigger_scheduling()  # etcd PUT with TTL lease
│               ├── _expire_session()      # CPA.expire_session()
│               └── Prune dedup sets
├── stop_async()
│   └── Cancel tasks, log stats
├── stats (property)                       # For admin endpoints
├── get_approaching_sessions()             # Live CPA query
├── get_expired_sessions()                 # Live CPA query
└── configure() (classmethod)             # DI factory registration
```

### Gap Filled

```
                PENDING                    SCHEDULED              RUNNING
    ┌─────────────────────────┐    ┌──────────────────────┐    ┌──────────────┐
    │   TimeslotManager       │    │ SchedulerHostedSvc   │    │ TimeslotWatch│
    │   (resource-scheduler)  │───>│ (resource-scheduler)  │───>│ (lablet-ctrl)│
    │                         │    │                       │    │              │
    │ • Gate premature sched  │    │ • Placement decisions │    │ • Instantiate│
    │ • Expire missed slots   │    │ • Worker assignment   │    │ • Stop at end│
    └─────────────────────────┘    └───────────────────────┘    └──────────────┘
```

## 6. Consequences

### Positive

- PENDING sessions with future timeslots are no longer scheduled prematurely
- Missed timeslots are automatically expired, preventing indefinite PENDING state
- Operators have full visibility into timeslot distribution via admin endpoints
- Independent lifecycle allows tuning scan interval without affecting placement decisions

### Negative

- Additional etcd leader election key — one more lease to maintain
- In-memory dedup sets are lost on service restart (acceptable — redundant triggers are idempotent)
- 60s scan interval means up to 60s delay before detecting an approaching timeslot (acceptable given the 35-minute lead time)

### Risks

- If CPA's `get_sessions_with_imminent_deadlines()` is slow or unavailable, scans will fail silently (mitigated by error logging and `last_error` stat)
- Dedup sets grow with active session count (mitigated by pruning on each scan)

## 7. Implementation Summary

| Task | Description | Status |
|------|-------------|--------|
| H1 | TimeslotManagerHostedService — leader-elected background service | ✅ |
| H2 | Timeslot-aware filtering in SchedulerHostedService | ✅ |
| H3 | Admin query endpoints (approaching, expired, landscape) | ✅ |
| H4 | Settings (TIMESLOT_MANAGER_ENABLED, interval, grace) | ✅ |
| H5 | Unit tests for all components | ✅ |
| H6 | Documentation (this ADR + README update) | ✅ |
