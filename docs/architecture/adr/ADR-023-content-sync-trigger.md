# ADR-023: Content Sync Trigger via Reactive etcd Watch + Opt-In Polling

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-02-25 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-005](./ADR-005-state-store-architecture.md) (Dual State Store), [ADR-015](./ADR-015-control-plane-api-no-ec2.md) (CPA No External Calls), [ADR-017](./ADR-017-lab-operations-via-lablet-controller.md) (Lab Operations via Lablet-Controller) |
| **Extends** | ADR-005 (etcd key namespace), ADR-017 (reconciliation pattern) |
| **Implementation** | [Content Synchronization Plan](../../implementation/content_synchronization.md) §1.3, §4.2, §4.6, §6.1 |

## Context

LabletDefinitions reference content packages authored in Mosaic (an external content authoring platform). When a user creates or updates a definition, the content must be downloaded from Mosaic, stored in RustFS (S3-compatible object storage), and metadata extracted for use during LabletSession instantiation.

The system needs a mechanism for the lablet-controller's `ContentSyncService` to learn that a definition requires content synchronization. Three options were considered:

1. **Polling only**: lablet-controller polls CPA internal API for definitions with `sync_status=sync_requested`
2. **Reactive etcd watch**: CPA emits a domain event → etcd projector writes a key → lablet-controller watches the prefix and reacts immediately
3. **CloudEvent webhook**: CPA sends a CloudEvent to lablet-controller when sync is requested

### Established Pattern

The codebase already uses reactive etcd watches as the primary reconciliation trigger for all controller operations:

| Feature | etcd Key Pattern | Writer (CPA Projector) | Watcher (Controller) |
|---------|-----------------|----------------------|---------------------|
| Worker desired state | `/lcm/workers/{id}/desired_state` | `CMLWorkerDesiredStatusUpdatedEtcdProjector` | worker-controller |
| Session state | `/lcm/sessions/{id}/state` | `SessionStateEtcdProjector` | lablet-controller |
| Lab pending action | `/lcm/lab_records/{id}/pending_action` | `LabActionRequestedEtcdProjector` | `LabRecordReconciler` |
| **Content sync (NEW)** | `/lcm/definitions/{id}/content_sync` | `ContentSyncRequestedEtcdProjector` | `ContentSyncService` |

The `LabRecordReconciler` (ADR-017) is the most directly analogous pattern: a standalone watcher class (not a HostedService) with lifecycle managed by `LabletReconciler`, using exponential backoff reconnection and PUT-only event handling.

## Decision

### 1. Reactive etcd Watch as Primary Trigger

When a user requests content synchronization, the CPA follows this reactive flow:

```
User → "Synchronize" → CPA SyncLabletDefinitionCommand
  → sets sync_status="sync_requested" in MongoDB
  → emits LabletDefinitionSyncRequestedDomainEvent
  → ContentSyncRequestedEtcdProjector writes /lcm/definitions/{id}/content_sync
  → lablet-controller ContentSyncService._watch_loop() reacts immediately
  → executes sync pipeline
  → reports results to CPA via internal API
  → CPA emits LabletDefinitionContentSyncedDomainEvent
  → ContentSyncCompletedEtcdProjector DELETES the etcd key (cleanup)
```

### 2. etcd Key Convention

```
/lcm/definitions/{definition_id}/content_sync
```

Payload (JSON):

```json
{
  "definition_id": "def-abc-123",
  "form_qualified_name": "Exam Associate CCNA v1.1 LAB 1.3a",
  "bucket_name": "exam-associate-ccna-v1.1-lab-1.3a",
  "user_session_package_name": "SVN.zip",
  "requested_by": "user@example.com",
  "requested_at": "2026-02-25T10:00:00Z"
}
```

### 3. CPA-Side Components

