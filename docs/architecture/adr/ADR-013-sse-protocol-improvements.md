# ADR-013: SSE Protocol Improvements

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-01-19 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-001](./ADR-001-api-centric-state-management.md), [ADR-003](./ADR-003-cloudevents-for-integration.md) |

## Context

The current SSE (Server-Sent Events) implementation provides real-time updates to connected browsers:

| Event Type | Source | Current Status |
|------------|--------|----------------|
| `worker.created` | Domain event | ✅ Implemented |
| `worker.imported` | Domain event | ✅ Implemented |
| `worker.status.updated` | Domain event | ✅ Implemented |
| `worker.metrics.updated` | Domain event | ✅ Implemented |
| `worker.labs.updated` | Domain event | ✅ Implemented |
| `worker.terminated` | Domain event | ✅ Implemented |
| `system.sse.shutdown` | Hosted service | ✅ Implemented |

**Current Issues:**

1. **Missing event types**: No SSE events for:
   - Worker template CRUD
   - Lablet definition CRUD
   - Lablet instance CRUD (lifecycle transitions)

2. **No event batching**: Individual metrics events flood the connection during high-frequency updates

3. **No server-side filtering**: All events sent to all clients; filtering is client-side only

4. **Inefficient reconnection**: Clients reconnect and must refetch full state

## Decision

**Improve the SSE protocol with:**

1. ✅ **Event batching** for metrics
2. ✅ **Server-side filtering** via query parameters
3. ✅ **Extended event types** for all resource CRUD operations
4. ❌ **Resumable streams** (rejected - clients receive current state on reconnect)
5. ❌ **Controller-direct Redis publishing** (rejected - violates ADR-001)

### Extended Event Types

Add SSE events for all resource CRUD operations:

| Event Type | Trigger | Payload |
|------------|---------|---------|
| `worker-template.created` | CreateWorkerTemplateCommand | Template summary |
| `worker-template.updated` | UpdateWorkerTemplateCommand | Template summary |
| `worker-template.deleted` | DeleteWorkerTemplateCommand | Template ID |
| `lablet-definition.created` | CreateLabletDefinitionCommand | Definition summary |
| `lablet-definition.updated` | UpdateLabletDefinitionCommand | Definition summary |
| `lablet-definition.deleted` | DeleteLabletDefinitionCommand | Definition ID |
| `lablet-instance.created` | CreateLabletInstanceCommand | Instance summary |
| `lablet-instance.scheduled` | ScheduleLabletInstanceCommand | Instance + worker assignment |
| `lablet-instance.status.updated` | TransitionLabletInstanceCommand | Instance status |
| `lablet-instance.terminated` | TerminateLabletInstanceCommand | Instance ID |

### Event Batching

For high-frequency events (metrics), batch multiple events into single frames:

```javascript
// Before (individual events):
event: worker.metrics.updated
data: {"worker_id": "w1", "cpu": 45.2}

event: worker.metrics.updated
data: {"worker_id": "w2", "cpu": 67.8}

// After (batched):
event: worker.metrics.batch
data: {
  "batch_id": "b123",
  "count": 2,
  "events": [
    {"worker_id": "w1", "cpu": 45.2, "memory": 60.1},
    {"worker_id": "w2", "cpu": 67.8, "memory": 55.3}
  ]
}
```

**Batching configuration:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `batch_interval_ms` | 1000 | Time window for collecting events |
| `max_batch_size` | 50 | Maximum events per batch |
| `batch_event_types` | `worker.metrics.updated` | Event types eligible for batching |

### Server-Side Filtering

Add query parameters to `/api/events/stream`:

| Parameter | Type | Description |
|-----------|------|-------------|
| `worker_ids` | string (comma-separated) | Filter events for specific workers |
| `event_types` | string (comma-separated) | Filter by event type prefix |
| `include_system` | boolean | Include system events (heartbeat, shutdown) |

**Example:**

```
GET /api/events/stream?worker_ids=w1,w2&event_types=worker.metrics,worker.status
```

This reduces network traffic and client processing for focused views.

## Rationale

### Event Batching Benefits

1. **Reduced network overhead**: Single frame for multiple events
2. **Lower client processing**: Batch updates reduce DOM operations
3. **Predictable timing**: UI updates at consistent intervals
4. **Backpressure management**: Prevents event queue overflow

### Server-Side Filtering Benefits

1. **Reduced bandwidth**: Clients only receive relevant events
2. **Lower client CPU**: No client-side filtering logic needed
3. **Scalability**: Supports views with many workers/instances
4. **Privacy/security**: Foundation for future role-based event filtering

### Rejected: Resumable Streams

**Why rejected:**

- Added complexity for event tracking and storage
- Clients must handle current state on reconnect anyway
- Most disconnections are brief; full refetch is acceptable
- Event store would grow unbounded without cleanup policy

**Alternative approach:**
Clients call `GET /api/workers` (or relevant endpoint) on reconnect to get current state, then receive live updates.

### Rejected: Controller-Direct Redis Publishing

**Why rejected:**

- Violates ADR-001 (API-centric state management)
- Controllers should not have write access to any persistence
- Would create inconsistent event sourcing
- Current flow (Controller → API → Domain Event → SSE) provides proper audit trail

## Consequences

### SSEEventRelay Changes

