# ADR-003: CloudEvents for External Integration

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-01-15 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-004](./ADR-004-port-allocation-per-worker.md), [ADR-020](./ADR-020-session-entity-model.md), [ADR-022](./ADR-022-cloudevent-ingestion-lablet-controller.md) |

## Context

CCM must integrate with external systems:

- **Assessment Platform**: Trigger collection, receive grading results
- **Audit/Compliance**: Track all state changes for regulatory requirements
- **Billing/Metering**: Future integration for usage-based billing

We need a standardized event format for this communication.

Options considered:

1. **REST webhooks** - Direct HTTP callbacks to external systems
2. **CloudEvents** - CNCF standard event format via external CloudEvents bus
3. **Message queues** - RabbitMQ/SQS with custom payloads
4. **gRPC streaming** - Bidirectional streaming to subscribers

## Decision

**Use CloudEvents for all external system communication.**

All domain events are published as CloudEvents to an external CloudEvents bus (configurable via `CLOUDEVENTS_SINK_URL`). External systems subscribe to relevant event types.

!!! note "Implementation Flexibility"
    The CloudEvents bus implementation is deployment-specific. Common options include:

    - **Knative Eventing** - For Kubernetes deployments
    - **Azure Event Grid** - For Azure deployments
    - **AWS EventBridge** - For AWS deployments
    - **Custom HTTP sink** - For simple deployments

## Rationale

### Benefits

- **Vendor Neutral**: CNCF standard, no lock-in to specific message broker
- **Existing Support**: Neuroglia framework already supports CloudEvents
- **Decoupling**: CCM doesn't need to know about consumer internals
- **Extensibility**: New consumers can subscribe without CCM changes
- **Audit Trail**: Events naturally provide audit log when persisted

### Trade-offs

- Eventual consistency (events are async)
- Event schema versioning must be managed
- Debugging async flows more complex than sync calls

## Consequences

### Positive

- Clean integration boundaries
- Natural fit with event-driven architecture
- Audit log "for free" by persisting events

### Negative

- Must handle event ordering and idempotency
- Schema evolution requires careful planning

## Event Catalog

!!! note "Updated 2026-02-18"
    Event types updated to reflect LabletSession rename (ADR-020) and child entity architecture (ADR-021).
    Consumed events updated to reflect CloudEvent ingestion via lablet-controller (ADR-022).

### Events Emitted by CCM

| Event Type | Trigger | Data |
|------------|---------|------|
| `ccm.lablet.definition.created` | New definition registered | definition_id, name, version |
| `ccm.lablet.definition.version.created` | New version detected | definition_id, old_version, new_version |
| `ccm.lablet.session.pending` | Session requested | session_id, definition_id, owner_id |
| `ccm.lablet.session.scheduled` | Worker assigned | session_id, worker_id, allocated_ports |
| `ccm.lablet.session.instantiating` | Lab import + LDS provisioning started | session_id, worker_id |
| `ccm.lablet.session.ready` | Infrastructure ready, awaiting user | session_id, login_url |
| `ccm.lablet.session.running` | User logged in (via LDS CloudEvent) | session_id, user_session_id |
| `ccm.lablet.session.collecting` | Assessment collection started | session_id, grading_session_id |
| `ccm.lablet.session.grading` | GradingEngine scoring in progress | session_id, grading_session_id |
| `ccm.lablet.session.graded` | Score finalized | session_id, score_report_id, score, passed |
| `ccm.lablet.session.stopping` | Cleanup initiated | session_id |
| `ccm.lablet.session.stopped` | Lab stopped | session_id |
| `ccm.lablet.session.terminated` | Resources released | session_id, final_state |
| `ccm.lablet.user_session.created` | LDS session provisioned | user_session_id, lablet_session_id |
| `ccm.lablet.grading_session.created` | Grading initiated | grading_session_id, lablet_session_id |
| `ccm.lablet.score_report.created` | Score report stored | score_report_id, lablet_session_id, score, passed |
| `ccm.worker.scaling.up` | New worker starting | worker_id, template_name |
| `ccm.worker.scaling.down` | Worker stopping | worker_id, reason |
| `ccm.worker.draining` | Worker entering drain mode | worker_id |

### Events Consumed by CCM (via lablet-controller CloudEventIngestor — ADR-022)

| Event Type | Source | Handler | Action |
|------------|--------|---------|--------|
| `lds.session.started` | LDS | `LdsSessionStartedHandler` | UserSession → ACTIVE, LabletSession READY → RUNNING |
| `lds.session.ended` | LDS | `LdsSessionEndedHandler` | UserSession → ENDED, trigger COLLECTING + grading |
| `grading.session.completed` | Grading Engine | `GradingSessionCompletedHandler` | Create ScoreReport, GradingSession → SUBMITTED, session → STOPPING |
| `grading.session.failed` | Grading Engine | `GradingSessionFailedHandler` | GradingSession → FAULTED |

## Implementation Notes

- Use `@cloudevent` decorator for domain events (existing Neuroglia pattern)
- Configure `CLOUDEVENTS_SINK_URL` environment variable for the CloudEvents bus endpoint
- External systems query CloudEvents bus API for missed events
- Consider dead-letter queue for failed deliveries
- Fire-and-forget publishing (see Event-Driven State-Based Persistence pattern in [Architecture Overview](../index.md))
