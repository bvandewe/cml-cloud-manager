# ADR-027: Version Auto-Increment on Content Change

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-02-25 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-023](./ADR-023-content-sync-trigger.md) (Content Sync Trigger), [ADR-028](./ADR-028-definition-initial-status.md) (Definition Initial Status) |
| **Implementation** | [Content Synchronization Plan](../../implementation/content_synchronization.md) §2 (AD-CS-005), §4.3 |

## Context

LabletDefinitions are designed as immutable versioned entities — once a definition is ACTIVE and in use by LabletSessions, its content (UserSession content, CML topology, grading rules, device definitions) should not change underneath running sessions.

However, the upstream Mosaic authoring platform may republish content for the same form at any time. When `ContentSyncService` re-syncs an ACTIVE definition and detects a different `content_package_hash`, the system must handle the content change without disrupting existing sessions.

Three strategies were considered:

1. **In-place update**: Overwrite the existing definition's content (breaks immutability)
2. **Version auto-increment**: Create a new version of the definition, deprecate the old one
3. **Manual re-creation**: Require the user to manually create a new definition version

## Decision

### 1. Auto-Increment on Content Change

When content sync detects a new `content_package_hash` on an already-ACTIVE definition:

1. **Deprecate** the current definition (set `status=DEPRECATED`, record reason)
2. **Clone** the definition into a new version with the patch component incremented
3. **Apply** the new content metadata to the cloned definition
4. **Activate** the new definition (it will be ACTIVE with the fresh content)

```
Re-sync ACTIVE definition (hash changed):
  v1.0.0 (ACTIVE, old hash) → v1.0.0 (DEPRECATED, reason: "Content updated")
  → v1.0.1 (ACTIVE, new hash) created automatically
```

### 2. Version Increment Rules

| Current Version | New Version | Rule |
|----------------|-------------|------|
| `1.0.0` | `1.0.1` | Patch increment (semver) |
| `2.3.7` | `2.3.8` | Patch increment |
| `1.0` | `1.1` | Minor increment (2-part fallback) |
| `1` | `1.1` | Append `.1` (1-part fallback) |

### 3. First Sync (No Change Detection)

When a PENDING_SYNC definition is synced for the first time, no version increment occurs. The content is simply recorded and the status transitions to ACTIVE:

```
First sync:
  v1.0.0 (PENDING_SYNC, no hash) → v1.0.0 (ACTIVE, hash recorded)
```

### 4. Same Hash (No Change)

When re-sync produces the same `content_package_hash`, no action is taken beyond updating the `synced_at` timestamp. The definition remains ACTIVE at its current version.

## Rationale

### Why auto-increment (not in-place update)?

- **Immutability**: Running LabletSessions reference a specific definition version. Changing content under them would be unsafe (topology changes, grading rule changes).
- **Auditability**: Version history shows exactly when and why content changed.
- **Rollback**: The old version remains in the system (DEPRECATED, not deleted) and can be restored if needed.
- **Session isolation**: Sessions created before the change continue using v1.0.0. New sessions use v1.0.1.

### Why not manual re-creation?

- Requires user intervention for every Mosaic republish (high friction)
- Users may not know when Mosaic content has changed
- Auto-detection during re-sync is a natural trigger point

### Why patch increment (not major/minor)?

- Content republishes are typically bug fixes or minor updates (not breaking changes)
- Patch increment signals "compatible update" in semver conventions
- Users can override the version string on the new definition if they want a different number

### Deprecation linkage

The deprecated definition stores:

- `deprecation_reason`: Human-readable explanation (e.g., "Content updated (new hash: abc123...)")
- `replacement_version`: Pointer to the new version (e.g., "1.0.1")

This enables the UI to show "This version was superseded by v1.0.1" with a direct link.

## Consequences

### Positive

- Preserves immutability guarantee for running sessions
- Automatic handling of upstream content changes (no user intervention for routine updates)
- Full audit trail of content versions
- Clean deprecation linkage for UI navigation

### Negative

- Version proliferation if Mosaic republishes frequently (mitigated: only triggers on hash change)
- Two definitions momentarily exist during the transition (old DEPRECATED + new ACTIVE)
- Definition cloning must handle all fields correctly (test coverage critical)

### Risks

- Race condition: two concurrent syncs could create duplicate versions (mitigated: `sync_status` acts as a lock — only one sync runs at a time per definition)
- Clone field omission: a new field added to LabletDefinitionState but not included in the clone logic (mitigated: explicit field mapping in `create_version()`, enforced by tests)

## Related Documents

- [Content Synchronization Implementation Plan](../../implementation/content_synchronization.md) — §4.3 `RecordContentSyncResultCommand`
- [ADR-028: Definition Initial Status](./ADR-028-definition-initial-status.md)
