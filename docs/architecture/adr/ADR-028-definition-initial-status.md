# ADR-028: LabletDefinition Initial Status (PENDING_SYNC)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-02-25 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-023](./ADR-023-content-sync-trigger.md) (Content Sync Trigger), [ADR-027](./ADR-027-content-version-auto-increment.md) (Version Auto-Increment) |
| **Implementation** | [Content Synchronization Plan](../../implementation/content_synchronization.md) §2 (AD-CS-006), §3 (Phase 1) |

## Context

LabletDefinitions go through a lifecycle from creation to active use in LabletSessions. The content synchronization feature introduces a new constraint: definitions must have their content package downloaded from Mosaic and stored in RustFS before they can be used for session creation.

This raises the question of what status a newly created definition should have, and what controls should apply before content is synchronized.

### Current Status Enum

The existing `LabletDefinitionStatus` includes:

- `ACTIVE` — Definition is ready for use
- `DEPRECATED` — Definition has been superseded (still usable for existing sessions)
- `DELETED` — Soft-deleted (not usable)

### Problem

If new definitions are created as `ACTIVE`, a LabletSession could be scheduled against a definition that has no content in RustFS, causing session instantiation failure (no `SVN.zip` to deliver to LDS).

## Decision

### 1. New Status: PENDING_SYNC

Add `PENDING_SYNC` to `LabletDefinitionStatus`:

```python
class LabletDefinitionStatus(str, Enum):
    PENDING_SYNC = "PENDING_SYNC"   # NEW: Created, awaiting content sync
    ACTIVE = "ACTIVE"                # Ready for LabletSession creation
    DEPRECATED = "DEPRECATED"        # Superseded by newer version
    DELETED = "DELETED"              # Soft-deleted
```

### 2. Creation → PENDING_SYNC

All new definitions are created with `status = PENDING_SYNC`:

```
CreateLabletDefinitionCommand → LabletDefinition.create()
  → status = PENDING_SYNC
  → sync_status = None (not yet requested)
```

### 3. PENDING_SYNC Permissions

| Operation | Allowed on PENDING_SYNC? | Notes |
|-----------|-------------------------|-------|
| Edit (update fields) | ✅ Yes | Users can refine definition before sync |
| Synchronize (trigger sync) | ✅ Yes | User must explicitly click "Synchronize" |
| Create LabletSession | ❌ No | Blocked — no content available |
| Deprecate | ✅ Yes | User can abandon before sync |
| Delete | ✅ Yes | User can discard |

### 4. Status Transitions

```
PENDING_SYNC → (user triggers sync) → sync_status=sync_requested
  → (content sync succeeds) → ACTIVE
  → (content sync fails) → PENDING_SYNC (with error, can retry)

ACTIVE → (re-sync detects change) → DEPRECATED
  → new version created as ACTIVE (see ADR-027)

ACTIVE → (user deprecates) → DEPRECATED
ACTIVE → (user deletes) → DELETED
PENDING_SYNC → (user deletes) → DELETED
```

### 5. Session Creation Guard

The `CreateLabletSessionCommand` handler must validate:

```python
if definition.state.status != LabletDefinitionStatus.ACTIVE:
    return self.bad_request(
        f"Definition '{definition.state.name}' v{definition.state.version} "
        f"is {definition.state.status.value} — only ACTIVE definitions can be used"
    )
```

## Rationale

### Why PENDING_SYNC (not DRAFT)?

- `PENDING_SYNC` clearly communicates what the definition is waiting for (content synchronization)
- `DRAFT` implies the user is still editing, which is a separate concern (editing is allowed in PENDING_SYNC)
- The name aligns with the sync pipeline terminology used throughout the system

### Why not auto-sync on creation?

- Content sync requires a `form_qualified_name` which must resolve in Mosaic — this may fail
- Users may want to configure all fields before triggering sync
- Sync involves external network calls (Mosaic, RustFS) that could be slow or fail
- Explicit sync gives users control over timing and retry

### Why block session creation (not warn)?

- A session without content in RustFS will fail at instantiation (LDS cannot find `SVN.zip`)
- Allowing creation and deferring the error creates a confusing user experience
- Hard blocking is consistent with the existing validation pattern in `CreateLabletSessionCommandHandler`

### Why allow edits in PENDING_SYNC?

- Users may create a definition, realize a field is wrong, and want to fix it before sync
- No content has been downloaded yet, so there's no consistency concern
- Reduces friction — no need to delete and recreate to fix a typo

## Consequences

### Positive

- Prevents session creation against unsynchronized definitions (eliminates a class of runtime failures)
- Clear lifecycle: PENDING_SYNC → ACTIVE → DEPRECATED/DELETED
- User retains full control (edit before sync, explicit sync trigger)
- Consistent with the sync pipeline flow (definition must have content before use)

### Negative

- Adds a state to the lifecycle (increased status management complexity)
- Users must take an explicit action (click "Synchronize") after creation
- UI must display the PENDING_SYNC status clearly and guide users to the sync action

### Risks

- User confusion: "Why can't I create a session?" (mitigated: clear error message with status and guidance)
- Stale PENDING_SYNC definitions: users create but never sync (mitigated: UI can show a warning, and admins can clean up via list filter)

## Related Documents

- [Content Synchronization Implementation Plan](../../implementation/content_synchronization.md) — §3 (Phase 1)
- [ADR-023: Content Sync Trigger](./ADR-023-content-sync-trigger.md)
- [ADR-027: Version Auto-Increment on Content Change](./ADR-027-content-version-auto-increment.md)
