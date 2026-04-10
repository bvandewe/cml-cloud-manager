# SSE & ResourceState Architecture — Comprehensive Research Report

> **Generated**: Research session covering all 5 requested areas.
> **Scope**: Backend (CPA SSE relay + handlers), Core library (`lcm_core`, `lcm_ui`), Frontend application (CPA UI wiring).

---

## Table of Contents

1. [ResourceState Abstract Class & SSE Streaming Role](#1-resourcestate-abstract-class--sse-streaming-role)
2. [CPA's SSE Event Relay & Domain Event Handlers](#2-cpas-sse-event-relay--domain-event-handlers)
3. [Frontend StoreSlice & SSE Client Code](#3-frontend-storeslice--sse-client-code)
4. [Frontend Web Components for Resources](#4-frontend-web-components-for-resources)
5. [SSE Event Type Mapping & Gap Analysis](#5-sse-event-type-mapping--gap-analysis)

---

## 1. ResourceState Abstract Class & SSE Streaming Role

### 1.1 ResourceState Hierarchy (ADR-036 §2.1.4)

```
AggregateState[str]                    ← Neuroglia framework base
  └─ ResourceState                     ← Layer 1 (core/lcm_core/domain/entities/resource.py)
       └─ TimedResourceState           ← Layer 2 (core/lcm_core/domain/entities/timed_resource.py)
            ├─ LabletSessionState      ← Concrete (control-plane-api/domain/)
            ├─ CMLWorkerState          ← Concrete (control-plane-api/domain/)
            └─ LabRecordState          ← Concrete (control-plane-api/domain/)
```

### 1.2 ResourceState (Layer 1) — `core/lcm_core/domain/entities/resource.py` (96 lines)

**Fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `id` | `str` | Unique aggregate identifier |
| `resource_type` | `str` | Polymorphic discriminator (e.g., `"cml_worker"`, `"lablet_session"`) |
| `status` | `str` | Current status — deliberately `str` NOT enum for cross-type polymorphism |
| `desired_status` | `str \| None` | Declarative desired state (reconciliation target) |
| `owner_id` | `str \| None` | Resource owner identifier |
| `state_history` | `list[StateTransition]` | Audit trail of state transitions |
| `pipeline_progress` | `dict \| None` | Multi-step pipeline execution progress |
| `created_at` | `datetime` | Creation timestamp |
| `updated_at` | `datetime` | Last modification timestamp |

**Key Method:**

```python
def _record_transition(self, from_state, to_state, triggered_by, reason=None, metadata=None):
    """Appends a StateTransition dict to state_history."""
```

**SSE Streaming Role:**

- `status` / `desired_status` are the primary fields SSE-streamed to the frontend via `worker.status.updated`, `lablet.session.status.changed`, `lablet.session.desired_status.changed` events.
- `pipeline_progress` is streamed via `lablet.session.pipeline.progress` events.
- `state_history` is rendered by the `<ui-state-history>` web component.

### 1.3 TimedResourceState (Layer 2) — `core/lcm_core/domain/entities/timed_resource.py` (116 lines)

**Additional Fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `timeslot` | `dict \| None` | Time-bounded execution window (start/end/duration) |
| `lifecycle` | `dict \| None` | Managed lifecycle phases (provision/active/teardown) |
| `started_at` | `datetime \| None` | Execution start time |
| `ended_at` | `datetime \| None` | Execution end time |
| `duration_seconds` | `float \| None` | Computed duration |
| `terminated_at` | `datetime \| None` | Forced termination timestamp |

**Key Methods:**

- `get_timeslot()` / `set_timeslot()` — Timeslot VO ↔ dict conversion
- `get_lifecycle()` / `set_lifecycle()` — ManagedLifecycle VO ↔ dict conversion
- `_compute_duration()` — Calculates duration from started_at/ended_at

**SSE Relevance:** `timeslot` feeds the `<ui-timeslot-badge>` component; `lifecycle` feeds `<ui-lifecycle-tracker>`.

---

## 2. CPA's SSE Event Relay & Domain Event Handlers

### 2.1 SSEEventRelay Architecture

**File:** `control-plane-api/application/services/sse_event_relay.py` (392 lines)

```
┌─────────────────────────────────────────────────────────────────┐
│                     SSEEventRelay (Singleton)                    │
│                                                                  │
│  Domain Event Handler                                            │
│    ↓ broadcast_event(type, data, source)                        │
│    ↓                                                             │
│  ┌──────────────────────────────────────┐                       │
│  │  Redis Pub/Sub                       │                       │
│  │  Channel: lablet-cloud-manager:events│                       │
│  │  (multi-instance sync)               │                       │
│  └──────────┬───────────────────────────┘                       │
│             ↓ _handle_redis_message()                            │
│             ↓                                                    │
│  ┌──────────────────────────────────────┐                       │
│  │  _broadcast_local()                  │                       │
│  │  Per-client SSEClientSubscription    │                       │
│  │    ├─ matches_event(type, source)?   │                       │
│  │    └─ asyncio.Queue.put_nowait()     │                       │
│  └──────────────────────────────────────┘                       │
│                                                                  │
│  Event Batching (ADR-013):                                      │
│  - Only "worker.metrics.updated" is batchable                   │
│  - 1s flush interval, max 50 events per batch                   │
│  - Batched suffix: ".batch" (e.g., "worker.metrics.updated.batch")│
└─────────────────────────────────────────────────────────────────┘
```

**Client Subscription:**

- `register_client(worker_ids, event_types)` → returns `(client_id, Queue)`
- `SSEClientSubscription.matches_event(event_type, source)` — filtering by worker_ids AND event_types
- Heartbeat: 30s keep-alive via controller

### 2.2 SSE Endpoint — `control-plane-api/api/controllers/events_controller.py` (273 lines)

**Endpoint:** `GET /api/events/stream?worker_ids=abc,def&event_types=worker.metrics.updated`

**Initial Snapshots on Connect:**

1. `worker.snapshot` — for all active workers
2. `lablet.session.snapshot` — for all active lablet sessions
3. `lablet.definition.snapshot` — for all active lablet definitions

**Special Events:**

| Event | Description |
|-------|-------------|
| `connected` | Sent immediately on connection |
| `heartbeat` | Every 30 seconds |
| `auth.session.expired` | Session expired during stream |
| `system.sse.shutdown` | Server graceful shutdown |

### 2.3 Domain Event Handlers — Complete Catalog

#### 2.3.1 CML Worker Events — `application/events/domain/cml_worker_events.py` (480 lines)

| # | Domain Event | SSE Event Type | Additional |
|---|-------------|----------------|------------|
| 1 | `CMLWorkerCreatedDomainEvent` | `worker.created` | + `worker.snapshot` |
| 2 | `CMLWorkerImportedDomainEvent` | `worker.imported` | + `worker.snapshot` |
| 3 | `CMLWorkerStatusUpdatedDomainEvent` | `worker.status.updated` | + `worker.snapshot` |
| 4 | `CMLWorkerTerminatedDomainEvent` | `worker.terminated` | + `worker.snapshot`, cascade-orphans lab records |
| 5 | `CMLWorkerTelemetryUpdatedDomainEvent` | `worker.metrics.updated` | + `worker.snapshot` |
| 6 | `CMLMetricsUpdatedDomainEvent` | `worker.metrics.updated` | No snapshot (lightweight) |
| 7 | `CMLWorkerEndpointUpdatedDomainEvent` | `worker.endpoint.updated` | + `worker.snapshot` |
| 8 | `EC2InstanceDetailsUpdatedDomainEvent` | `worker.ec2_details.updated` | + `worker.snapshot` |

#### 2.3.2 Lablet Session Events — `application/events/domain/lablet_session_sse_handlers.py` (536 lines)

| # | Domain Event | SSE Event Type |
|---|-------------|----------------|
| 1 | `LabletSessionCreatedDomainEvent` | `lablet.session.created` |
| 2 | `LabletSessionScheduledDomainEvent` | `lablet.session.status.changed` |
| 3 | `LabletSessionInstantiatingDomainEvent` | `lablet.session.status.changed` |
| 4 | `LabletSessionReadyDomainEvent` | `lablet.session.status.changed` |
| 5 | `LabletSessionRunningDomainEvent` | `lablet.session.status.changed` |
| 6 | `LabletSessionCollectingDomainEvent` | `lablet.session.status.changed` |
| 7 | `LabletSessionGradingDomainEvent` | `lablet.session.status.changed` |
| 8 | `ScoreRecordedDomainEvent` | `lablet.session.score.recorded` |
| 9 | `LabletSessionStoppingDomainEvent` | `lablet.session.status.changed` |
| 10 | `LabletSessionStoppedDomainEvent` | `lablet.session.status.changed` |
| 11 | `LabletSessionArchivedDomainEvent` | `lablet.session.status.changed` |
| 12 | `LabletSessionTerminatedDomainEvent` | `lablet.session.terminated` |
| 13 | `PortsReleasedDomainEvent` | `lablet.session.ports.released` |
| 14 | `TimeslotExtendedDomainEvent` | `lablet.session.timeslot.extended` |
| 15 | `InstantiationProgressUpdatedDomainEvent` | `lablet.session.pipeline.progress` |
| 16 | `PipelineProgressUpdatedDomainEvent` | `lablet.session.pipeline.progress` |
| 17 | `DesiredStatusUpdatedDomainEvent` | `lablet.session.desired_status.changed` |

#### 2.3.3 Lab Record Events — `application/events/domain/lab_record_events.py` (523 lines)

| # | Domain Event | SSE Event Type | Notes |
|---|-------------|----------------|-------|
| 1 | `LabSyncCompletedDomainEvent` | `worker.labs.updated` | Legacy — action: created/updated/state_changed |
| 2 | `LabRecordDiscoveredDomainEvent` | `lab.discovered` | Phase 10 |
| 3 | `LabRecordStartedDomainEvent` | `lab.status.updated` | |
| 4 | `LabRecordStoppedDomainEvent` | `lab.status.updated` | |
| 5 | `LabRecordWipedDomainEvent` | `lab.status.updated` | |
| 6 | `LabRecordDeletedDomainEvent` | `lab.status.updated` | |
| 7 | `LabRecordArchivedDomainEvent` | `lab.status.updated` | |
| 8 | `LabRecordClonedDomainEvent` | `lab.cloned` | |
| 9 | `LabRecordTopologyUpdatedDomainEvent` | `lab.topology.updated` | |
| 10 | `LabRecordBoundDomainEvent` | `lab.bound` | |
| 11 | `LabRecordUnboundDomainEvent` | `lab.unbound` | |
| 12 | `LabRecordActionRequestedDomainEvent` | `lab.action.requested` | |
| 13 | `LabRecordActionCompletedDomainEvent` | `lab.action.completed` | |
| 14 | `LabRecordActionFailedDomainEvent` | `lab.action.failed` | |
| 15 | `LabRecordErrorDomainEvent` | `lab.error` | |

---

## 3. Frontend StoreSlice & SSE Client Code

### 3.1 Two-Layer Frontend Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  APPLICATION LAYER (CPA UI: control-plane-api/ui/src/scripts/) │
│                                                                  │
│  app/sse/eventMap.js ─── SSE wire name → EventBus event mapping │
│  app/sse/sseAdapter.js ─ EventBus → store.dispatch() wiring    │
│  app/eventTypes.js ───── Domain event type constants            │
│  app/eventBus.js ──────── EventBus singleton                    │
│  app/store.js ──────────── StateStore with 5 domain slices      │
│  app/slices/ ───────────── workersSlice, sessionsSlice,         │
│                            labRecordsSlice, definitionsSlice,   │
│                            templatesSlice                       │
│  bridge/uiCoreSetup.js ── Injects eventBus+store into ui-core  │
│  bridge/StoreConnectedPage.js ─ Base class for page components  │
└────────────────────┬────────────────────────────────────────────┘
                     │ imports
┌────────────────────▼────────────────────────────────────────────┐
│  LIBRARY LAYER (@neuroglia/ui-core: core/lcm_ui/)              │
│                                                                  │
│  core/SSEClient.ts ──── EventSource wrapper, eventMap routing   │
│  core/EventBus.ts ───── Singleton pub/sub, wildcard, middleware │
│  core/StateStore.ts ─── Slice-based state, middleware, history  │
│  core/BaseComponent.ts ─ Web component base, store connection   │
│  components/*.ts ──────── 15 passive UI web components          │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 SSE Data Flow (end-to-end)

```
Server SSE stream (/api/events/stream)
  ↓ EventSource (browser native)
  ↓
SSEClient (lcm_ui) — applies eventMap: wire name → bus event name
  ↓ eventBus.emit(mappedType, parsedData)
  ↓
EventBus middleware (sseAdapter.js) — preprocesses (e.g., normalizeWorkerSnapshot)
  ↓
sseAdapter._setupStoreUpdates() handlers:
  eventBus.on(WORKER_SNAPSHOT)  → store.dispatch('workers', 'upsertWorker', data)
  eventBus.on(SESSION_CREATED)  → store.dispatch('sessions', 'upsertSession', data)
  eventBus.on(LAB_DISCOVERED)   → store.dispatch('labRecords', 'upsertLabRecord', data)
  ... (50+ event→dispatch mappings)
  ↓
StateStore — runs reducer, updates state, notifies subscribers
  ↓
StoreConnectedPage.connectSlice(sliceName, selector, callback)
  ↓ selector(newState) !== previousValue ?
  ↓
Page callback — updates DOM / sets web component attributes
  ↓
<ui-resource-status>, <ui-pipeline-log>, etc. — re-render
```

### 3.3 SSE Event Map — `app/sse/eventMap.js` (244 lines)

The `sseEventMap` object maps **57 SSE wire names** to `LcmEventTypes` constants:

| Category | Wire Names Mapped | Count |
|----------|-------------------|-------|
| Worker events | `worker.snapshot`, `worker.created`, `worker.imported`, `worker.terminated`, `worker.status.updated`, `worker.metrics.updated`, `worker.activity.updated`, `worker.idle_detection.toggled`, `worker.paused`, `worker.resumed`, `worker.endpoint.updated`, `worker.ec2_details.updated`, `worker.refresh.throttled`, `worker.data.refreshed`, `worker.labs.updated`, `workers.refresh.completed` | 16 |
| License events | `worker.license.registration.started/completed/failed`, `worker.license.deregistered` | 4 |
| Lablet session events | `lablet.session.created/updated/deleted/status.changed/scheduled/instantiating/ready/running/collecting/grading/stopping/stopped/archived/terminated/snapshot/pipeline.progress/desired_status.changed`, `lablet.sessions.refresh.completed` | 18 |
| Lablet instance (compat) | `lablet.instance.created/updated/deleted/status.changed/snapshot`, `lablet.instances.refresh.completed` | 6 |
| Pipeline CloudEvents | `pipeline.step.started/completed/failed.v1`, `pipeline.completed.v1` | 4 |
| Definition events | `lablet.definition.created/updated/activated/deactivated/deleted/snapshot/content_synced/deprecated/sync_requested`, `lablet.definitions.refresh.completed` | 10 |
| Template events | `worker.template.created/updated/deleted` | 3 |
| Lab Record events | `lab.discovered/status.updated/imported/cloned/bound/unbound/topology.updated/snapshot/action.requested/action.completed/action.failed/error`, `lab_records.refresh.completed` | 13 |
| System/Auth | `system.sse.shutdown`, `auth.session.expired` | 2 |
| Ignored | `heartbeat` → `null` | 1 |

**Total: 77 map entries** (including backward-compat aliases)

### 3.4 Store Slices

| Slice Name | File | Normalized State Shape | SSE-Driven Reducers |
|-----------|------|----------------------|---------------------|
| `workers` | `workersSlice.js` (581 lines) | `{ byId, allIds, activeId, timing, loading, errors, lastRefreshedAt }` | `upsertWorker`, `updateMetrics`, `updateStatus`, `removeWorker`, `updateTiming`, `replaceAll` |
| `sessions` | `sessionsSlice.js` (400 lines) | `{ byId, allIds, activeId, activeDetail, loading, errors, lastRefreshedAt, filters }` | `upsertSession`, `removeSession`, `replaceAll` |
| `labRecords` | `labRecordsSlice.js` (516 lines) | `{ byId, allIds, activeId, loading, errors, lastRefreshedAt, filters }` | `upsertLabRecord`, `upsertLabRecords`, `updateStatus`, `removeLabRecord`, `setPendingAction`, `clearPendingAction`, `replaceAll` |
| `definitions` | `definitionsSlice.js` (331 lines) | `{ byId, allIds, activeId, loading, errors, lastRefreshedAt }` | `upsertDefinition`, `removeDefinition`, `replaceAll` |
| `templates` | `templatesSlice.js` (309 lines) | `{ byId, allIds, loading, errors, lastRefreshedAt }` | `upsertTemplate`, `removeTemplate`, `replaceAll` |

### 3.5 SSE Adapter Store Dispatch Mapping — `sseAdapter.js` (517 lines)

The `LcmSSEAdapter._setupStoreUpdates()` method wires **~40 EventBus subscriptions** to store dispatches:

| EventBus Event | Store Dispatch | Notes |
|---------------|----------------|-------|
| `WORKER_SNAPSHOT` | `workers/upsertWorker` | Data normalized via `_normalizeWorkerSnapshot()` |
| `WORKER_CREATED` | `workers/upsertWorker` | |
| `WORKER_IMPORTED` | `workers/upsertWorker` | |
| `WORKER_METRICS_UPDATED` | `workers/updateMetrics` | Extracts `workerId` from `data.worker_id \|\| data.id` |
| `WORKER_TERMINATED` | `workers/removeWorker` | |
| `LABLET_SESSION_SNAPSHOT` | `sessions/upsertSession` | |
| `LABLET_SESSION_CREATED` | `sessions/upsertSession` | |
| `LABLET_SESSION_UPDATED` | `sessions/upsertSession` | |
| `LABLET_SESSION_STATUS_CHANGED` | `sessions/upsertSession` | |
| `LABLET_SESSION_PIPELINE_PROGRESS` | `sessions/upsertSession` | Merges `pipeline_progress` dict |
| `LABLET_SESSION_DESIRED_STATUS_CHANGED` | `sessions/upsertSession` | Sets `desired_status` field |
| `PIPELINE_STEP_STARTED` | `sessions/upsertSession` | Via `_updatePipelineStep()` |
| `PIPELINE_STEP_COMPLETED` | `sessions/upsertSession` | Via `_updatePipelineStep()` |
| `PIPELINE_STEP_FAILED` | `sessions/upsertSession` | Via `_updatePipelineStep()` |
| `PIPELINE_COMPLETED` | Re-emits as `LABLET_SESSION_PIPELINE_PROGRESS` | |
| `LABLET_SESSION_TERMINATED` | `sessions/removeSession` | |
| `WORKER_TEMPLATE_CREATED` | `templates/upsertTemplate` | |
| `WORKER_TEMPLATE_UPDATED` | `templates/upsertTemplate` | |
| `WORKER_TEMPLATE_DELETED` | `templates/removeTemplate` | |
| `LABLET_DEFINITION_SNAPSHOT` | `definitions/upsertDefinition` | |
| `LABLET_DEFINITION_CREATED` | `definitions/upsertDefinition` | |
| `LABLET_DEFINITION_UPDATED` | `definitions/upsertDefinition` | |
| `LABLET_DEFINITION_DELETED` | `definitions/removeDefinition` | |
| `LABLET_DEFINITION_ACTIVATED` | `definitions/upsertDefinition` | Sets `is_active: true` |
| `LABLET_DEFINITION_DEACTIVATED` | `definitions/upsertDefinition` | Sets `is_active: false` |
| `LABLET_DEFINITION_CONTENT_SYNCED` | `definitions/upsertDefinition` | Sets `sync_status`, `last_synced_at` |
| `LABLET_DEFINITION_DEPRECATED` | `definitions/upsertDefinition` | Sets `status: deprecated` + metadata |
| `LABLET_DEFINITION_SYNC_REQUESTED` | `definitions/upsertDefinition` | Sets `sync_status: sync_requested` |
| `LAB_RECORD_SNAPSHOT` | `labRecords/upsertLabRecord` | |
| `LAB_RECORD_DISCOVERED` | `labRecords/upsertLabRecord` | |
| `LAB_RECORD_IMPORTED` | `labRecords/upsertLabRecord` | |
| `LAB_RECORD_STATUS_UPDATED` | `labRecords/updateStatus` | Re-emits `DELETED`/`ARCHIVED` as needed |
| `LAB_RECORD_DELETED` | `labRecords/updateStatus` | Sets `status: deleted` |
| `LAB_RECORD_ARCHIVED` | `labRecords/updateStatus` | Sets `status: archived` |
| `LAB_RECORD_CLONED` | `labRecords/upsertLabRecord` | |
| `LAB_RECORD_TOPOLOGY_UPDATED` | `labRecords/upsertLabRecord` | |
| `LAB_RECORD_ACTION_QUEUED` | `labRecords/setPendingAction` | AD-023 pattern |
| `LAB_RECORD_ACTION_COMPLETED` | `labRecords/clearPendingAction` | |
| `LAB_RECORD_ACTION_FAILED` | `labRecords/clearPendingAction` | |
| `SYSTEM_SSE_SHUTDOWN` | Disconnect + reconnect after 2s | |
| `AUTH_SESSION_EXPIRED` | Disconnect | |
| `SSE_CONNECTED` | Toast notification | |

### 3.6 Toast Notifications — `eventMap.js`

The `toastEventTypes` map triggers user-visible notifications for 13 event types:
`WORKER_CREATED`, `WORKER_IMPORTED`, `WORKER_TERMINATED`, `WORKER_REFRESH_THROTTLED`, `WORKERS_REFRESH_COMPLETED`, `WORKER_LICENSE_*` (4 events), `SYSTEM_SSE_SHUTDOWN`, `LAB_RECORD_DISCOVERED`, `LAB_RECORD_ACTION_COMPLETED/FAILED`, `LABLET_DEFINITION_CREATED`, `LABLET_DEFINITION_CONTENT_SYNCED`, `LABLET_DEFINITION_DEPRECATED`, `PIPELINE_STEP_FAILED`, `PIPELINE_COMPLETED`.

### 3.7 Bridge Layer

**`bridge/uiCoreSetup.js`**: Auto-executing module that:

1. Calls `configureComponents({ eventBus, store })` — injects CPA's app-level EventBus + StateStore into lcm_ui's `BaseComponent` so all `<ui-*>` web components can use `this.emit()` / `this.connectToStore()`.
2. Calls `registerAllComponents()` — defines all `<ui-*>` custom elements.

**`bridge/StoreConnectedPage.js`** (266 lines): Base class for page-level components with:

- `connectSlice(sliceName, selector, callback)` — selector-based store subscription with automatic cleanup
- `get actions()` — lazy action creator cache
- Lifecycle: `initialize(user)` → `render()` → `subscribeToStore()` → `loadInitialData()`

---

## 4. Frontend Web Components for Resources

All 15 components are in `core/lcm_ui/src/components/` and extend `BaseComponent`. They are **passive renderers** — driven entirely by HTML attributes and JavaScript API calls (e.g., `setStatus()`, `setSteps()`). They do NOT subscribe to SSE events directly.

### 4.1 Component Catalog

| Component | Tag | Purpose | Key Attributes/API |
|-----------|-----|---------|-------------------|
| **ResourceStatus** | `<ui-resource-status>` | Status + desired-status badges with reconciliation arrow | `status`, `desired-status` → `setStatus()`, `setDesiredStatus()` |
| **StatusBadge** | `<ui-status-badge>` | Single status badge with color/icon | `status`, `size`, `variant` |
| **ResourceObservation** | `<ui-resource-observation>` | CPU/memory/storage progress bars, node details | `observation` → `setObservation(data)` |
| **PipelineLog** | `<ui-pipeline-log>` | Step-by-step pipeline execution log with live timer | `setSteps(steps)`, `updateStep(name, update)` |
| **LifecycleTracker** | `<ui-lifecycle-tracker>` | Phase visualization (compact dots / horizontal / vertical) | `phases`, `layout` → `setPhases(phases)`, `updatePhase(name, update)` |
| **StateHistory** | `<ui-state-history>` | State transition timeline (breadcrumb or full) | `transitions`, `layout` → `setTransitions(transitions)` |
| **TimeslotBadge** | `<ui-timeslot-badge>` | Phase-aware timeslot display (before/approaching/active/teardown/expired) | `timeslot` → `setTimeslot(data)`. Auto-refreshes every 10s. |
| **MetricCard** | `<ui-metric-card>` | Metric value with trend indicator | `setData({ value, label, unit, trend })` |
| **ActionBar** | `<ui-action-bar>` | Action buttons + filter chips + dropdowns | Emits `ui:action`, `ui:filter-remove` to EventBus |
| **RevisionIndicator** | `<ui-revision-indicator>` | Version badge with localStorage delta tracking | `revision` → emits `revision-clicked` DOM event |
| **DataTable** | `<ui-data-table>` | Configurable data table | Column config, sorting, pagination |
| **TabView/Tab** | `<ui-tab-view>`, `<ui-tab>` | Tab container | Active tab management |
| **Modal/ConfirmModal** | `<ui-modal>`, `<ui-confirm-modal>` | Dialog overlays | Promise-based confirmation |
| **ColumnPicker** | `<ui-column-picker>` | Column visibility toggle | Column config |

### 4.2 Component–ResourceState Field Mapping

| ResourceState Field | Web Component | How It Gets There |
|--------------------|--------------|-------------------|
| `status` | `<ui-resource-status>`, `<ui-status-badge>` | Page sets attribute from store state |
| `desired_status` | `<ui-resource-status>` (dual badge + reconciliation arrow) | Page sets attribute from store state |
| `state_history` | `<ui-state-history>` | Page calls `setTransitions()` from store state |
| `pipeline_progress` | `<ui-pipeline-log>` | Page calls `setSteps()`/`updateStep()` from store state |
| `timeslot` | `<ui-timeslot-badge>` | Page calls `setTimeslot()` from store state |
| `lifecycle` | `<ui-lifecycle-tracker>` | Page calls `setPhases()` from store state |
| CPU/memory/storage metrics | `<ui-resource-observation>` | Page calls `setObservation()` from worker metrics in store |

---

## 5. SSE Event Type Mapping & Gap Analysis

> **Last updated**: Track 2 remediation complete. All end-to-end gaps resolved.
> Status legend: ✅ Complete | ℹ️ Mitigated / Signal / Toast | 🏷️ Deprecated

### 5.1 Complete Mapping: Backend → eventMap → EventBus → Store

#### Worker Events

| Backend SSE Event | eventMap | EventBus Constant | Store Dispatch | Status |
|---|---|---|---|---|
| `worker.snapshot` | ✅ | `WORKER_SNAPSHOT` | `workers/upsertWorker` | ✅ Complete |
| `worker.created` | ✅ | `WORKER_CREATED` | `workers/upsertWorker` | ✅ Complete |
| `worker.imported` | ✅ | `WORKER_IMPORTED` | `workers/upsertWorker` | ✅ Complete |
| `worker.status.updated` | ✅ | `WORKER_STATUS_CHANGED` | — | ℹ️ Mitigated — backend co-emits `worker.snapshot` → `upsertWorker` |
| `worker.terminated` | ✅ | `WORKER_TERMINATED` | `workers/removeWorker` | ✅ Complete |
| `worker.metrics.updated` | ✅ | `WORKER_METRICS_UPDATED` | `workers/updateMetrics` | ✅ Complete |
| `worker.metrics.updated.batch` | ✅ | `WORKER_METRICS_UPDATED_BATCH` | `workers/updateMetrics` × N | ✅ Complete — ADR-013 batch unwrap |
| `worker.endpoint.updated` | ✅ | `WORKER_ENDPOINT_UPDATED` | — | ℹ️ Mitigated — backend co-emits `worker.snapshot` → `upsertWorker` |
| `worker.ec2_details.updated` | ✅ | `WORKER_EC2_DETAILS_UPDATED` | — | ℹ️ Mitigated — backend co-emits `worker.snapshot` → `upsertWorker` |
| `worker.activity.updated` | ✅ | `WORKER_ACTIVITY_UPDATED` | — | ℹ️ EventBus only — available for direct component subscription |
| `worker.idle_detection.toggled` | ✅ | `WORKER_IDLE_DETECTION_TOGGLED` | — | ℹ️ EventBus only |
| `worker.paused` | ✅ | `WORKER_PAUSED` | — | ℹ️ EventBus only |
| `worker.resumed` | ✅ | `WORKER_RESUMED` | — | ℹ️ EventBus only |
| `worker.refresh.throttled` | ✅ | `WORKER_REFRESH_THROTTLED` | — | ℹ️ Toast only |
| `worker.data.refreshed` | ✅ | `WORKER_DATA_REFRESHED` | — | ℹ️ EventBus only |
| `worker.labs.updated` | ✅ | `LAB_UPDATED` | — | 🏷️ Legacy — `@deprecated`, no frontend subscriber |
| `workers.refresh.completed` | ✅ | `WORKERS_REFRESH_COMPLETED` | — | ℹ️ Toast only |

#### Worker License Events

| Backend SSE Event | eventMap | EventBus Constant | Store Dispatch | Status |
|---|---|---|---|---|
| `worker.license.registration.started` | ✅ | `WORKER_LICENSE_REGISTRATION_STARTED` | — | ℹ️ Toast only |
| `worker.license.registration.completed` | ✅ | `WORKER_LICENSE_REGISTRATION_COMPLETED` | — | ℹ️ Toast only |
| `worker.license.registration.failed` | ✅ | `WORKER_LICENSE_REGISTRATION_FAILED` | — | ℹ️ Toast only |
| `worker.license.deregistered` | ✅ | `WORKER_LICENSE_DEREGISTERED` | — | ℹ️ Toast only |

#### Lablet Session Events

| Backend SSE Event | eventMap | EventBus Constant | Store Dispatch | Status |
|---|---|---|---|---|
| `lablet.session.created` | ✅ | `LABLET_SESSION_CREATED` | `sessions/upsertSession` | ✅ Complete |
| `lablet.session.updated` | ✅ | `LABLET_SESSION_UPDATED` | `sessions/upsertSession` | ✅ Complete |
| `lablet.session.deleted` | ✅ | `LABLET_SESSION_DELETED` | `sessions/removeSession` | ✅ Complete |
| `lablet.session.status.changed` | ✅ | `LABLET_SESSION_STATUS_CHANGED` | `sessions/upsertSession` | ✅ Complete |
| `lablet.session.scheduled` | ✅ | `LABLET_SESSION_SCHEDULED` | — | ℹ️ Mitigated — covered by `status.changed` → `upsertSession` |
| `lablet.session.instantiating` | ✅ | `LABLET_SESSION_INSTANTIATING` | — | ℹ️ Mitigated — covered by `status.changed` → `upsertSession` |
| `lablet.session.ready` | ✅ | `LABLET_SESSION_READY` | — | ℹ️ Mitigated — covered by `status.changed` → `upsertSession` |
| `lablet.session.running` | ✅ | `LABLET_SESSION_RUNNING` | — | ℹ️ Mitigated — covered by `status.changed` → `upsertSession` |
| `lablet.session.collecting` | ✅ | `LABLET_SESSION_COLLECTING` | — | ℹ️ Mitigated — covered by `status.changed` → `upsertSession` |
| `lablet.session.grading` | ✅ | `LABLET_SESSION_GRADING` | — | ℹ️ Mitigated — covered by `status.changed` → `upsertSession` |
| `lablet.session.stopping` | ✅ | `LABLET_SESSION_STOPPING` | — | ℹ️ Mitigated — covered by `status.changed` → `upsertSession` |
| `lablet.session.stopped` | ✅ | `LABLET_SESSION_STOPPED` | — | ℹ️ Mitigated — covered by `status.changed` → `upsertSession` |
| `lablet.session.archived` | ✅ | `LABLET_SESSION_ARCHIVED` | — | ℹ️ Mitigated — covered by `status.changed` → `upsertSession` |
| `lablet.session.terminated` | ✅ | `LABLET_SESSION_TERMINATED` | `sessions/removeSession` | ✅ Complete |
| `lablet.session.snapshot` | ✅ | `LABLET_SESSION_SNAPSHOT` | `sessions/upsertSession` | ✅ Complete |
| `lablet.session.pipeline.progress` | ✅ | `LABLET_SESSION_PIPELINE_PROGRESS` | `sessions/upsertSession` (merge) | ✅ Complete |
| `lablet.session.desired_status.changed` | ✅ | `LABLET_SESSION_DESIRED_STATUS_CHANGED` | `sessions/upsertSession` | ✅ Complete |
| `lablet.session.score.recorded` | ✅ | `LABLET_SESSION_SCORE_RECORDED` | `sessions/upsertSession` | ✅ Complete — Track 2 |
| `lablet.session.timeslot.extended` | ✅ | `LABLET_SESSION_TIMESLOT_EXTENDED` | `sessions/upsertSession` | ✅ Complete — Track 2 |
| `lablet.session.ports.released` | ✅ | `LABLET_SESSION_PORTS_RELEASED` | `sessions/upsertSession` | ✅ Complete — Track 2 |
| `lablet.sessions.refresh.completed` | ✅ | `LABLET_SESSIONS_REFRESH_COMPLETED` | — | ℹ️ Signal |

#### Pipeline CloudEvents

| Backend SSE Event | eventMap | EventBus Constant | Store Dispatch | Status |
|---|---|---|---|---|
| `pipeline.step.started.v1` | ✅ | `PIPELINE_STEP_STARTED` | `sessions/upsertSession` via `_updatePipelineStep()` | ✅ Complete |
| `pipeline.step.completed.v1` | ✅ | `PIPELINE_STEP_COMPLETED` | `sessions/upsertSession` via `_updatePipelineStep()` | ✅ Complete |
| `pipeline.step.failed.v1` | ✅ | `PIPELINE_STEP_FAILED` | `sessions/upsertSession` via `_updatePipelineStep()` | ✅ Complete |
| `pipeline.completed.v1` | ✅ | `PIPELINE_COMPLETED` | Re-emits as `PIPELINE_PROGRESS` | ✅ Complete |

#### Lablet Definition Events

| Backend SSE Event | eventMap | EventBus Constant | Store Dispatch | Status |
|---|---|---|---|---|
| `lablet.definition.created` | ✅ | `LABLET_DEFINITION_CREATED` | `definitions/upsertDefinition` | ✅ Complete |
| `lablet.definition.updated` | ✅ | `LABLET_DEFINITION_UPDATED` | `definitions/upsertDefinition` | ✅ Complete |
| `lablet.definition.activated` | ✅ | `LABLET_DEFINITION_ACTIVATED` | `definitions/upsertDefinition` | ✅ Complete |
| `lablet.definition.deactivated` | ✅ | `LABLET_DEFINITION_DEACTIVATED` | `definitions/upsertDefinition` | ✅ Complete |
| `lablet.definition.deleted` | ✅ | `LABLET_DEFINITION_DELETED` | `definitions/removeDefinition` | ✅ Complete |
| `lablet.definition.snapshot` | ✅ | `LABLET_DEFINITION_SNAPSHOT` | `definitions/upsertDefinition` | ✅ Complete |
| `lablet.definition.content_synced` | ✅ | `LABLET_DEFINITION_CONTENT_SYNCED` | `definitions/upsertDefinition` | ✅ Complete |
| `lablet.definition.deprecated` | ✅ | `LABLET_DEFINITION_DEPRECATED` | `definitions/upsertDefinition` | ✅ Complete |
| `lablet.definition.sync_requested` | ✅ | `LABLET_DEFINITION_SYNC_REQUESTED` | `definitions/upsertDefinition` | ✅ Complete |
| `lablet.definitions.refresh.completed` | ✅ | `LABLET_DEFINITIONS_REFRESH_COMPLETED` | — | ℹ️ Signal |

#### Worker Template Events

| Backend SSE Event | eventMap | EventBus Constant | Store Dispatch | Status |
|---|---|---|---|---|
| `worker.template.created` | ✅ | `WORKER_TEMPLATE_CREATED` | `templates/upsertTemplate` | ✅ Complete |
| `worker.template.updated` | ✅ | `WORKER_TEMPLATE_UPDATED` | `templates/upsertTemplate` | ✅ Complete |
| `worker.template.deleted` | ✅ | `WORKER_TEMPLATE_DELETED` | `templates/removeTemplate` | ✅ Complete |

#### Lab Record Events

| Backend SSE Event | eventMap | EventBus Constant | Store Dispatch | Status |
|---|---|---|---|---|
| `lab.discovered` | ✅ | `LAB_RECORD_DISCOVERED` | `labRecords/upsertLabRecord` | ✅ Complete |
| `lab.status.updated` | ✅ | `LAB_RECORD_STATUS_UPDATED` | `labRecords/updateStatus` | ✅ Complete — also re-emits DELETED/ARCHIVED |
| `lab.imported` | ✅ | `LAB_RECORD_IMPORTED` | `labRecords/upsertLabRecord` | ✅ Complete |
| `lab.cloned` | ✅ | `LAB_RECORD_CLONED` | `labRecords/upsertLabRecord` | ✅ Complete |
| `lab.bound` | ✅ | `LAB_RECORD_BOUND` | `labRecords/upsertLabRecord` | ✅ Complete — Track 2 |
| `lab.unbound` | ✅ | `LAB_RECORD_UNBOUND` | `labRecords/upsertLabRecord` | ✅ Complete — Track 2 |
| `lab.topology.updated` | ✅ | `LAB_RECORD_TOPOLOGY_UPDATED` | `labRecords/upsertLabRecord` | ✅ Complete |
| `lab.snapshot` | ✅ | `LAB_RECORD_SNAPSHOT` | `labRecords/upsertLabRecord` | ✅ Complete |
| `lab.action.requested` | ✅ | `LAB_RECORD_ACTION_QUEUED` | `labRecords/setPendingAction` | ✅ Complete — AD-023 |
| `lab.action.completed` | ✅ | `LAB_RECORD_ACTION_COMPLETED` | `labRecords/clearPendingAction` | ✅ Complete — AD-023 |
| `lab.action.failed` | ✅ | `LAB_RECORD_ACTION_FAILED` | `labRecords/clearPendingAction` | ✅ Complete — AD-023 |
| `lab.error` | ✅ | `LAB_RECORD_ERROR` | `labRecords/upsertLabRecord` | ✅ Complete — Track 2 |
| `lab_records.refresh.completed` | ✅ | `LAB_RECORDS_REFRESH_COMPLETED` | — | ℹ️ Signal |

#### System / Auth Events

| Backend SSE Event | eventMap | EventBus Constant | Store Dispatch | Status |
|---|---|---|---|---|
| `system.sse.shutdown` | ✅ | `SYSTEM_SSE_SHUTDOWN` | Disconnect + reconnect (2s) | ✅ Complete |
| `auth.session.expired` | ✅ | `AUTH_SESSION_EXPIRED` | Disconnect (no reconnect) | ✅ Complete |

#### Backward-Compat Aliases (eventMap only)

| Backend SSE Event | eventMap | EventBus Constant | Notes |
|---|---|---|---|
| `lablet.instance.created` | ✅ | `LABLET_SESSION_CREATED` | Old wire name → same constant |
| `lablet.instance.updated` | ✅ | `LABLET_SESSION_UPDATED` | Old wire name → same constant |
| `lablet.instance.deleted` | ✅ | `LABLET_SESSION_DELETED` | Old wire name → same constant |
| `lablet.instance.status.changed` | ✅ | `LABLET_SESSION_STATUS_CHANGED` | Old wire name → same constant |
| `lablet.instance.snapshot` | ✅ | `LABLET_SESSION_SNAPSHOT` | Old wire name → same constant |
| `lablet.instances.refresh.completed` | ✅ | `LABLET_SESSIONS_REFRESH_COMPLETED` | Old wire name → same constant |

### 5.2 Backend Events NOT in eventMap — ✅ All Resolved

All previously identified gaps have been resolved in Track 2:

| Backend SSE Event | Resolution |
|---|---|
| `lablet.session.score.recorded` | ✅ eventMap entry + `sessions/upsertSession` dispatch (merges score fields) |
| `lablet.session.ports.released` | ✅ eventMap entry + `sessions/upsertSession` dispatch (sets `ports_allocated` to null) |
| `lablet.session.timeslot.extended` | ✅ eventMap entry + `sessions/upsertSession` dispatch (updates timeslot if present) |
| `worker.metrics.updated.batch` | ✅ eventMap entry + batch unwrap handler (iterates `data.events[]` → `workers/updateMetrics` each) |

### 5.3 Frontend LcmEventTypes NOT Emitted by Backend

These constants exist in `eventTypes.js` but have no corresponding backend SSE handler. They serve as frontend-only synthetic events or are deprecated/planned:

| LcmEventTypes Constant | Value | Annotation | Notes |
|---|---|---|---|
| `WORKER_UPDATED` | `worker.updated` | `@deprecated` | Synthetic — re-emitted by frontend only, no backend SSE |
| `WORKER_ACTIVE_CHANGED` | `worker.active.changed` | `@deprecated` | Emitted by workersSlice but never consumed |
| `WORKER_TIMING_UPDATED` | `worker.timing.updated` | `@deprecated` | Emitted by workersSlice but never consumed |
| `LAB_UPDATED` | `lab.updated` | `@deprecated` | Legacy SSE-mapped but no frontend subscriber |
| `LAB_RECORD_DELETED` | `lab_record.deleted` | — | No direct backend wire; re-emitted from `LAB_RECORD_STATUS_UPDATED` in sseAdapter when `status === 'deleted'` |
| `LAB_RECORD_ARCHIVED` | `lab_record.archived` | — | Same — re-emitted from `LAB_RECORD_STATUS_UPDATED` when `status === 'archived'` |
| `WORKER_TEMPLATE_ENABLED` | `worker.template.enabled` | `@todo` | Backend handler not yet implemented |
| `WORKER_TEMPLATE_DISABLED` | `worker.template.disabled` | `@todo` | Backend handler not yet implemented |
| `SESSIONS_REFRESH_COMPLETED` | `sessions.refresh.completed` | `@deprecated` | Emitted by sessionsActions but never consumed |
| `TAB_CHANGED` | `ui.tab.changed` | `@deprecated` | Emitted by LcmTabView but never consumed |

### 5.4 Current Status Summary

#### ✅ Store Dispatch Coverage — No Gaps

All events that require store updates now have dispatches. The only events without store dispatches are intentionally so:

**By design — Mitigated via snapshot co-emission (worker domain):**

Events like `worker.status.updated`, `worker.endpoint.updated`, and `worker.ec2_details.updated` have no dedicated store dispatch because the backend co-emits a `worker.snapshot` event alongside each of these, and `worker.snapshot` IS dispatched to `workers/upsertWorker`. This is a deliberate design choice — the snapshot carries the complete worker state, making a separate dispatch for each field-level event redundant.

**By design — Mitigated via consolidated status event (session domain):**

Fine-grained session lifecycle events (`lablet.session.scheduled`, `.instantiating`, `.ready`, `.running`, `.collecting`, `.grading`, `.stopping`, `.stopped`, `.archived`) have no dedicated store dispatch because the backend co-emits a consolidated `lablet.session.status.changed` event alongside each of these, and that event IS dispatched to `sessions/upsertSession`. The fine-grained events remain available on the EventBus for direct component subscriptions (toasts, animations, transition effects).

**By design — EventBus-only events:**

Events like `worker.activity.updated`, `worker.idle_detection.toggled`, `worker.paused`, `worker.resumed`, and `worker.data.refreshed` are mapped to the EventBus but intentionally not dispatched to the store. They serve as extension points for direct component subscriptions without polluting the store's normalized state.

**By design — Toast/Signal-only events:**

License events (`worker.license.*`), refresh throttle/completion signals (`worker.refresh.throttled`, `workers.refresh.completed`, `*.refresh.completed`), and `heartbeat` are notification or coordination events that don't carry state to persist.

#### ✅ End-to-End Coverage — No Gaps

All backend-emitted SSE event types now have corresponding eventMap entries and sseAdapter handlers. Track 2 resolved the final 4 gaps:

| Resolved Gap | Resolution |
|---|---|
| `lablet.session.score.recorded` | eventMap + `sessions/upsertSession` (merges score fields) |
| `lablet.session.ports.released` | eventMap + `sessions/upsertSession` (nulls `ports_allocated`) |
| `lablet.session.timeslot.extended` | eventMap + `sessions/upsertSession` (updates timeslot) |
| `worker.metrics.updated.batch` | eventMap + batch unwrap → `workers/updateMetrics` per event |

### 5.5 Recommendations — ✅ All Resolved

All 5 original recommendations from the initial gap analysis have been implemented:

1. ✅ **Missing eventMap entries** — Added for `score.recorded`, `timeslot.extended`, `ports.released`, `metrics.updated.batch`
2. ✅ **`LAB_RECORD_BOUND`/`LAB_RECORD_UNBOUND` store dispatch** — Added `labRecords/upsertLabRecord`
3. ✅ **`LAB_RECORD_ERROR` store dispatch** — Added `labRecords/upsertLabRecord`
4. ✅ **Batch suffix handling** — Added `WORKER_METRICS_UPDATED_BATCH` constant + eventMap + unwrap handler
5. ✅ **Phantom LcmEventTypes cleanup** — 4 deprecated with `@deprecated` JSDoc, 2 tagged `@todo` for future backend

**Remaining considerations (low priority, not blocking):**

- `WORKER_TEMPLATE_ENABLED` / `WORKER_TEMPLATE_DISABLED` — `@todo` constants awaiting backend handler implementation
- Deprecated constants (`WORKER_UPDATED`, `WORKER_ACTIVE_CHANGED`, `WORKER_TIMING_UPDATED`, `LAB_UPDATED`, `SESSIONS_REFRESH_COMPLETED`, `TAB_CHANGED`) can be removed in a future cleanup pass when confirmed unused

---

## Appendix A: Complete File Listing

### Backend (control-plane-api/)

| File | Lines | Purpose |
|------|-------|---------|
| `application/services/sse_event_relay.py` | 392 | SSEEventRelay singleton — Redis pub/sub, client subscriptions, batching |
| `application/events/domain/cml_worker_events.py` | 480 | 8 worker domain event → SSE handlers |
| `application/events/domain/lablet_session_sse_handlers.py` | 536 | 17 session domain event → SSE handlers |
| `application/events/domain/lab_record_events.py` | 523 | 15 lab record domain event → SSE handlers |
| `api/controllers/events_controller.py` | 273 | SSE endpoint, initial snapshots, heartbeat |

### Core Library (core/lcm_core/)

| File | Lines | Purpose |
|------|-------|---------|
| `domain/entities/resource.py` | 96 | ResourceState base (Layer 1) |
| `domain/entities/timed_resource.py` | 116 | TimedResourceState (Layer 2) |

### Core UI Library (core/lcm_ui/src/)

| File | Lines | Purpose |
|------|-------|---------|
| `core/SSEClient.ts` | 431 | EventSource wrapper, eventMap routing |
| `core/EventBus.ts` | 479 | Singleton pub/sub, wildcards, middleware |
| `core/StateStore.ts` | 580 | Slice-based state management |
| `core/BaseComponent.ts` | 581 | Web component base, store connection |
| `core/SSEEventBuffer.ts` | 232 | Ring buffer for SSE events |
| `core/constants.ts` | 42 | Library-level event type constants |
| `components/ResourceStatus.ts` | 160 | Status + desired-status badges |
| `components/StatusBadge.ts` | 297 | Single status badge |
| `components/ResourceObservation.ts` | ~250 | Telemetry display |
| `components/PipelineLog.ts` | ~350 | Pipeline step log |
| `components/LifecycleTracker.ts` | 323 | Phase visualization |
| `components/StateHistory.ts` | ~300 | State transition timeline |
| `components/TimeslotBadge.ts` | 214 | Timeslot phase display |
| `components/MetricCard.ts` | 241 | Metric card |
| `components/ActionBar.ts` | 427 | Action buttons |
| `components/RevisionIndicator.ts` | 160 | Version badge |

### CPA Frontend Application (control-plane-api/ui/src/scripts/)

| File | Lines | Purpose |
|------|-------|---------|
| `app/eventTypes.js` | 143 | LcmEventTypes constants (~80 domain event types) |
| `app/eventBus.js` | 37 | EventBus singleton + re-exports |
| `app/store.js` | 86 | StateStore with 5 registered slices |
| `app/index.js` | ~80 | Re-exports all app modules |
| `app/sse/eventMap.js` | 244 | 77 SSE wire → EventBus mappings + toast config |
| `app/sse/sseAdapter.js` | 517 | LcmSSEAdapter — store dispatch wiring, pipeline step handling |
| `app/slices/workersSlice.js` | 581 | Workers state management |
| `app/slices/sessionsSlice.js` | 400 | Sessions state management |
| `app/slices/labRecordsSlice.js` | 516 | Lab Records state management |
| `app/slices/definitionsSlice.js` | 331 | Definitions state management |
| `app/slices/templatesSlice.js` | 309 | Templates state management |
| `bridge/uiCoreSetup.js` | 49 | Injects EventBus+Store into ui-core components |
| `bridge/StoreConnectedPage.js` | 266 | Base class for store-driven page components |
