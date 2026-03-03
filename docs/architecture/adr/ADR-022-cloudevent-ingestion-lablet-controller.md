# ADR-022: CloudEvent Ingestion via Lablet-Controller

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-02-18 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-003](./ADR-003-cloudevents-for-integration.md) (CloudEvents), [ADR-018](./ADR-018-lds-integration.md) (LDS Integration), [ADR-020](./ADR-020-session-entity-model.md) (Session Entity Model), [ADR-021](./ADR-021-child-entity-architecture.md) (Child Entities) |
| **Amends** | ADR-018 §7 (CloudEvent routing) |
| **Knowledge Refs** | AD-41 |

## Context

ADR-018 §7 originally specified that LDS CloudEvents (e.g., `session.started`) would be routed to **control-plane-api**, which would handle state transitions directly:

```
LDS → control-plane-api → MongoDB (update state)
```

This design was chosen because the state transition (READY → RUNNING) seemed like a simple mutation best handled by the component that owns MongoDB writes.

However, with the expanded Session entity model (ADR-020, ADR-021), CloudEvent handling now requires:

1. **Complex orchestration**: Receiving a `grading.session.completed` event requires creating a ScoreReport entity, updating the GradingSession status, and transitioning the LabletSession — all in sequence.
2. **External system interaction**: Some CloudEvent handlers need to call back to external systems (e.g., after `lds.session.user-finished`, initiate grading via GradingSPI).
3. **Domain logic**: Event handling involves business logic (score calculation, status validation) that belongs in the controller layer, not the API gateway.
4. **Multiple event sources**: Events now come from both LDS and GradingEngine, with different handling requirements.

### ADR-015 Constraint

ADR-015 established that control-plane-api must not make external calls. CloudEvent handlers that need to call GradingSPI or LabDeliverySPI cannot live in control-plane-api.

## Decision

### 1. Lablet-Controller Hosts CloudEventIngestor (AD-41)

All inbound CloudEvents from LDS and GradingEngine are routed to **lablet-controller**, not control-plane-api:

```
LDS / GradingEngine → lablet-controller (CloudEventIngestor) → control-plane-api (state mutations)
```

The lablet-controller exposes a `/api/events` endpoint that receives CloudEvents and dispatches them to type-specific handlers.

### 2. Neuroglia CloudEventIngestor + @dispatch Pattern

The implementation uses Neuroglia's `CloudEventIngestor` with the `@dispatch` decorator for type-based routing:

see /Users/bvandewe/Documents/Work/Systems/Mozart/src/microservices/lds-sessions-adapter/src/application/events/integration/lds_events_handlers.py

```python

class LdsSessionIntegrationEventHandler(
    IntegrationEventHandler[
        LdsSessionCreatedIntegrationEventV1
        | LdsSessionPartAddedIntegrationEventV1
        | LdsSessionPrelaunchedIntegrationEventV1
        | LdsSessionPartPrelaunchedIntegrationEventV1
        | LdsSessionRunningIntegrationEventV1
        | LdsSessionPartRunningIntegrationEventV1
        | LdsSessionPartNavIntegrationEventV1
        | LdsSessionPausedIntegrationEventV1
        | LdsSessionPartPausedIntegrationEventV1
        | LdsSessionUserFinishedIntegrationEventV1
        | LdsSessionPartUserFinishedIntegrationEventV1
        | LdsSessionPartUserFeedbackSubmittedIntegrationEventV1
        | LdsSessionPartUserSubmittedResponsesIntegrationEventV1
        | LdsSessionPartPopupIntegrationEventV1
        | LdsSessionPartRestartedIntegrationEventV1
        | LdsSessionPartVariablesUpdatedIntegrationEventV1
        | LdsSessionPartTimeUpdatedIntegrationEventV1
        | LdsSessionPartDevicesAddedIntegrationEventV1
    ]
):


    mapper: Mapper

    mediator: Mediator

    ...

    @dispatch(LdsSessionCreatedIntegrationEventV1)
    async def handle_async(self, e: LdsSessionCreatedIntegrationEventV1) -> None:
        """
        We ignore the sessionPart in here and rely on the LdsSessionPartAddedIntegrationEventV1 to handle that.
        """
        if self.session_event_sequencer:
            # Enqueue for sequential processing using simplified aggregate-based key - NO RECURSION
            self.session_event_sequencer.enqueue_event_by_aggregate_id(e.aggregateId, e, "LDS")
            return

        # Process directly if no sequencing
        try:
            await self._handle_session_created_internal(e)
        except Exception as ex:
            log.critical(f"CRITICAL: Unexpected exception in fallback (non-sequenced) path for {getattr(e, '__cloudevent__type__', 'unknown')}: {type(ex).__name__}: {ex}")

```