```python
class SSEEventRelay:
    """Enhanced SSE relay with batching and filtering."""

    def __init__(self, serializer: JsonSerializer):
        # ... existing ...
        self._batch_buffer: dict[str, list[dict]] = {}
        self._batch_task: asyncio.Task | None = None

    async def register_client(
        self,
        worker_ids: set[str] | None = None,
        event_types: set[str] | None = None,
        include_system: bool = True,
    ) -> tuple[str, asyncio.Queue]:
        """Register client with server-side filtering."""
        # ... enhanced filtering ...

    async def _flush_batch(self, event_type: str) -> None:
        """Flush accumulated events as a batch."""
        events = self._batch_buffer.get(event_type, [])
        if not events:
            return

        batch_event = {
            "batch_id": str(uuid4()),
            "count": len(events),
            "events": events,
        }
        await self.broadcast_event(f"{event_type}.batch", batch_event)
        self._batch_buffer[event_type] = []
```

### Events Controller Update

```python
@get("/stream")
async def event_stream(
    self,
    worker_ids: str | None = Query(default=None),
    event_types: str | None = Query(default=None),
    include_system: bool = Query(default=True),
) -> EventSourceResponse:
    """SSE stream with optional filtering."""
    worker_id_set = set(worker_ids.split(",")) if worker_ids else None
    event_type_set = set(event_types.split(",")) if event_types else None

    client_id, queue = await self.sse_relay.register_client(
        worker_ids=worker_id_set,
        event_types=event_type_set,
        include_system=include_system,
    )
    # ... rest of implementation ...
```

### Frontend Changes

Update `sse-client.js` to:

1. Support filter parameters on connection
2. Handle batch events (`*.batch` suffix)
3. Unpack batch payloads for existing handlers

```javascript
// Connect with filters
sseClient.connect({
    workerIds: ['w1', 'w2'],
    eventTypes: ['worker.metrics', 'worker.status'],
    includeSystem: true
});

// Handle batch events automatically
sseClient.on('worker.metrics', handler);  // Works for both individual and batch
```

### New Domain Event Handlers

| Handler | Event | SSE Type |
|---------|-------|----------|
| `WorkerTemplateCreatedHandler` | `WorkerTemplateCreatedDomainEvent` | `worker-template.created` |
| `WorkerTemplateUpdatedHandler` | `WorkerTemplateUpdatedDomainEvent` | `worker-template.updated` |
| `WorkerTemplateDeletedHandler` | `WorkerTemplateDeletedDomainEvent` | `worker-template.deleted` |
| `LabletDefinitionCreatedHandler` | `LabletDefinitionCreatedDomainEvent` | `lablet-definition.created` |
| `LabletDefinitionUpdatedHandler` | `LabletDefinitionUpdatedDomainEvent` | `lablet-definition.updated` |
| `LabletDefinitionDeletedHandler` | `LabletDefinitionDeletedDomainEvent` | `lablet-definition.deleted` |
| `LabletInstanceCreatedHandler` | `LabletInstanceCreatedDomainEvent` | `lablet-instance.created` |
| `LabletInstanceScheduledHandler` | `LabletInstanceScheduledDomainEvent` | `lablet-instance.scheduled` |
| `LabletInstanceStatusUpdatedHandler` | `LabletInstanceStatusUpdatedDomainEvent` | `lablet-instance.status.updated` |
| `LabletInstanceTerminatedHandler` | `LabletInstanceTerminatedDomainEvent` | `lablet-instance.terminated` |

## Implementation Phases

### Phase 1: Server-Side Filtering ✅

- [x] Update `/api/events/stream` to accept query parameters
- [x] Update `SSEEventRelay.register_client()` with filter support
- [x] Update `SSEClientSubscription.matches_event()` for new filters
- [x] Update `sse-client.js` to pass filter parameters

### Phase 2: Event Batching ✅

- [x] Add batch buffer to `SSEEventRelay`
- [x] Implement batch flush timer (1-second intervals)
- [x] Create batch event format (`*.batch` suffix)
- [x] Update `SSEEventRelayHostedService` to start/stop batch timer
- [ ] Update `sse-client.js` to handle batch events (Phase 7)

### Phase 3: Extended Event Types (Worker Templates) ✅

- [x] Create domain events for worker template CRUD (`domain/events/worker_template_events.py`)
- [x] Create SSE handlers for worker template events (`application/events/domain/worker_template_events.py`)
- [ ] Update frontend to handle template events

### Phase 4: Extended Event Types (Lablet Definitions) ✅

- [x] Create domain events for lablet definition CRUD (`domain/events/lablet_definition_events.py`)
- [x] Create SSE handlers for definition events (`application/events/domain/lablet_definition_events.py`)
- [ ] Update frontend to handle definition events

### Phase 5: Extended Event Types (Lablet Instances) ✅

- [x] Create domain events for instance lifecycle (`domain/events/lablet_instance_events.py`)
- [x] Create SSE handlers for instance events (`application/events/domain/lablet_instance_sse_handlers.py`)
- [ ] Update frontend to handle instance events

### Phase 6: Integration Testing

- [ ] Test server-side filtering with various filter combinations
- [ ] Test event batching with high-frequency metrics
- [ ] Test extended event types end-to-end

### Phase 7: Frontend Updates

- [ ] Update `sse-client.js` to handle `*.batch` events automatically
- [ ] Add handlers for worker template SSE events
- [ ] Add handlers for lablet definition SSE events
- [ ] Add handlers for lablet instance SSE events
