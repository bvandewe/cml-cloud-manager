# ADR-041: WebSocket-Based CML Worker Monitoring

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-05-20 |
| **Deciders** | Platform Team |
| **Related ADRs** | [ADR-013](./ADR-013-sse-protocol-improvements.md) (SSE Batching), [ADR-015](./ADR-015-control-plane-api-no-ec2.md) (CPA No External Calls), [ADR-019](./ADR-019-labrecord-independent-aggregate.md) (LabRecord Aggregate) |
| **Knowledge Refs** | AD-WS-MONITOR-001 |

## Context

### Current Monitoring Architecture

The worker-controller monitors active CML workers using a **polling-based** approach:

1. **Metrics Collection Loop** (60s interval): For each RUNNING worker, calls:
   - CloudWatch API (`get_metric_statistics`) for EC2-level CPU/network/disk metrics
   - CML REST API (`GET /api/v0/system_stats`) for system resource utilization
   - CML REST API (`GET /api/v0/system_health`) for compute health
   - CML REST API (`GET /api/v0/licensing`) for license status

2. **Idle Detection** (per-reconciliation cycle, ~30s): Fetches:
   - CML REST API (`GET /api/v0/telemetry/events`) for all raw telemetry events
   - Sends events to control-plane-api for idle evaluation

3. **Data Reporting**: Worker-controller reports collected data to control-plane-api via:
   - `POST /api/internal/workers/{id}/metrics` (EC2 + CML system stats)
   - `POST /api/internal/workers/{id}/cml-data` (system info, health, license)
   - `POST /api/internal/workers/{id}/detect-idle` (raw telemetry events for idle evaluation)

4. **Frontend Delivery**: Control-plane-api broadcasts to the frontend via SSE:
   - `worker.metrics.updated` (batched every 1s per ADR-013)
   - `worker.activity.updated`, `worker.paused`, etc.

### Problem Statement

This polling approach has several limitations:

| Problem | Impact |
|---------|--------|
| **60-second latency** for resource metrics | Dashboard shows stale data; labs starting/stopping go unnoticed for up to a minute |
| **30-second latency** for idle detection | Delayed auto-pause decisions; wasted compute costs |
| **N×4 API calls per cycle** per RUNNING worker | Significant HTTP overhead; each poll creates a new connection |
| **Full telemetry dump** on each idle check | `/api/v0/telemetry/events` returns ALL events (no pagination/filtering); wasteful for repeated checks |
| **No lab-level activity signals** | Only aggregate CPU/memory visible; can't detect individual lab starts/stops in real-time |
| **No node-level state changes** | Node QUEUED → STARTED → BOOTED transitions invisible between polls |

### CML WebSocket Endpoint Discovery

CML servers expose a WebSocket endpoint at `wss://<host>/ws/ui` that their own frontend consumes. This endpoint emits **push-based, real-time events** including:

| Event Type | Data Content | Current Polling Equivalent | WS Frequency |
|------------|-------------|---------------------------|--------------|
| `system_stats` | Full compute stats (CPU load, memory, disk, dominfo) | `GET /api/v0/system_stats` (60s poll) | ~3s interval |
| `lab_stats` | Per-lab node CPU/RAM/disk, link traffic | None (only aggregate available via poll) | ~3s per lab |
| `state_change` | Node/interface lifecycle: QUEUED, STARTED, BOOTED, STOPPED | `GET /api/v0/telemetry/events` (30s poll) | On occurrence |
| `lab_event` | Lab-level state: STARTED, STOPPED, DEFINED | `GET /api/v0/telemetry/events` (30s poll) | On occurrence | On occurrence |

**Key observation** (validated 2026-05-20): The `system_stats` event contains the **exact same data** as `GET /api/v0/system_stats` (CPU, memory, disk, dominfo per compute). The event stream averages **~0.9 msg/s** with `system_stats` every ~3 seconds and `lab_stats` every ~3 seconds per running lab. The `state_change`/`lab_event` events **supersede** the telemetry events endpoint for idle detection purposes — they arrive in real-time vs. polled every 30s.

---

## Decision

### Replace polling-based CML metrics/activity collection with a persistent WebSocket connection per monitored worker

The worker-controller will maintain a WebSocket connection to each RUNNING worker's `wss://<host>/ws/ui` endpoint, replacing:

1. **CML system_stats polling** → Replaced by `system_stats` WebSocket events (~3s interval from CML)
2. **CML telemetry/events polling** → Replaced by `state_change` + `lab_event` WebSocket events (real-time push)
3. **Idle detection telemetry fetch** → Replaced by activity inference from WebSocket events (zero additional API calls)

**CloudWatch polling and CML system_health/licensing REST calls remain unchanged** — these have no WebSocket equivalent.

