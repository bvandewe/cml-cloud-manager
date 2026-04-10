# ADR-040: LDS CloudEvent Direct Ingestion via Control Plane API

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-10 |
| **Deciders** | Platform Team |
| **Related ADRs** | [ADR-003](./ADR-003-cloudevents-for-integration.md) (CloudEvents), [ADR-015](./ADR-015-control-plane-api-no-ec2.md) (CPA No External Calls), [ADR-018](./ADR-018-lds-integration.md) (LDS Integration), [ADR-022](./ADR-022-cloudevent-ingestion-lablet-controller.md) (CloudEvent Ingestion via Lablet-Controller) |
| **Amends** | ADR-022 (adds CPA as secondary CloudEvent handler for simple state transitions) |
| **Knowledge Refs** | AD-LDS-CE-001 |

## Context

ADR-022 established that **all** inbound CloudEvents from LDS and GradingEngine are routed to lablet-controller, which then calls control-plane-api's internal endpoints for state mutations. This was the correct decision for CloudEvents that require:

- **External system calls** (GradingSPI, LabDeliverySPI) — forbidden in CPA per ADR-015
- **Complex orchestration** (multi-step: create ScoreReport → update GradingSession → transition LabletSession)
- **Domain logic** that belongs in the controller layer

However, a subset of LDS CloudEvents represent **simple state transitions** that require only aggregate mutation — no external calls, no orchestration:

| CloudEvent Type | Current Handler | Required Action | Needs External Calls? |
|-----------------|-----------------|-----------------|----------------------|
| `io.lablet.lds.session.running.v1` | None (gap) | READY → RUNNING | ❌ No |
| `io.lablet.lds.session.paused.v1` | None (gap) | Informational log | ❌ No |
| `io.lablet.lds.session.ended.v1` | None (gap) | Informational log | ❌ No |
| `lds.session.user-finished` | lablet-controller | Initiate grading | ✅ Yes (GradingSPI) |
| `grading.session.completed` | lablet-controller | Create ScoreReport | ✅ Yes (complex) |

### Problem Statement

Sessions reaching READY state remain stuck because no handler transitions them to RUNNING when the user logs in via LDS. The `io.lablet.lds.session.running.v1` CloudEvent was being published by LDS but not consumed by any LCM service.

### ADR-015 Compatibility

The `session.running.v1` handler requires only:

1. Load `LabletSession` aggregate from repository
2. Call `session.mark_running()` (aggregate method)
3. Save aggregate to MongoDB

This is a pure **aggregate state mutation** — no external API calls. CPA is the natural home for this handler since it owns the aggregate and the repository.

## Decision

### 1. Dual CloudEvent Routing (Amendment to ADR-022)

Introduce a **dual routing model** where CloudEvent destination depends on handler complexity:

```text
LDS / GradingEngine
        │
        ├── Simple state transitions ──→ control-plane-api (CloudEventIngestor)
        │   • io.lablet.lds.session.running.v1
        │   • io.lablet.lds.session.paused.v1
        │   • io.lablet.lds.session.ended.v1
        │
        └── Complex orchestration ──→ lablet-controller (CloudEventIngestor)
            • lds.session.user-finished (→ GradingSPI)
            • grading.session.completed (→ ScoreReport + transition)
            • grading.session.failed (→ GradingSession.FAULTED)
```

**Routing rule**: If the handler needs only aggregate access (repository + save), it belongs in CPA. If it needs external calls or multi-entity orchestration, it stays in lablet-controller per ADR-022.

### 2. Integration Events in CPA

Three `@cloudevent`-decorated integration events registered with CPA's `CloudEventIngestor`:

```python
@cloudevent("io.lablet.lds.session.running.v1")
@dataclass
class LdsSessionRunningIntegrationEventV1(IntegrationEvent[str]):
    aggregate_id: str = ""
    session_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.min)

@cloudevent("io.lablet.lds.session.paused.v1")
@dataclass
class LdsSessionPausedIntegrationEventV1(IntegrationEvent[str]):
    aggregate_id: str = ""
    session_id: str = ""
    reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.min)

@cloudevent("io.lablet.lds.session.ended.v1")
@dataclass
class LdsSessionEndedIntegrationEventV1(IntegrationEvent[str]):
    aggregate_id: str = ""
    session_id: str = ""
    reason: str = ""
    ended_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.min)
```

### 3. Handler with Settings Toggle