### 3. CloudEvent Types

see /Users/bvandewe/Documents/Work/Systems/Mozart/src/microservices/lds-sessions-adapter/src/application/events/integration/lds_events.py

- com.cisco.certs.lds.session.created.v1 > ACK that the session was created (with no part)
- com.cisco.certs.lds.sessionpart.added.v1 > ACK that the session part was added
- com.cisco.certs.lds.session.running.v1 > indicates the user started the session
- com.cisco.certs.lds.sessionpart.running.v1 > indicates the user started the session part (redundant with session.running.v1 when session has only one part)
- com.cisco.certs.lds.session.userfinished.v1 > indicates the user finished the session, triggers the collection/grading processes
- com.cisco.certs.lds.sessionpart.userfinished.v1
- com.cisco.certs.lds.session.finalized.v1 > ACK that the session was terminated
- com.cisco.certs.lds.sessionpart.finalized.v1
- com.cisco.certs.lds.sessionpart.devicesadded.v1 > ACK that devices access info was configured

### 4. State Mutations via Control Plane API

The lablet-controller does NOT write to MongoDB directly (ADR-001). All state changes are made via internal REST calls to control-plane-api:

```
CloudEvent → lablet-controller → POST /api/internal/sessions/{id}/transition → control-plane-api → MongoDB
```

This preserves the single-writer pattern while placing orchestration logic in the appropriate controller.

### 5. Idempotency

CloudEvent handlers must be idempotent:

- Duplicate `lds.session.started` events are ignored if session is already RUNNING
- Duplicate `grading.session.completed` events are ignored if ScoreReport already exists
- Control Plane API validates state transitions and rejects invalid ones with 409 Conflict

## Rationale

### Why lablet-controller, not control-plane-api?

| Concern | control-plane-api | lablet-controller |
|---------|-------------------|-------------------|
| MongoDB writes | ✅ Direct access | ❌ Via REST API |
| External calls (GradingSPI) | ❌ Forbidden (ADR-015) | ✅ Allowed |
| Complex orchestration | ❌ Gateway, not orchestrator | ✅ Controller pattern |
| Domain logic | ❌ Thin gateway | ✅ Reconciliation logic |
| SPI access (LDS, CML) | ❌ None | ✅ Full access |

The decisive factor is that CloudEvent handlers need to call external systems (GradingSPI, LabDeliverySPI), which is forbidden in control-plane-api per ADR-015.

### Why not a dedicated event-handler service?

- Adding a 5th microservice increases operational complexity
- lablet-controller already owns the LabletSession lifecycle
- The @dispatch pattern in lablet-controller is lightweight and consistent with existing reconciliation patterns

## Consequences

### Positive

- **Consistent with ADR-015**: No external calls from control-plane-api
- **Orchestration in one place**: All LabletSession lifecycle logic in lablet-controller
- **Clean handler pattern**: @dispatch provides type-safe, testable event handlers
- **Idempotent by design**: State validation in control-plane-api prevents duplicate processing

### Negative

- **Extra hop**: CloudEvent → lablet-controller → control-plane-api → MongoDB (vs. direct)
- **Latency**: Additional REST call for state mutations
- **Dependency**: lablet-controller must be running to process CloudEvents (no event queue)

### Mitigations

1. **Missing events**: LDS/GradingEngine should implement retry with exponential backoff
2. **Controller downtime**: Events are retried; eventual consistency is acceptable
3. **Latency**: Internal REST calls are sub-millisecond on same network
4. **Future**: Consider event queue (e.g., NATS, Redis Streams) for guaranteed delivery

## Implementation Notes

### Endpoint Registration

The CloudEventIngestor endpoint must be registered in lablet-controller's FastAPI app:

```python
# In lablet-controller main.py
app.include_router(cloudevent_router, prefix="/api/events")
```

### Event Source Configuration

LDS and GradingEngine must be configured to send CloudEvents to:

```
LABLET_CONTROLLER_CLOUDEVENT_ENDPOINT=http://lablet-controller:8003/api/events
```

### Testing Strategy

- Unit test each @dispatch handler with mocked ControlPlaneApiClient
- Integration test CloudEvent endpoint with actual HTTP POST of CloudEvent payloads
- End-to-end test full flow: LDS event → lablet-controller → control-plane-api → MongoDB state change

## Related Documents

- [ADR-003: CloudEvents for External Integration](./ADR-003-cloudevents-for-integration.md)
- [ADR-018: LDS Integration](./ADR-018-lds-integration.md)
- [LabletSession Lifecycle Flow](../lablet-instance-lifecycle-flow.md)
- [Lablet Resource Manager Architecture](../lablet-resource-manager-architecture.md) §5.3
