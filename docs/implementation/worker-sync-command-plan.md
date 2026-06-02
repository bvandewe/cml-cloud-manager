# Worker Synchronization Command — Implementation Plan

**Date**: 2026-06-01
**Status**: DRAFT
**ADR**: AD-043 (pending approval)
**Relates to**: AD-015 (desired_status etcd projection), AD-017 (on-demand refresh), AD-018 (polling config), AD-041 (lab discovery etcd trigger)

---

## Problem Statement

The current "Refresh" button in the Worker Details modal only performs a **UI data re-fetch** (GET request) — it does NOT trigger actual reconciliation. Meanwhile, the existing `RequestWorkerRefreshCommand` sets a `refresh_requested_at` flag that is only detected on the **next reconciliation polling cycle** (up to 30–60s delay), and only works for `RUNNING` workers.

### Concrete Failure Scenario

A worker was restarted externally (e.g., via AWS Console) and now has:

- `status: "running"` (stale — may have been stopped and restarted)
- `desired_status: "stopped"` (from a previous stop request)
- `service_status: "available"` (stale — CML may not be ready yet)

Lab records linked to this worker remain in stale state. The reconciler may not detect the mismatch quickly because:

1. The refresh flag requires polling detection (not watch-based)
2. STOPPED workers are excluded from `list_resources()` (terminal status filter)
3. If etcd `state` key already says "running", no watch event fires (no delta)

A **synchronization command** should force immediate re-evaluation of the worker's actual EC2 + CML state and trigger full reconciliation regardless of cached state.

---

## Goals

1. **Reactive sync trigger** — User action immediately triggers reconciliation via etcd watch (< 1s latency)
2. **Status-agnostic** — Works for ANY worker status, not just RUNNING
3. **Full state re-read** — Forces EC2 + CML state refresh, not just a data fetch
4. **Lab record recovery** — Triggers downstream lab record state reconciliation
5. **UI clarity** — "Refresh" becomes a view refresh; "Sync" becomes the reconciliation trigger

---

## Approach Comparison

### Option A: Extend Existing `refresh_requested_at` with etcd Projection (Minimal Change)

Add an etcd projector for `WorkerDataRefreshRequestedDomainEvent` to publish `/workers/{id}/sync_requested`.

| Aspect | Detail |
|--------|--------|
| **Mechanism** | Domain event → etcd projector → watch fires → reconciliation |
| **New Code** | ~1 new etcd key constant, ~1 projector handler, ~10 lines in reconciler |
| **Trigger Latency** | ~500ms (etcd watch debounce) |
| **Status Constraint** | Still limited to RUNNING (existing command guard) |

**Pros:**

- Minimal code change; reuses existing `request_refresh()` domain method
- No new domain event needed
- Leverages existing `refresh_requested_at` clearing mechanism

**Cons:**

- Still limited to RUNNING workers (the guard is in the command handler)
- Semantically conflates "refresh data" with "reconcile state"
- Doesn't address lab record recovery
- The `refresh_requested_at` flag is cleared by `UpdateWorkerCmlDataCommand` — if CML is unreachable, the flag may never clear

---

### Option B: New `SyncWorkerCommand` + Dedicated etcd Key `/workers/{id}/sync` (Recommended)

Create a purpose-built synchronization mechanism with its own domain event, etcd projection, and reconciler handling.

| Aspect | Detail |
|--------|--------|
| **Mechanism** | New command → domain event → etcd projector → `/workers/{id}/sync` → watch fires → full reconciliation |
| **New Code** | 1 command+handler, 1 domain event, 1 etcd projector, 1 etcd store method, reconciler updates |
| **Trigger Latency** | ~500ms (etcd watch debounce) |
| **Status Constraint** | None — works for any non-terminal status |

**Pros:**

