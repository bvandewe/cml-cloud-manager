# ADR-026: Extensible Upstream Notifier Pattern (Deferred)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-02-25 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-023](./ADR-023-content-sync-trigger.md) (Content Sync Trigger), [ADR-018](./ADR-018-lds-integration.md) (LDS Integration) |
| **Implementation** | [Content Synchronization Plan](../../implementation/content_synchronization.md) §2 (AD-CS-004), Appendix C |

## Context

After content synchronization downloads a package from Mosaic and stores it in RustFS, upstream services must be notified so they can update their own state:

| Service | Notification Purpose | API |
|---------|---------------------|-----|
| **LDS** (Lab Delivery System) | Refresh content package reference for the form | `POST /api/content/sync` |
| **Grading Engine** | Sync grading toolkit for the form | `POST /api/v1/grading-toolkit/synchronize` |
| **Pod Automator** (future) | Update pod definitions | TBD |
| **Variables Generator** (future) | Update variable templates | TBD |

A design question arose: should we build a generic, template-based notifier plugin system now, or implement direct service calls and evolve later?

### Template-Based Pattern (Deferred Design)

The content synchronization plan envisions three template types that would eventually define how definitions interact with external services:

- `lablet_synchronization_template` — content sync notifications
- `lablet_initialization_template` — session creation instructions
- `lablet_evaluation_template` — grading/evaluation instructions

Each template would be a declarative spec (stored on the LabletDefinition) that the lablet-controller interprets at runtime, enabling zero-code addition of new upstream services.

## Decision

### 1. Direct Calls for Known Services (Now)

Implement LDS and Grading Engine notifications as direct method calls within `ContentSyncService.notify_upstream_services()`:

```python
async def _notify_upstream_services(self, defn: dict, metadata: dict) -> dict:
    """Notify known upstream services after content sync.

    Returns status dict: {"lds": {...}, "grading_engine": {...}}
    """
    upstream_status = {}

    # LDS notification
    try:
        result = await self._lds.sync_content(fqn, region=user_session_default_region)
        upstream_status["lds"] = {"status": "success", ...}
    except Exception as e:
        upstream_status["lds"] = {"status": "failed", "error": str(e)}

    # Grading Engine notification (when implemented)
    # try:
    #     result = await self._grading.sync_toolkit(fqn, ...)
    #     upstream_status["grading_engine"] = {"status": "success", ...}
    # except Exception as e:
    #     upstream_status["grading_engine"] = {"status": "failed", ...}

    return upstream_status
```

### 2. Template-Based Notifier Pattern (Deferred)

Defer the full template-based notifier plugin system until:

- A third upstream service (pod-automator or variables-generator) has a defined API
- The pattern for all three template types is validated with real use cases

### 3. Code Structure for Evolution

Structure the code to make the transition straightforward:

- All upstream notifications are isolated in a single method (`_notify_upstream_services`)
- Each service notification is independent (failure in one does not block others)
- Results are collected as a status dict and stored on the definition
- Service-specific logic is delegated to dedicated SPI clients (not inline HTTP calls)

## Rationale

### Why defer the template-based pattern?

- **Known services have defined APIs**: LDS and Grading Engine APIs are well-documented. Direct integration is simpler and more testable.
- **Unknown services have unknown APIs**: Pod Automator and Variables Generator APIs are not yet specified. Building a generic framework against hypothetical contracts risks over-engineering.
- **YAGNI**: Two services do not justify a plugin system. The third service will validate whether a pattern is needed.
- **Easy to refactor**: The isolated `_notify_upstream_services` method can be replaced with a template interpreter when the time comes.

### Why not build the template system now?

- Speculative abstraction often leads to wrong abstractions
- Testing a generic notifier requires mocking unknown service contracts
- Development time is better spent on the critical sync pipeline

### Why not skip upstream notification entirely?

- LDS sync is a hard requirement — content must be available before sessions can be created
- Grading Engine sync is needed for evaluation to work correctly
- Both services expect to be notified when content changes

## Consequences

### Positive

- Simpler initial implementation (direct calls, no abstraction layer)
- Faster delivery of the content sync feature
- Well-tested integration with known APIs (LDS, Grading Engine)
- Clean refactoring path when the third service arrives

### Negative

- Adding a new upstream service requires code changes (new SPI client + notify call)
- No declarative configuration of upstream services (must be coded)

### Risks

- If many upstream services emerge quickly, the direct-call pattern may become unwieldy (mitigated: refactor to template pattern at that point)

## Future Direction

When the third upstream service is identified:

1. Define the template schema (`lablet_synchronization_template`)
2. Implement a `SyncNotifierRegistry` that interprets templates
3. Migrate LDS and Grading Engine to template-based definitions
4. Store templates on the LabletDefinition aggregate

## Related Documents

- [Content Synchronization Implementation Plan](../../implementation/content_synchronization.md) — Appendix C
- [ADR-018: LDS Integration](./ADR-018-lds-integration.md)