### Architecture: CmlWebSocketMonitor Service

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Worker Controller                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  WorkerReconciler                                                        │
│  ├── _handle_running()                                                  │
│  │     ├── (existing) Verify EC2 state                                  │
│  │     ├── (existing) Handle on-demand refresh                          │
│  │     ├── (existing) Reconcile license operations                      │
│  │     ├── (NEW) Ensure CmlWebSocketMonitor is connected                │
│  │     └── (MODIFIED) Idle detection uses WS-derived activity data     │
│  │                                                                       │
│  ├── _handle_stopping() / _handle_stopped()                            │
│  │     └── (NEW) Disconnect CmlWebSocketMonitor                         │
│  │                                                                       │
│  └── _run_metrics_collection_loop()                                     │
│        ├── (RETAINED) CloudWatch EC2 metrics (no WS equivalent)         │
│        ├── (REMOVED) CML system_stats poll → replaced by WS             │
│        ├── (RETAINED) CML system_health poll (no WS equivalent)         │
│        ├── (RETAINED) CML licensing poll (no WS equivalent)             │
│        └── (NEW) Report WS-collected metrics to CPA                     │
│                                                                          │
│  CmlWebSocketMonitor  ← NEW SERVICE                                    │
│  ├── Per-worker WebSocket connection lifecycle                          │
│  ├── Event parsing and classification                                   │
│  ├── Metrics aggregation (rate-limit outbound reports)                  │
│  ├── Activity event tracking (replaces telemetry fetch)                 │
│  ├── Auto-reconnect with exponential backoff                            │
│  └── Connection health monitoring                                        │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Event Flow: WebSocket → CPA → SSE → Frontend

```
CML Worker                     Worker Controller              Control Plane API         Frontend
   │                                │                              │                      │
   │─ ws: system_stats ────────────▶│                              │                      │
   │                                │─ report_worker_metrics() ───▶│                      │
   │                                │                              │─ SSE: worker.metrics ─▶│
   │                                │                              │      .updated         │
   │                                │                              │                      │
   │─ ws: state_change(STARTED) ───▶│                              │                      │
   │                                │─ report_worker_activity() ──▶│                      │
   │                                │                              │─ SSE: worker.activity─▶│
   │                                │                              │      .updated         │
   │                                │                              │                      │
   │─ ws: lab_event(state=STARTED)─▶│                              │                      │
   │                                │─ report_worker_activity() ──▶│                      │
   │                                │─ report_lab_state_change() ─▶│                      │
   │                                │                              │─ SSE: worker.lab     ─▶│
   │                                │                              │      .state_change    │
   │                                │                              │                      │
   │─ ws: lab_stats ───────────────▶│                              │                      │
   │                                │─ report_lab_metrics() ──────▶│                      │
   │                                │                              │─ SSE: worker.lab     ─▶│
   │                                │                              │      .stats_updated   │
```

### New SSE Event Types for Frontend

| SSE Event Type | Source | Data Shape | Purpose |
|----------------|--------|------------|---------|
| `worker.lab.state_change` | CML WS `state_change` | `{worker_id, lab_id, element_type, element_id, event, data}` | Real-time node/interface lifecycle |
| `worker.lab.stats_updated` | CML WS `lab_stats` | `{worker_id, lab_id, nodes: {...}, links: {...}}` | Per-lab resource utilization |
| `worker.ws.connected` | WS lifecycle | `{worker_id, connected_at}` | WS connection status indicator |
| `worker.ws.disconnected` | WS lifecycle | `{worker_id, disconnected_at, reason}` | WS connection lost |

**Existing events enhanced** (no breaking changes):

- `worker.metrics.updated` — Now arrives within ~5-10s of CML emitting `system_stats` (was 60s)
- `worker.activity.updated` — Now arrives within milliseconds of lab interaction (was 30s)

### Idle Detection: Event-Driven Approach

**Before (polling)**:

1. Every 30s: Fetch ALL telemetry events from CML REST API
2. Send raw events to CPA for filtering and evaluation
3. CPA determines `last_activity_at` from matching event categories

**After (WebSocket-driven)**:

1. CmlWebSocketMonitor receives `state_change` and `lab_event` in real-time
2. Worker-controller classifies events by activity category (same filter as current):
   - `lab_event` with state `STARTED` | `STOPPED` → **user activity**
   - `state_change` with event `QUEUED` | `STARTED` on `node` element → **user activity**
3. On activity detection → immediately report to CPA via `report_worker_activity(worker_id, activity_events=[...])`
4. CPA updates `last_activity_at` and resets idle timer (existing pipeline Steps 2-4 unchanged)

**Fallback**: If WebSocket disconnects, revert to polling-based telemetry fetch (existing behavior) until reconnection.

---

## Consequences

### Positive