| Component | File | Purpose |
|-----------|------|---------|
| `LabletDefinitionSyncRequestedDomainEvent` | `domain/events/lablet_definition_events.py` | Emitted by `SyncLabletDefinitionCommandHandler` |
| `LabletDefinitionContentSyncedDomainEvent` | `domain/events/lablet_definition_events.py` | Emitted by `RecordContentSyncResultCommandHandler` |
| `EtcdStateStore.DEFINITION_CONTENT_SYNC_KEY` | `integration/services/etcd_state_store.py` | Key template: `/definitions/{id}/content_sync` |
| `EtcdStateStore.set_definition_content_sync()` | `integration/services/etcd_state_store.py` | Writes etcd key with JSON payload |
| `EtcdStateStore.delete_definition_content_sync()` | `integration/services/etcd_state_store.py` | Deletes etcd key (cleanup) |
| `ContentSyncRequestedEtcdProjector` | `application/events/domain/etcd_state_projector.py` | DomainEventHandler → writes key |
| `ContentSyncCompletedEtcdProjector` | `application/events/domain/etcd_state_projector.py` | DomainEventHandler → deletes key |

### 4. Lablet-Controller ContentSyncService

Follows the `LabRecordReconciler` pattern exactly:

- **Singleton** (not a HostedService) — lifecycle managed by `LabletReconciler._become_leader()` / `_step_down()`
- `_watch_loop()` with exponential backoff reconnection (1s → 30s max)
- `_handle_watch_event()` reacts to PUT events only
- `_get_watch_prefix()` → `{etcd_key_prefix}/definitions/`
- DI: `configure()` classmethod registers via factory

### 5. Opt-In Polling Fallback

Polling is available as an additional consistency measure, disabled by default:

| Setting | Default | Purpose |
|---------|---------|---------|
| `CONTENT_SYNC_WATCH_ENABLED` | `true` | Primary: reactive etcd watch |
| `CONTENT_SYNC_POLL_ENABLED` | `false` | Fallback: periodic poll (opt-in) |
| `CONTENT_SYNC_POLL_INTERVAL` | `300` | Seconds between polls (if enabled) |

When enabled, the poll loop queries `GET /api/internal/lablet-definitions?sync_status=sync_requested` and processes any definitions missed during etcd watch reconnection gaps.

## Rationale

### Why reactive etcd watch (not polling-only)?

- **Consistency**: All existing controller reconciliation uses etcd watches as primary trigger
- **Low latency**: Sub-second reaction time vs. polling interval delay
- **Proven pattern**: `LabRecordReconciler`, worker desired state, session state all use this approach
- **Clean lifecycle**: etcd key is created on request and deleted on completion — self-documenting

### Why opt-in polling (not mandatory)?

- **Edge case coverage**: etcd watch reconnection gaps could miss events
- **Startup catch-up**: New leader may have pending sync requests from before election
- **Minimal overhead**: 300s interval with simple HTTP query when enabled

### Why not CloudEvent webhook?

- Adds a reverse dependency (CPA → lablet-controller)
- CloudEvents are used for external system integration (LDS, GradingEngine), not internal coordination
- etcd watches are the established internal coordination mechanism

### Why not polling-only?

- Inconsistent with the architecture — all other reconciliation uses etcd watches
- Higher latency (minimum one poll interval)
- Unnecessary load from frequent polling

## Consequences

### Positive

- Consistent with all existing controller reconciliation patterns
- Immediate reaction to sync requests (sub-second via etcd watch)
- Self-cleaning: etcd key lifecycle mirrors the sync lifecycle
- Polling fallback provides defense-in-depth for data consistency
- Pattern is well-understood by the team (identical to `LabRecordReconciler`)

### Negative

- Two code paths (watch + optional poll) increase testing surface
- etcd becomes a dependency for content sync flow (already a dependency for all reconciliation)
- Additional etcd key namespace to manage

### Risks

- etcd unavailability blocks immediate sync (mitigated by opt-in polling fallback)
- Key cleanup failure could leave stale keys (mitigated by ContentSyncCompletedEtcdProjector)

## Related Documents

- [Content Synchronization Implementation Plan](../../implementation/content_synchronization.md)
- [ADR-005: Dual State Store Architecture](./ADR-005-state-store-architecture.md)
- [ADR-017: Lab Operations via Lablet-Controller](./ADR-017-lab-operations-via-lablet-controller.md)
