# Sprint H: TimeslotManager — Resource Scheduler Timeslot Gating & Visibility

| Attribute | Value |
|-----------|-------|
| **Status** | Draft |
| **Created** | 2026-03-12 |
| **Service** | `src/resource-scheduler/` |
| **Parent** | `docs/implementation/ADR-034-next-steps.md` |
| **Depends On** | Existing SchedulerHostedService, CleanupHostedService, CPA imminent-deadlines endpoint |

---

## 1. Problem Statement

The resource-scheduler currently treats **all PENDING sessions equally** — the `SchedulerHostedService` watches for PENDING sessions and schedules them to workers immediately, regardless of when their timeslot actually begins. This creates two problems:

1. **Premature scheduling**: Sessions with `timeslot_start` hours or days in the future consume worker capacity unnecessarily early, blocking sessions that need to start sooner.
2. **No expired-timeslot enforcement**: PENDING sessions whose `timeslot_start` has already passed (e.g., user created a session but no worker was available in time) remain PENDING indefinitely instead of being expired.

### What Already Exists

| Component | Service | Purpose |
|-----------|---------|---------|
| `TimeslotWatcherService` | lablet-controller | Handles **SCHEDULED→INSTANTIATING** (approaching start) and **RUNNING→STOPPING** (past end) transitions. Already fully implemented. |
| `SchedulerHostedService` | resource-scheduler | Handles **PENDING→SCHEDULED** placement via PlacementEngine. Has NO timeslot awareness. |
| `CleanupHostedService` | resource-scheduler | Periodic cleanup of terminated workers. Uses leader election pattern. |
| `get_sessions_with_imminent_deadlines()` | CPA (lcm_core client) | Server-side MongoDB query returning `approaching_start` and `past_end` sessions. |
| `expire_session()` | CPA (lcm_core client) | Expires a session due to timeslot exhaustion. |
| `timeslot_lead_time_minutes` | resource-scheduler Settings | Already configured (default 35) but **unused** in resource-scheduler code. |

### The Gap

The **PENDING → SCHEDULED** transition has no timeslot gating. The TimeslotManager fills this gap:

```
Session Created (timeslot_start = T+4h)
  → PENDING (should NOT be scheduled yet — timeslot too far out)
  → [TimeslotManager detects T-35min approaching]
  → SchedulerHostedService places it → SCHEDULED
  → [TimeslotWatcherService detects approaching start]
  → INSTANTIATING → pipeline runs → RUNNING

Session Created (timeslot_start = T-1h, missed)
  → PENDING (should be EXPIRED — timeslot already passed)
  → [TimeslotManager detects past timeslot → calls expire_session()]
  → EXPIRED
```

---

## 2. Architecture Decision

### AD-TIMESLOT-MGR-001: Dual-Strategy Timeslot Management

**Decision:** Implement timeslot management as TWO complementary changes rather than a single new service:

1. **Enhance `SchedulerHostedService.list_resources()`** — Filter out PENDING sessions whose `timeslot_start` is outside the scheduling window. This is the simplest, most cohesive approach since the scheduler already lists and processes PENDING sessions.

2. **Add `TimeslotManagerHostedService`** — Separate leader-elected background service that handles the *proactive* side: (a) detecting PENDING sessions approaching their timeslot and writing etcd trigger keys for instant watch-based scheduling, and (b) expiring PENDING sessions whose timeslot has already passed.

**Rationale:**

- Separation of concerns: scheduling placement (SchedulerHostedService) vs. timeslot lifecycle enforcement (TimeslotManagerHostedService)
- The SchedulerHostedService poll cycle runs every 30s — timeslot detection needs its own cadence (configurable, default 60s)
- Follows the existing pattern: SchedulerHostedService + CleanupHostedService are independent services with distinct responsibilities
- TimeslotManagerHostedService follows the exact same pattern as CleanupHostedService (leader election, asyncio loop, DI factory)