| Benefit | Quantified Impact |
|---------|-------------------|
| **Near-real-time metrics** | 60s → ~3s latency for system stats (validated) |
| **Instant activity detection** | 30s → <1s for node start/stop events |
| **Reduced API load** | Eliminates 2 REST calls per worker per cycle (system_stats + telemetry/events) |
| **Lab-level visibility** | NEW: Per-lab resource usage visible (not just aggregate) |
| **Node lifecycle visibility** | NEW: Individual node state transitions in real-time |
| **More accurate idle detection** | Activity detected instantly → faster auto-pause when truly idle, no false positives from polling gaps |
| **Persistent connection** | Reuses single TCP connection vs. creating new HTTP connections every 60s |

### Negative

| Trade-off | Mitigation |
|-----------|------------|3s latency for system stats (validated)
| **Persistent connection per worker** | Bounded by max_workers (10/region default); negligible memory |
| **Connection management complexity** | Auto-reconnect with exponential backoff; health monitoring; graceful degradation to polling |
| **WebSocket library dependency** | Add `websockets` package (mature, well-maintained, already async) |
| **Token refresh over WS** | Monitor for 401/close events; reconnect with fresh token |
| **CML version dependency** | `/ws/ui` endpoint may vary across CML versions; version check on connect |

### Neutral

- CloudWatch polling unchanged (still 60s; no WS equivalent available)
- CML system_health and licensing REST polls unchanged (infrequent, no WS equivalent)
- CPA idle detection pipeline unchanged (Steps 2-4); only Step 1 (telemetry fetch) replaced with push-based events
- Frontend SSE infrastructure unchanged; only new event types added

---

## Alternatives Considered

### 1. Reduce Polling Interval (10s instead of 60s)

**Rejected**: 6× more REST API calls; increases load on CML workers; still not real-time; doesn't provide lab-level granularity.

### 2. Server-Sent Events from CML (instead of WebSocket)

**Rejected**: CML doesn't expose an SSE endpoint; the existing frontend uses WebSocket exclusively.

### 3. WebSocket only for activity detection, keep polling for metrics

**Rejected**: `system_stats` arrives via WebSocket at the same interval as the CML frontend refreshes (~5-10s), eliminating the need for a separate poll. Using both would create redundant data paths.

### 4. Have CPA connect to CML WebSocket directly

**Rejected**: Violates ADR-015 (CPA shall not make external calls to CML/EC2). Worker-controller owns all external CML communication.

---

## Validation (Completed 2026-05-20)

**Exploration script**: `scripts/explore_cml_ws.py` tested against CML worker at `3.91.22.2` (CML v2.9).

### Confirmed Results

| Question | Answer |
|----------|--------|
| Authentication method | **Message-based**: send `{"token": "<jwt>"}` as first WS message |
| Handshake auth required? | No — handshake always succeeds (101), auth is post-connect |
| Auth timeout | ~10 seconds (CLOSE 3000 if no valid auth) |
| `system_stats` frequency | Every ~3.3 seconds |
| `lab_stats` frequency | Every ~3.3 seconds per running lab |
| Total message rate | ~0.9 msg/s (with 2 running labs, idle nodes) |
| Event types observed (idle) | `system_stats`, `lab_stats` |
| Event types observed (active) | `state_change`, `lab_event` (from user's prior capture) |
| Close code on auth failure | `3000` with reason "Unauthorized" |
| Close behavior on token expiry | TBD (requires 24h test or token manipulation) |
| CML version tested | 2.9.x |

### Remaining Validation (Deferred to Phase 1)

1. **Extended stability test**: 30+ minute connection hold
2. **Token expiry behavior**: What close code/reason when JWT expires mid-session
3. **Minimum CML version**: Test against older CML instances if available

---

## Implementation Notes

See [ADR-041 Implementation Plan](../../implementation/ADR-041-implementation-plan.md) for the detailed, phased implementation plan.

### Key Design Decisions Within This ADR

1. **CmlWebSocketMonitor is a standalone integration service** — not embedded in the reconciler. The reconciler manages its lifecycle (connect/disconnect) but the monitor runs independently.
2. **Activity events are reported immediately** (no batching on the worker-controller side). CPA's existing batching (ADR-013) handles frontend delivery rate-limiting.
3. **Metrics are throttled** in the monitor before reporting to CPA — maximum one `report_worker_metrics()` call per `metrics_report_interval` seconds (configurable, default 10s), regardless of how frequently CML pushes `system_stats`.
4. **Graceful degradation**: If WebSocket is unavailable (CML version too old, network issues, auth failure), fall back to polling seamlessly. The reconciler checks `monitor.is_connected` and uses the polling path if not.
5. **Lab-level events** are forwarded to CPA for LabRecord state updates (existing `lab.status.updated` SSE event) and as new `worker.lab.stats_updated` events.

### Compatibility Matrix

| CML Version | `/ws/ui` Available | Behavior |
|-------------|-------------------|----------|
| < 2.7 (estimated) | ❌ Unknown | Polling fallback (existing behavior) |
| ≥ 2.9 | ✅ Confirmed | WebSocket monitoring active (validated 2026-05-20) |

**Note**: Minimum version may be lower than 2.9 but untested.