- Clean separation: "refresh view" ≠ "reconcile resource"
- Status-agnostic: works for RUNNING, STOPPED, STOPPING, STARTING, etc.
- Can carry metadata (reason, scope, requested_by) for observability
- etcd key can include sync directives (e.g., `{"scope": "full", "include_labs": true}`)
- Follows established pattern: AD-016 (license), AD-041 (discover_labs)
- Clear lifecycle: write key → watch fires → reconcile → clear key
- Can trigger lab record reconciliation as a downstream effect

**Cons:**

- More code (but follows established patterns exactly)
- Need to decide what happens for terminal statuses (TERMINATED, FAILED)

---

### Option C: Touch/Bump `desired_state` etcd Key Without Changing Value

Write the current `desired_status` value back to etcd to force a watch event.

| Aspect | Detail |
|--------|--------|
| **Mechanism** | Re-write same value to `/workers/{id}/desired_state` → watch fires → reconciliation |
| **Trigger Latency** | ~500ms |
| **Status Constraint** | None |

**Pros:**

- Zero new keys or events
- Works immediately with existing watch infrastructure

**Cons:**

- Semantically misleading (desired_state didn't actually change)
- No audit trail (can't distinguish "user requested sync" from "spec change")
- Reconciler can't distinguish "sync request" from normal flow
- No way to carry metadata (scope, reason, include_labs)
- May cause unintended side effects if reconciler treats desired_state changes specially
- Violates event sourcing principles (no meaningful domain event)

---

## Recommendation: Option B — `SyncWorkerCommand` + `/workers/{id}/sync`

This follows the same pattern as:

- **AD-016** (License): `/workers/{id}/license` — write pending operation → watch → reconcile → clear
- **AD-041** (Lab Discovery): `/workers/{id}/discover_labs` — write trigger → watch → discover → clear

The pattern is proven, observable, and cleanly separates concerns.

---

## Detailed Design

### 1. etcd Key Structure

```
/lcm/workers/{worker_id}/sync
```

**Payload** (JSON):

```json
{
  "requested_at": "2026-06-01T14:30:00Z",
  "requested_by": "user@example.com",
  "scope": "full",
  "reason": "manual_sync",
  "include_labs": true
}
```

**Lifecycle**: CPA writes on command → worker-controller reads on watch → reconciles → CPA clears via internal API

### 2. Domain Layer (control-plane-api)

#### New Domain Event: `CMLWorkerSyncRequestedDomainEvent`

**File**: `src/control-plane-api/domain/events/cml_worker.py` (append)

```python
@dataclass(frozen=True)
class CMLWorkerSyncRequestedDomainEvent(DomainEvent):
    """Emitted when a full synchronization is requested for a worker."""
    worker_id: str
    requested_at: str
    requested_by: str
    scope: str = "full"        # "full" | "ec2_only" | "cml_only"
    include_labs: bool = True  # Whether to also trigger lab record reconciliation
    reason: str = "manual"     # "manual" | "stale_state_detected" | "startup_recovery"
```

#### Aggregate Method: `CMLWorker.request_sync()`

**File**: `src/control-plane-api/domain/entities/cml_worker.py`

```python
def request_sync(self, requested_by: str, scope: str = "full", include_labs: bool = True, reason: str = "manual") -> None:
    """Request full state synchronization for this worker.

    Unlike refresh (data collection only), sync triggers full reconciliation
    including desired_status vs actual_status alignment and lab record recovery.

    Args:
        requested_by: Identity of requester (email or "system")
        scope: Sync scope - "full", "ec2_only", "cml_only"
        include_labs: Whether to trigger lab record reconciliation downstream
        reason: Why sync was requested (for audit trail)
    """
    # Guard: Cannot sync terminated workers (no resources to reconcile)
    if self.state.status == CMLWorkerStatus.TERMINATED:
        raise InvalidOperationError("Cannot sync a terminated worker")

    self.record_event(CMLWorkerSyncRequestedDomainEvent(
        worker_id=self.id(),
        requested_at=datetime.now(timezone.utc).isoformat(),
        requested_by=requested_by,
        scope=scope,
        include_labs=include_labs,
        reason=reason,
    ))
```

### 3. Application Layer (control-plane-api)

#### New Command: `RequestWorkerSyncCommand`

**File**: `src/control-plane-api/application/commands/worker/request_worker_sync_command.py`

```python
@dataclass
class RequestWorkerSyncCommand(Command[OperationResult[dict]]):
    """Request full synchronization of a worker's state.

    This triggers reactive reconciliation via etcd watch, forcing the
    worker-controller to re-read actual EC2 + CML state and align it
    with desired state. Works for any non-terminal worker status.
    """
    worker_id: str
    region: str
    scope: str = "full"          # "full" | "ec2_only" | "cml_only"
    include_labs: bool = True    # Trigger lab record reconciliation
    reason: str = "manual"       # Audit trail


class RequestWorkerSyncCommandHandler(CommandHandler[RequestWorkerSyncCommand, OperationResult[dict]]):
    def __init__(self, cml_worker_repository: CMLWorkerRepository):
        self.cml_worker_repository = cml_worker_repository

    @instrumented("RequestWorkerSyncCommand")
    async def handle_async(self, request: RequestWorkerSyncCommand, cancellation_token=None) -> OperationResult[dict]:
        worker = await self.cml_worker_repository.get_by_id_async(request.worker_id, cancellation_token)
        if not worker:
            return self.not_found("CMLWorker", f"Worker {request.worker_id} not found")

        if worker.state.status == CMLWorkerStatus.TERMINATED:
            return self.bad_request("Cannot sync a terminated worker — no resources to reconcile")

        worker.request_sync(
            requested_by="user",  # TODO: Extract from auth context
            scope=request.scope,
            include_labs=request.include_labs,
            reason=request.reason,
        )
        await self.cml_worker_repository.update_async(worker, cancellation_token)

        return self.accepted({
            "worker_id": request.worker_id,
            "sync_requested": True,
            "scope": request.scope,
            "include_labs": request.include_labs,
            "message": "Synchronization requested. Worker state will be reconciled immediately.",
        })
```

#### etcd Projector: `CMLWorkerSyncRequestedEtcdProjector`

**File**: `src/control-plane-api/application/events/domain/etcd_state_projector.py` (append)

```python
class CMLWorkerSyncRequestedEtcdProjector(DomainEventHandler[CMLWorkerSyncRequestedDomainEvent]):
    """Projects sync request to etcd for reactive worker-controller reconciliation.

    Pattern: AD-043 — Same as AD-016 (license) and AD-041 (discover_labs).
    Write trigger key → watch fires → reconcile → clear key.
    """
    def __init__(self, etcd_state_store: EtcdStateStore):
        self._etcd = etcd_state_store

    async def handle_async(self, notification: CMLWorkerSyncRequestedDomainEvent, cancellation_token=None) -> None:
        await self._etcd.set_worker_sync(
            worker_id=notification.worker_id,
            scope=notification.scope,
            include_labs=notification.include_labs,
            reason=notification.reason,
            requested_by=notification.requested_by,
            requested_at=notification.requested_at,
        )
        log.info(
            f"Projected worker.sync.requested: {notification.worker_id} "
            f"scope={notification.scope} include_labs={notification.include_labs} "
            f"reason={notification.reason}"
        )
```

### 4. Integration Layer (control-plane-api)

#### EtcdStateStore: New Key + Methods

**File**: `src/control-plane-api/integration/services/etcd_state_store.py`

```python
# New constant (add to class):
WORKER_SYNC_KEY = "/workers/{id}/sync"  # AD-043: Full sync trigger for reactive reconciliation

async def set_worker_sync(
    self,
    worker_id: str,
    scope: str = "full",
    include_labs: bool = True,
    reason: str = "manual",
    requested_by: str = "unknown",
    requested_at: str | None = None,
) -> None:
    """Set a sync trigger for a worker.

    AD-043: Triggers watch-based full reconciliation in worker-controller.
    Worker-controller watches /workers/ prefix and reacts immediately.

    Args:
        worker_id: The CML worker ID to sync
        scope: "full" | "ec2_only" | "cml_only"
        include_labs: Whether to trigger lab record reconciliation
        reason: Audit trail for why sync was requested
        requested_by: Who requested the sync
        requested_at: ISO timestamp (defaults to now)
    """
    key = self.WORKER_SYNC_KEY.format(id=worker_id)
    data = {
        "scope": scope,
        "include_labs": include_labs,
        "reason": reason,
        "requested_by": requested_by,
        "requested_at": requested_at or datetime.now(timezone.utc).isoformat(),
    }
    await self._etcd.put(key, json.dumps(data))
    log.info(f"Set worker {worker_id} sync: scope={scope}, include_labs={include_labs}, reason={reason}")

async def delete_worker_sync(self, worker_id: str) -> bool:
    """Delete the pending sync trigger for a worker.

    Called by worker-controller (via internal API) after reconciliation completes.

    Args:
        worker_id: The CML worker ID

    Returns:
        True if deleted, False if not found
    """
    key = self.WORKER_SYNC_KEY.format(id=worker_id)
    deleted = await self._etcd.delete(key)
    if deleted:
        log.info(f"Deleted worker {worker_id} sync key")
    return deleted
```

### 5. API Layer (control-plane-api)

#### Controller Endpoint

**File**: `src/control-plane-api/api/controllers/workers_controller.py`

```python
@post("/region/{region}/workers/{worker_id}/sync")
async def request_worker_sync(
    self, region: str, worker_id: str, body: dict | None = None
) -> Response:
    """Request full state synchronization for a worker.

    Triggers immediate reconciliation via etcd watch. Unlike refresh (data-only),
    sync forces the worker-controller to re-evaluate actual vs desired state
    and correct any inconsistencies.

    Returns 202 Accepted — reconciliation happens asynchronously.
    """
    scope = (body or {}).get("scope", "full")
    include_labs = (body or {}).get("include_labs", True)
    reason = (body or {}).get("reason", "manual")

    result = await self.mediator.execute_async(
        RequestWorkerSyncCommand(
            worker_id=worker_id,
            region=region,
            scope=scope,
            include_labs=include_labs,
            reason=reason,
        )
    )
    return self.process(result)
```

#### Internal Controller: Clear Sync Key

**File**: `src/control-plane-api/api/controllers/internal_controller.py` (append)

```python
@delete("/workers/{worker_id}/sync")
async def clear_worker_sync(self, worker_id: str) -> Response:
    """Delete the sync etcd key after worker-controller completes reconciliation.

    Called by worker-controller after processing the sync trigger.
    """
    etcd_store = self._get_etcd_state_store()
    deleted = await etcd_store.delete_worker_sync(worker_id)
    logger.info(f"[Internal] Cleared sync key for worker {worker_id}: deleted={deleted}")
    return JSONResponse({"deleted": deleted})
```

### 6. Worker-Controller Reconciler Updates

#### Watch Event Already Covered

The existing `on_watch_event()` already handles `/workers/{id}/sync` because it watches the entire `/workers/` prefix and extracts worker_id from any sub-key:

```python
# Existing code in on_watch_event():
parts = key_stripped.strip("/").split("/")
if len(parts) >= 2 and parts[0] == "workers":
    worker_id = parts[1]
    key_type = parts[2] if len(parts) >= 3 else "unknown"
    logger.info(f"Watch event: {event.type} for worker {worker_id} key={key_type}")
    return worker_id  # Triggers immediate reconciliation
```

When `/workers/{id}/sync` is written, this fires and triggers reconciliation for that worker_id.

#### Enhanced Reconcile Entry Point

**File**: `src/worker-controller/application/hosted_services/worker_reconciler.py`

Add sync detection at the **TOP of `reconcile()`**, before status routing:

```python
async def reconcile(self, worker: CMLWorkerReadModel) -> ReconciliationResult:
    # AD-043: Check for pending sync request (takes priority)
    if worker.sync_requested_at:
        logger.info(f"Worker {worker.id} has pending sync request (scope={worker.sync_scope})")
        return await self._handle_sync_request(worker)

    # ... existing status-based routing ...
```

#### New Method: `_handle_sync_request()`

```python
async def _handle_sync_request(self, worker: CMLWorkerReadModel) -> ReconciliationResult:
    """Handle a sync request — force full state re-read and alignment.

    AD-043: Unlike the on-demand refresh (EC2 + CML data collection only),
    sync performs FULL reconciliation including:
    1. EC2 actual state verification
    2. CML health + data re-read
    3. Status alignment (correct stale status)
    4. Lab record reconciliation trigger (if include_labs=True)
    5. Clear the sync trigger key

    This recovers from stale states like:
    - Worker restarted externally (status=running but EC2 says stopped)
    - desired_status mismatch after crash recovery
    - Lab records stuck in stale state after worker restart
    """
    logger.info(f"Performing sync for worker {worker.id} (scope={worker.sync_scope}, include_labs={worker.sync_include_labs})")

    # Step 1: Verify actual EC2 state
    actual_status = None
    if worker.ec2_instance_id and worker.sync_scope in ("full", "ec2_only"):
        state = await self._ec2.get_instance_state(worker.ec2_instance_id)
        if state:
            actual_status = self._map_ec2_state_to_worker_status(state.state)
            await self._report_ec2_details(worker.id, state)
            logger.info(f"Sync: EC2 actual state for {worker.id}: {state.state} → {actual_status}")

            # If actual EC2 state differs from stored status, correct it
            if actual_status and actual_status != worker.status:
                logger.warning(
                    f"Sync: Status mismatch for {worker.id}: "
                    f"stored={worker.status}, actual={actual_status}. Correcting."
                )
                await self._api.update_worker_status(
                    worker_id=worker.id,
                    status=actual_status,
                )
        else:
            logger.warning(f"Sync: EC2 instance {worker.ec2_instance_id} not found for worker {worker.id}")

    # Step 2: CML health + data (if worker has an IP and scope includes CML)
    if worker.ip_address and worker.sync_scope in ("full", "cml_only"):
        is_healthy, msg = await self._cml.check_health(worker.ip_address)
        if is_healthy:
            # Collect CML data (system_info, labs, nodes)
            await self._collect_and_report_cml_data(worker)
            logger.info(f"Sync: CML data collected for {worker.id}")
        else:
            logger.info(f"Sync: CML not healthy for {worker.id}: {msg}")
            # Report service_status as unavailable if CML is down
            await self._api.update_worker_service_status(
                worker_id=worker.id,
                service_status="unavailable",
            )

    # Step 3: Trigger lab record reconciliation (if requested)
    if worker.sync_include_labs:
        await self._trigger_lab_reconciliation(worker)

    # Step 4: Clear the sync trigger key via CPA internal API
    try:
        await self._api.clear_worker_sync(worker.id)
        logger.info(f"Sync: Cleared sync key for worker {worker.id}")
    except Exception as e:
        logger.warning(f"Sync: Failed to clear sync key for {worker.id}: {e}")

    # Requeue to ensure next reconciliation uses fresh state
    return ReconciliationResult.requeue("Sync completed — re-reconcile with fresh state")
```

#### Lab Record Reconciliation Trigger

```python
async def _trigger_lab_reconciliation(self, worker: CMLWorkerReadModel) -> None:
    """Trigger lab record reconciliation for all labs on this worker.

    After a worker restart/sync, lab records may be stale. This tells
    the lablet-controller to re-evaluate lab states.
    """
    try:
        # Option A: Trigger via CPA internal API (CPA writes lab etcd keys)
        await self._api.trigger_lab_discovery(worker.id)
        logger.info(f"Sync: Triggered lab discovery for worker {worker.id}")
    except Exception as e:
        logger.warning(f"Sync: Failed to trigger lab reconciliation for {worker.id}: {e}")
```

### 7. Worker Read Model Update

**File**: `src/worker-controller/domain/models/` (or wherever `CMLWorkerReadModel` lives)

Add sync-related fields that the CPA API response includes:

```python
@dataclass
class CMLWorkerReadModel:
    # ... existing fields ...
    sync_requested_at: str | None = None
    sync_scope: str = "full"
    sync_include_labs: bool = True
    sync_reason: str = "manual"
```

These are populated from the worker's API response when a sync is pending.

### 8. UI Changes

#### Worker Details Modal — Split "Refresh" into Two Actions

**Current**: Single "Refresh" button in action bar → GET worker data

**New**:

1. **"↻ Refresh" in header** (lightweight) → GET worker data (view refresh only)
2. **"⟳ Sync" in action bar** (heavyweight) → POST `/api/.../sync` (triggers reconciliation)

```javascript
// Header refresh button (view-only)
const headerRefreshBtn = this.$('#refresh-worker-view');
headerRefreshBtn.addEventListener('click', async () => {
    await this.loadWorkerData();
    showToast('View refreshed', 'info');
});

// Action bar sync button (triggers reconciliation)
const syncBtn = this.$('#sync-worker-state');
syncBtn.addEventListener('click', async () => {
    const confirmed = await confirmAction(
        'Sync Worker State',
        'This will trigger full state reconciliation for this worker. ' +
        'The system will re-read actual EC2 and CML state and correct any inconsistencies.'
    );
    if (!confirmed) return;

    const { requestWorkerSync } = await import('../api/workers.js');
    await requestWorkerSync(this.currentRegion, this.currentWorkerId, {
        scope: 'full',
        include_labs: true,
        reason: 'manual',
    });
    showToast('Synchronization requested — state will update shortly', 'success');
});
```

**API function** (`workers.js`):

```javascript
export async function requestWorkerSync(region, workerId, options = {}) {
    const response = await apiRequest(`/api/workers/region/${region}/workers/${workerId}/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            scope: options.scope || 'full',
            include_labs: options.include_labs !== false,
            reason: options.reason || 'manual',
        }),
    });
    return await response.json();
}
```

---

## Implementation Sequence

| # | Task | Service | Effort |
|---|------|---------|--------|
| 1 | Add `CMLWorkerSyncRequestedDomainEvent` | control-plane-api/domain | S |
| 2 | Add `request_sync()` to `CMLWorker` aggregate | control-plane-api/domain | S |
| 3 | Add `WORKER_SYNC_KEY` + `set_worker_sync()` / `delete_worker_sync()` to `EtcdStateStore` | control-plane-api/integration | S |
| 4 | Add `CMLWorkerSyncRequestedEtcdProjector` | control-plane-api/application/events | S |
| 5 | Add `RequestWorkerSyncCommand` + handler | control-plane-api/application/commands | M |
| 6 | Add SSE event handler for sync requested/completed | control-plane-api/application/events | S |
| 7 | Add `/region/{region}/workers/{worker_id}/sync` endpoint | control-plane-api/api | S |
| 8 | Add `DELETE /workers/{worker_id}/sync` to internal controller | control-plane-api/api | S |
| 9 | Add `sync_requested_at` fields to worker API response | control-plane-api/application | S |
| 10 | Add `clear_worker_sync()` to worker-controller's CPA API client | worker-controller/integration | S |
| 11 | Add `_handle_sync_request()` to `WorkerReconciler` | worker-controller/application | M |
| 12 | Add sync fields to `CMLWorkerReadModel` | worker-controller/domain | S |
| 13 | Update reconcile() to check sync flag before status routing | worker-controller/application | S |
| 14 | Split UI "Refresh" → header "Refresh View" + action bar "Sync" | control-plane-api/ui | M |
| 15 | Add `requestWorkerSync()` API function to `workers.js` | control-plane-api/ui | S |
| 16 | Tests: command handler, projector, reconciler sync handling | all services | M |

**Total estimate**: ~16 tasks, mostly Small, a few Medium

---

## Migration & Backward Compatibility

1. **Existing `refresh_requested_at` mechanism**: Keep as-is (still useful for "light refresh" during normal operation). The sync command is a superset — it includes data refresh AND state alignment.

2. **UI "Refresh" button**: Retarget to header as a pure view refresh (no API mutation). This is non-breaking since it was already just a GET.

3. **Worker-controller watch**: Already watches entire `/workers/` prefix — the new `/sync` key is automatically picked up. No watch config changes needed.

4. **Feature flag**: Add `WORKER_SYNC_COMMAND_ENABLED=true` setting for safe rollout (skip sync handling if disabled in reconciler).

---

## Observability

| Signal | Source | Detail |
|--------|--------|--------|
| Domain event | `CMLWorkerSyncRequestedDomainEvent` | Recorded in event store |
| SSE broadcast | `worker.sync.requested` / `worker.sync.completed` | UI gets real-time feedback |
| etcd key | `/lcm/workers/{id}/sync` | Observable via `etcdctl get --prefix /lcm/workers/` |
| Reconciler log | `Performing sync for worker ...` | Structured log with scope/reason |
| OTEL span | `@instrumented("RequestWorkerSyncCommand")` | Distributed trace |
| CloudEvent | `com.lcm.worker.sync.requested` | Integration event for external consumers |

---

## Testing Strategy

### Unit Tests

1. **Command handler**: Validates guards (not_found, terminated worker rejection)
2. **Domain method**: `request_sync()` emits correct domain event
3. **etcd projector**: Writes correct key/payload to etcd mock
4. **Reconciler `_handle_sync_request()`**: Verifies EC2 + CML re-read, status correction, key clearing

### Integration Tests

1. **End-to-end**: POST `/sync` → verify etcd key written → verify reconciler fires
2. **Stale state recovery**: Set up worker with mismatched status/desired_status, trigger sync, verify correction
3. **Lab recovery**: Trigger sync with `include_labs=true`, verify lab discovery triggered

---

## Security Considerations

- **Authorization**: Same auth requirements as existing worker commands (authenticated user with worker management role)
- **Rate limiting**: Consider rate-limiting sync requests (e.g., max 1 per worker per 30s) to prevent abuse
- **Audit trail**: Full traceability via domain event + OTEL span + structured logs

---

## Open Questions

1. **Should sync also re-align `desired_status`?** If EC2 says "running" but `desired_status` says "stopped", should sync:
   - (a) Stop the worker (respect desired_status) ← **Current reconciler behavior**
   - (b) Update desired_status to match actual (user explicitly synced = "accept current state") ← **Needs explicit user choice**
   - **Recommendation**: (a) — sync aligns actual state, then normal reconciliation handles desired_status drift. If user wants to accept current state, they must explicitly change desired_status.

2. **Should the old "Refresh" command (AD-017) be deprecated?** It could remain as a lightweight "collect latest data" without forcing reconciliation. Useful for metrics update without state changes.
   - **Recommendation**: Keep both. "Refresh" = data collection. "Sync" = full reconciliation.

3. **Lab record recovery scope**: Should sync trigger reconciliation for ALL lab records on the worker, or only those in stale state?
   - **Recommendation**: Trigger lab discovery (re-enumerate labs from CML), which will naturally identify stale records.