---

## 3. Implementation Plan

### H1: TimeslotManagerHostedService

**File:** `src/resource-scheduler/application/hosted_services/timeslot_manager_hosted_service.py` (new)

**Pattern Reference:** `cleanup_hosted_service.py` (233 lines — leader election, asyncio loops, stats, DI factory)

**Responsibilities:**

1. **Approaching timeslot activation** — Query CPA for PENDING sessions within `timeslot_lead_time_minutes` window. For each, write etcd trigger key `/lcm/sessions/{session_id}/state` with value `PENDING` to wake up `SchedulerHostedService.on_watch_event()`.
2. **Expired timeslot enforcement** — Query CPA for PENDING sessions with `timeslot_start < now - grace_period`. Call `expire_session()` via CPA client for each.
3. **Admin stats** — Expose scan count, triggers, expirations for `/api/admin/info`.

**Key Design Points:**

- Uses `ControlPlaneApiClient.get_sessions_with_imminent_deadlines()` — the endpoint already exists in CPA and returns both `approaching_start` and `past_end` lists.
- Writes etcd trigger keys to leverage the existing watch-based SchedulerHostedService activation (the same approach TimeslotWatcherService uses in lablet-controller).
- Tracks `_triggered_session_ids: set[str]` to avoid redundant etcd writes (same dedup pattern as lablet-controller's `TimeslotWatcherService`).
- Leader-elected via etcd (only one instance runs timeslot management).

**Constructor signature:**

```python
def __init__(
    self,
    api_client: ControlPlaneApiClient,
    etcd_client: EtcdClient,
    settings: Settings,
) -> None:
```

**Main loop pseudocode:**

```python
async def _scan_loop(self):
    while self._started and self._is_leader:
        # 1. Query CPA for imminent deadlines
        result = await self._api.get_sessions_with_imminent_deadlines(
            boot_window_minutes=self._settings.timeslot_lead_time_minutes,
        )

        # 2. Trigger scheduling for approaching PENDING sessions
        for session in result["approaching_start"]:
            if session["status"] == "PENDING" and session["id"] not in self._triggered:
                await self._trigger_scheduling(session["id"])
                self._triggered.add(session["id"])

        # 3. Expire PENDING sessions past their timeslot
        for session in result["past_end"]:
            if session["status"] == "PENDING":
                await self._api.expire_session(session["id"], reason="timeslot_missed")
                self._expirations += 1

        # 4. Prune triggered set (remove sessions no longer in response)
        # 5. Sleep for interval
```

**DI Registration pattern** (same as CleanupHostedService):

```python
@staticmethod
def configure(services, settings: Settings) -> None:
    def factory(sp):
        return TimeslotManagerHostedService(
            api_client=sp.get_required_service(ControlPlaneApiClient),
            etcd_client=sp.get_required_service(EtcdClient),
            settings=settings,
        )
    services.add_singleton(TimeslotManagerHostedService, implementation_factory=factory)
```

**Wire into main.py** — follow the exact CleanupHostedService pattern:

```python
# In create_app():
TimeslotManagerHostedService.configure(builder.services, settings)

def timeslot_factory(sp) -> HostedService:
    return sp.get_required_service(TimeslotManagerHostedService)

builder.services.add_singleton(
    HostedService,
    implementation_factory=timeslot_factory,
)
```

### H2: Timeslot-Aware Filtering in SchedulerHostedService

**File:** `src/resource-scheduler/application/hosted_services/scheduler_hosted_service.py` (modify)

**Changes to `list_resources()`:**

After fetching PENDING sessions from CPA, add timeslot filtering:

```python
async def list_resources(self) -> list[LabletSessionReadModel]:
    sessions_data = await self._api.get_lablet_sessions(status=LabletSessionStatus.PENDING)
    sessions = [LabletSessionReadModel.from_dict(data) for data in sessions_data]

    # NEW: Timeslot-aware filtering
    now = datetime.now(timezone.utc)
    lead_time = timedelta(minutes=self._settings.timeslot_lead_time_minutes)
    eligible = []
    for session in sessions:
        if session.timeslot_start is None:
            # No timeslot → always eligible (immediate scheduling)
            eligible.append(session)
        elif session.timeslot_start <= now + lead_time:
            # Within scheduling window → eligible
            eligible.append(session)
        else:
            # Too far in the future → skip for now
            logger.debug(f"Skipping session {session.id}: timeslot_start {session.timeslot_start} is outside lead time window")

    sessions = eligible
    # ... rest of existing code (cache refresh, etc.)
```

**Also update `on_watch_event()`** to accept timeslot trigger keys:

The TimeslotManagerHostedService writes `/lcm/sessions/{id}/state` with value `PENDING` to trigger the watch. The existing `on_watch_event()` already handles this — it checks for `PUT` events with `PENDING` value. **No change needed** for watch event handling.

**Priority sorting** (optional enhancement):

Sort eligible sessions by timeslot proximity so closest-starting sessions get scheduled first:

```python
eligible.sort(key=lambda s: s.timeslot_start or datetime.min.replace(tzinfo=timezone.utc))
```

### H3: Settings

**File:** `src/resource-scheduler/application/settings.py` (modify)

Add to the "Scheduling" section:

```python
# ============================================================================
# Timeslot Management
# ============================================================================
timeslot_manager_enabled: bool = True
timeslot_manager_interval_seconds: int = 60  # Scan every 60 seconds
timeslot_expiry_grace_minutes: int = 5  # Grace period before expiring missed timeslots
```

**Environment variables:**

- `TIMESLOT_MANAGER_ENABLED` — Enable/disable the TimeslotManagerHostedService (default: `true`)
- `TIMESLOT_MANAGER_INTERVAL_SECONDS` — Scan interval (default: `60`)
- `TIMESLOT_EXPIRY_GRACE_MINUTES` — Minutes past `timeslot_start` before a PENDING session is expired (default: `5`)

Note: `timeslot_lead_time_minutes` (default 35) already exists and controls the scheduling window.

### H4: Admin Query Endpoints

**File:** `src/resource-scheduler/api/controllers/admin_controller.py` (modify)

Add timeslot visibility endpoints to the existing admin controller:

```python
@router.get("/admin/timeslots/status")
async def get_timeslot_status(request: Request) -> dict:
    """Get timeslot management status and statistics.

    Returns TimeslotManagerHostedService stats:
    - Running state, scan count, triggers, expirations
    - Last scan timestamp, last error
    - Currently tracked approaching sessions
    """
    timeslot_mgr = request.app.state.services.get_required_service(TimeslotManagerHostedService)
    return timeslot_mgr.stats
```

**Optional (defer if not needed):**

- `GET /api/admin/timeslots/approaching` — List PENDING sessions within scheduling window
- `GET /api/admin/timeslots/landscape` — 24h histogram of upcoming timeslot_start times

These can be proxied from CPA via `get_sessions_with_imminent_deadlines()` or added as new CPA query endpoints if needed.

### H5: Update `__init__.py` and Export

**File:** `src/resource-scheduler/application/hosted_services/__init__.py` (modify)

```python
from application.hosted_services.cleanup_hosted_service import CleanupHostedService
from application.hosted_services.scheduler_hosted_service import SchedulerHostedService
from application.hosted_services.timeslot_manager_hosted_service import TimeslotManagerHostedService

__all__ = ["CleanupHostedService", "SchedulerHostedService", "TimeslotManagerHostedService"]
```

### H6: Tests

**File:** `src/resource-scheduler/tests/test_timeslot_manager_hosted_service.py` (new)

**Test categories:**

| Category | Tests | Count |
|----------|-------|-------|
| Lifecycle | start/stop, disabled via settings, leader election | 3 |
| Approaching detection | Triggers scheduling for PENDING sessions in window | 3 |
| Expired detection | Expires PENDING sessions past timeslot + grace | 3 |
| Deduplication | Doesn't re-trigger already-triggered sessions | 2 |
| Pruning | Removes from tracked set when session leaves response | 2 |
| Error handling | CPA unavailable, etcd write failure, expire failure | 3 |
| Stats | Counters increment correctly, stats dict format | 2 |
| **Total** | | **~18** |

**File:** `src/resource-scheduler/tests/test_scheduler_hosted_service.py` (modify existing)

Add tests for timeslot-aware filtering in `list_resources()`:

| Test | Description |
|------|-------------|
| `test_list_resources_filters_future_sessions` | Sessions with timeslot > lead time are excluded |
| `test_list_resources_includes_approaching_sessions` | Sessions within lead time are included |
| `test_list_resources_includes_no_timeslot_sessions` | Sessions without timeslot are always included |
| `test_list_resources_sorts_by_timeslot_proximity` | Closest timeslot_start first |
| **Total** | **~4 new tests** |

**Pattern for tests:** Follow existing `test_cleanup_hosted_service.py` patterns — mock `ControlPlaneApiClient`, `EtcdClient`, and `Settings` as constructor arguments.

### H7: Documentation

**File:** `src/resource-scheduler/README.md` (update)

Add section describing the TimeslotManager's role in the scheduling pipeline.

**File:** `src/resource-scheduler/docs/TIMESLOT_MANAGEMENT.md` (new, optional)

Architecture note explaining:

- The three-service timeslot lifecycle (resource-scheduler gate → scheduler placement → lablet-controller enforcement)
- Decision rationale for dual-strategy approach
- Configuration reference

---

## 4. Data Flow Diagram

```
                           PENDING Session Created
                           (timeslot_start = T+4h)
                                    │
                                    ▼
                        ┌──────────────────────┐
                        │ Sits in CPA MongoDB  │
                        │   status = PENDING   │
                        │   timeslot_start = T  │
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
    ┌─────────▼──────────┐  ┌─────▼──────────┐  ┌─────▼──────────┐
    │ TimeslotManager    │  │ Scheduler      │  │ Scheduler      │
    │ (every 60s)        │  │ (poll 30s)     │  │ (watch)        │
    │                    │  │                │  │                │
    │ "Is T within 35m?" │  │ list_resources │  │ on_watch_event │
    │ YES → write etcd   │──│ filters by     │  │ PENDING → run  │
    │ MISSED → expire    │  │ timeslot_lead  │  │                │
    └────────────────────┘  └────────────────┘  └────────────────┘
              │                    │                    │
              │              ┌─────▼──────────┐        │
              │              │ PlacementEngine│◄───────┘
              │              │ schedule()     │
              │              └────────────────┘
              │                    │
              ▼                    ▼
        EXPIRED              SCHEDULED
                                   │
                    ┌──────────────▼──────────────┐
                    │ TimeslotWatcherService      │
                    │ (lablet-controller, 10s)    │
                    │ approaching? → INSTANTIATING│
                    │ past end?    → STOPPING     │
                    └─────────────────────────────┘
```

---

## 5. Checklist — LabletSessionReadModel.timeslot_start

Before implementing H2 (timeslot filtering in SchedulerHostedService), verify that `LabletSessionReadModel` exposes `timeslot_start` and `timeslot_end`:

**File to check:** `src/core/lcm_core/domain/entities/read_models/lablet_session_read_model.py`

If `timeslot_start` is NOT on the read model, add it as part of H2:

```python
timeslot_start: datetime | None = None
timeslot_end: datetime | None = None
```

And update `from_dict()` to parse ISO 8601 strings into datetime objects.

---

## 6. Implementation Order

```
H3 (Settings) ← First: add configuration fields
  │
  ├── H1 (TimeslotManagerHostedService) ← Depends on settings
  │     └── Wire into main.py + __init__.py (H5)
  │
  ├── H2 (SchedulerHostedService filtering) ← Independent of H1
  │     └── Check LabletSessionReadModel.timeslot_start first
  │
  ├── H4 (Admin endpoints) ← Depends on H1 (needs service reference)
  │
  └── H6 (Tests) ← After H1 + H2 are implemented
        └── H7 (Docs) ← Last
```

**Suggested implementation sequence:** H3 → H1 + H5 → H2 → H6 → H4 → H7

---

## 7. Acceptance Criteria

- [ ] `TimeslotManagerHostedService` starts under leader election and scans at configured interval
- [ ] PENDING sessions within `timeslot_lead_time_minutes` get etcd trigger keys written
- [ ] PENDING sessions past `timeslot_start + grace_period` get expired via CPA
- [ ] `SchedulerHostedService.list_resources()` filters out sessions outside timeslot window
- [ ] Sessions without timeslot (`timeslot_start is None`) are always scheduled immediately
- [ ] Settings `TIMESLOT_MANAGER_ENABLED`, `TIMESLOT_MANAGER_INTERVAL_SECONDS`, `TIMESLOT_EXPIRY_GRACE_MINUTES` work correctly
- [ ] Admin endpoint `GET /api/admin/timeslots/status` returns operational stats
- [ ] ≥18 new unit tests pass for TimeslotManagerHostedService
- [ ] ≥4 new unit tests pass for timeslot-aware list_resources()
- [ ] All existing resource-scheduler tests still pass
- [ ] `make lint` passes
- [ ] README updated with TimeslotManager description

---

## 8. Reference Files

| File | Purpose | Lines |
|------|---------|-------|
| `resource-scheduler/application/hosted_services/cleanup_hosted_service.py` | **Primary pattern** — leader election, asyncio loop, DI factory | 233 |
| `resource-scheduler/application/hosted_services/scheduler_hosted_service.py` | Where H2 filtering goes — `list_resources()`, `on_watch_event()` | 528 |
| `resource-scheduler/application/settings.py` | Where H3 settings go | 126 |
| `resource-scheduler/main.py` | Where DI registration goes (H5) | 230 |
| `resource-scheduler/api/controllers/admin_controller.py` | Where H4 admin endpoints go | 115 |
| `lablet-controller/application/services/timeslot_watcher_service.py` | Pattern reference for dedup + etcd triggers | 228 |
| `core/lcm_core/integration/clients/control_plane_client.py` | `get_sessions_with_imminent_deadlines()`, `expire_session()` | 1714 |
| `core/lcm_core/domain/entities/read_models/lablet_session_read_model.py` | Check for `timeslot_start` field (H2 prerequisite) | — |

---

## 9. Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| TimeslotManager writes etcd key but SchedulerHostedService filters it out as "too early" | Both use same `timeslot_lead_time_minutes` setting — if TimeslotManager triggers it, the scheduler's filter will include it |
| Session expired by TimeslotManager while user is looking at it | Grace period (`timeslot_expiry_grace_minutes`) prevents premature expiry. Default 5 minutes past timeslot_start. |
| Duplicate processing between TimeslotManager and lablet-controller's TimeslotWatcherService | No overlap: resource-scheduler handles PENDING sessions, lablet-controller handles SCHEDULED/RUNNING sessions. Different status filtering. |
| `LabletSessionReadModel` missing `timeslot_start` field | Checklist item §5 — verify before H2 implementation |
| CPA `get_sessions_with_imminent_deadlines()` returns sessions in statuses other than PENDING | Filter by `session["status"] == "PENDING"` in TimeslotManager (approaching_start may include SCHEDULED sessions meant for lablet-controller) |
| Leader election race with SchedulerHostedService | Separate election keys: `/lcm/timeslot-manager/leader` vs `/lcm/resource-scheduler/leader`. Both can be leader simultaneously (different concerns). |