The handler follows the established `assessment_events_handler.py` pattern:

- **Deduplication**: Uses `EventDeduplicationService` to prevent double-processing
- **Settings toggle**: `lds_cloudevent_enabled` flag to disable without code changes
- **State validation**: Only processes `READY → RUNNING`; logs warning for invalid states
- **Error handling**: Catches `InvalidStateTransitionError` gracefully

### 4. Configurable Event Parameters

Three new settings in `application/settings.py`:

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| `lds_cloudevent_source` | `LDS_CLOUDEVENT_SOURCE` | `https://labs.lcm.io` | Expected CloudEvent source URI |
| `lds_cloudevent_type_prefix` | `LDS_CLOUDEVENT_TYPE_PREFIX` | `io.lablet.lds` | CloudEvent type prefix for LDS events |
| `lds_cloudevent_enabled` | `LDS_CLOUDEVENT_ENABLED` | `true` | Feature toggle for LDS event processing |

## Rationale

### Why CPA and not lablet-controller for these events?

| Concern | lablet-controller (ADR-022) | control-plane-api (this ADR) |
|---------|---------------------------|------------------------------|
| Aggregate access | ❌ Via REST API (extra hop) | ✅ Direct repository access |
| External calls needed | ✅ (GradingSPI, LabDeliverySPI) | ❌ Not needed for simple transitions |
| Domain event emission | ❌ Manual (REST call to CPA) | ✅ Automatic (aggregate save → domain events → SSE) |
| Latency | Higher (REST call chain) | Lower (direct MongoDB) |
| ADR-015 compliance | N/A | ✅ No external calls |

The critical advantage is that when CPA handles `mark_running()` directly, the aggregate emits domain events which automatically trigger SSE handlers — the UI receives the status change in real-time without any additional wiring.

### Why not move ALL CloudEvent handlers to CPA?

Complex handlers (e.g., `grading.session.completed`) need to call GradingSPI, which is forbidden in CPA per ADR-015. The dual routing model preserves ADR-022's principles while allowing simple transitions to take the most efficient path.

## Consequences

### Positive

- **READY → RUNNING gap closed**: Sessions now transition when the user logs in via LDS
- **Lower latency**: Direct aggregate mutation vs. REST API chain
- **Automatic SSE propagation**: Domain events from aggregate save flow through existing SSE handlers
- **Feature toggle**: Can disable LDS event processing per-environment
- **Deduplication**: Prevents double-processing of retried CloudEvents

### Negative

- **Split routing**: CloudEvent handlers now live in two services, increasing cognitive load
- **Routing complexity**: Event producers must know which service handles which event types

### Risks

- **Routing misconfiguration**: If a complex event is accidentally routed to CPA, it will fail (no external service access). Mitigated by explicit `@cloudevent` type registration.

## Implementation Notes

### Files Created

| File | Purpose |
|------|---------|
| `application/events/integration/lds_events.py` | 3 `@cloudevent` integration event classes |
| `application/events/integration/lds_events_handler.py` | Handler with deduplication + settings toggle |
| `tests/application/test_lds_events_handler.py` | 9 unit tests |

### Files Modified

| File | Change |
|------|--------|
| `application/settings.py` | Added `lds_cloudevent_source`, `lds_cloudevent_type_prefix`, `lds_cloudevent_enabled` |

### Testing

- 9 new unit tests: happy path, not found, wrong state, deduplication, disabled toggle, invalid transition, session_id fallback
- Full suite: 1142 passed (9 new + 1133 existing), no regressions

### Event Source Configuration

LDS must be configured to send `session.running.v1`, `session.paused.v1`, and `session.ended.v1` CloudEvents to CPA's CloudEvent endpoint:

```bash
# For simple state transitions (handled by CPA directly)
CPA_CLOUDEVENT_ENDPOINT=http://control-plane-api:8000/

# For complex orchestration events (handled by lablet-controller)
LC_CLOUDEVENT_ENDPOINT=http://lablet-controller:8003/api/events
```

## Related Documents

- [ADR-022: CloudEvent Ingestion via Lablet-Controller](./ADR-022-cloudevent-ingestion-lablet-controller.md)
- [ADR-018: Lab Delivery System Integration](./ADR-018-lds-integration.md)
- [Control Plane API Architecture](../components/control-plane-api/index.md)
- [LabletSession Lifecycle Flow](../lablet-session-lifecycle-flow.md)
