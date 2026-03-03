# Content Synchronization Implementation Plan

**Status**: In Progress
**Created**: 2026-02-25
**Last Updated**: 2026-02-25
**Author**: AI Architect (lcm-senior-architect)
**Scope**: LabletDefinition content synchronization — end-to-end from Mosaic authoring platform through RustFS object storage to upstream service notification.

### Implementation Progress

| Phase | Scope | Status | Completed |
|-------|-------|--------|-----------|
| **Phase 1** | Domain model (lcm-core + CPA entities, events, DTOs) | ✅ Complete | 2026-02-25 |
| **Phase 2** | CPA commands, internal API, controller updates | ✅ Complete | 2026-02-25 |
| **Phase 3** | Integration clients (S3, EnvResolver, Mosaic, LDS, OAuth2) | ✅ Complete | 2026-02-25 |
| **Phase 4** | ContentSyncService + LabletReconciler integration | ✅ Complete | 2026-02-25 |
| **Phase 5** | UI changes (sync button, form updates, status badges) | ⬜ Not started | — |
| **Phase 6** | Keycloak scope + authorization | ⬜ Not started | — |
| **Phase 7** | Tests | ⬜ Not started | — |
| **Phase 8** | Documentation & env config | ⬜ Not started | — |

> **Phases 1–4 complete.** Next up: Phase 5 (UI changes).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture Decision Records](#2-architecture-decision-records)
3. [Phase 1: Domain Model Expansion (lcm-core + CPA)](#3-phase-1-domain-model-expansion)
4. [Phase 2: CPA Internal API & Sync Trigger (control-plane-api)](#4-phase-2-cpa-internal-api--sync-trigger)
5. [Phase 3: Integration Clients (lablet-controller)](#5-phase-3-integration-clients)
6. [Phase 4: Content Sync Service (lablet-controller)](#6-phase-4-content-sync-service)
7. [Phase 5: UI Changes (control-plane-api)](#7-phase-5-ui-changes)
8. [Phase 6: Keycloak & Authorization](#8-phase-6-keycloak--authorization)
9. [Phase 7: Testing](#9-phase-7-testing)
10. [Phase 8: Documentation](#10-phase-8-documentation)
11. [Appendix A: Sample Data](#appendix-a-sample-data)
12. [Appendix B: API Endpoint Reference](#appendix-b-api-endpoint-reference)
13. [Appendix C: Upstream Notifier Pattern (Deferred)](#appendix-c-upstream-notifier-pattern-deferred)

---

## 1. Overview

### 1.1 User Story

> As an authenticated and authorized User (with `content:rw` scope, `track_acronym: AUTO` in JWT),
> I want to create a new LabletDefinition and trigger on-demand content synchronization based on
> the `form_qualified_name` so that the content package is downloaded from Mosaic, stored in RustFS,
> and upstream services (LDS, Grading Engine, etc.) are notified.

### 1.2 High-Level Flow

```
User → CPA UI "Create Definition" → CPA stores definition (status: PENDING_SYNC)
User → CPA UI "Synchronize" button → CPA SyncLabletDefinitionCommand
  → sets sync_status="sync_requested" in MongoDB
  → emits LabletDefinitionSyncRequestedDomainEvent
  → etcd projector writes /lcm/definitions/{id}/content_sync (reactive notification)

lablet-controller ContentSyncService (watch-based, leader-only):
  PRIMARY: watches etcd /definitions/ prefix → immediate reaction on PUT event
  FALLBACK (opt-in): polls CPA internal API for sync_requested definitions
  → orchestrates content sync pipeline:
    1. Resolve Mosaic base URL via Environment Resolver
    2. Get latest publish records from Mosaic
    3. Download content package (zip) from Mosaic
    4. Compute package hash (SHA-256 of entire zip)
    5. Extract metadata (mosaic_meta.json, cml.yaml path, grade.xml path, devices.json)
    6. Upload package archive to RustFS bucket as configured package name (default: "SVN.zip")
    7. Notify upstream services (LDS sync, Grading Engine sync — extensible pattern)
    8. Report sync result to CPA (via internal API)
  → CPA records result → status transitions to ACTIVE
  → CPA emits ContentSyncedDomainEvent → projector DELETES etcd key
```

### 1.3 Sync Trigger Mechanism (AD-CS-001)

**Decision**: Reactive etcd watch (primary) + opt-in polling (consistency fallback).
Follows the established AD-023 `LabRecordReconciler` pattern exactly.

**Rationale**: The codebase already uses reactive etcd watches for immediate reconciliation
(worker desired_state, session state, lab pending_action). Content sync must follow the same
pattern for consistency and low-latency response. Polling is an opt-in fallback for edge cases
(etcd watch reconnection gaps, startup catch-up).

**Reactive Flow (primary — etcd watch)**:

1. User clicks "Synchronize" in UI → CPA API `POST /api/lablet-definitions/{id}/sync`
2. CPA `SyncLabletDefinitionCommandHandler`:
   a. Sets `sync_status = "sync_requested"` on the definition (MongoDB)
   b. Emits `LabletDefinitionSyncRequestedDomainEvent`
   c. Returns 202 Accepted
3. `ContentSyncRequestedEtcdProjector` handles the domain event:
   → Writes `/lcm/definitions/{id}/content_sync` to etcd (JSON payload with FQN, bucket, etc.)
4. lablet-controller `ContentSyncService` watches `/lcm/definitions/` prefix:
   → Receives PUT event immediately
   → Parses definition ID and payload from etcd key/value
   → Fetches full definition from CPA internal API
   → Executes the sync orchestration pipeline
5. On completion, calls `POST /api/internal/lablet-definitions/{id}/content-synced` with results
6. CPA `RecordContentSyncResultCommandHandler`:
   a. Updates definition state (hash, metadata, status → ACTIVE)
   b. Emits `LabletDefinitionContentSyncedDomainEvent`
7. `ContentSyncCompletedEtcdProjector` handles the synced event:
   → **DELETES** `/lcm/definitions/{id}/content_sync` from etcd (cleanup)

**Polling Flow (opt-in fallback — disabled by default)**:

1. ContentSyncService optionally runs a periodic poll task
2. Polls `GET /api/internal/lablet-definitions?sync_status=sync_requested`
3. For each result, executes the same orchestration pipeline
4. Catches definitions that may have been missed during watch reconnection

**etcd Key Convention**:

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

### 1.4 Form Qualified Name (FQN)

**Format**: `"{trackType} {trackLevel} {trackAcronym} {examVersion} {moduleAcronym} {formName}"`

- 6 alphanumeric components separated by single space
- Allowed characters: `[a-zA-Z0-9. ]`
- Example: `"Exam Associate CCNA v1.1 LAB 1.3a"`

**Slugification** (for S3 bucket name):

- Convert to lowercase
- Replace spaces with dashes
- Example: `"Exam Associate CCNA v1.1 LAB 1.3a"` → `"exam-associate-ccna-v1.1-lab-1.3a"`
- Result must be a valid S3 bucket name

---

## 2. Architecture Decision Records

### AD-CS-001: Sync Trigger via Reactive etcd Watch + Opt-In Polling

> **Formal ADR**: [ADR-023](../architecture/adr/ADR-023-content-sync-trigger.md)

- **Decision**: CPA emits `LabletDefinitionSyncRequestedDomainEvent` → etcd projector writes `/lcm/definitions/{id}/content_sync`. lablet-controller's `ContentSyncService` watches the `/lcm/definitions/` prefix for immediate reaction. Polling is opt-in (`CONTENT_SYNC_POLL_ENABLED=false` by default) as a consistency fallback.
- **Rationale**: Follows the established AD-023 `LabRecordReconciler` reactive pattern exactly. All existing controller reconciliation uses etcd watches as primary trigger (worker desired_state, session state, lab pending_action). Content sync must be consistent with this architecture. Polling catches edge cases during etcd reconnection gaps.
- **Alternatives rejected**: Polling-only (inconsistent with architecture, higher latency), CloudEvent webhook (adds complexity), direct HTTP to lablet-controller (reverse dependency).
- **Pattern reference**: `LabActionRequestedEtcdProjector` → `LabRecordReconciler._watch_loop()` → `LabActionCompletedEtcdProjector` (delete key).

### AD-CS-002: Package Storage in RustFS

> **Formal ADR**: [ADR-024](../architecture/adr/ADR-024-content-package-storage.md)

- **Decision**: Upload the package archive (zip) to the root of the slugified-FQN bucket with a configurable filename (default `"SVN.zip"`). Do NOT extract content into the bucket.
- **Rationale**: LDS expects `SVN.zip` at the bucket root. Extracted content (cml.yaml, devices.json) is stored in MongoDB via the LabletDefinition state for internal use during LabletSession instantiation.
- **Bucket structure**:

  ```
  <slugified-fqn>/         # bucket name
  └── SVN.zip              # configurable filename (user_session_package_name)
  ```

### AD-CS-003: Content Metadata in MongoDB (Not S3)

> **Formal ADR**: [ADR-025](../architecture/adr/ADR-025-content-metadata-storage.md)

- **Decision**: Extract cml.yaml content, devices.json content, grade.xml path, and mosaic_meta.json fields from the downloaded zip, then store them as fields on the LabletDefinition aggregate state in MongoDB.
- **Rationale**: Simpler than managing extracted files in S3. The lablet-controller already needs this data during LabletSession instantiation (cml.yaml for lab import, devices for LDS session).

### AD-CS-004: Extensible Upstream Notifier Pattern (Deferred)

> **Formal ADR**: [ADR-026](../architecture/adr/ADR-026-upstream-notifier-pattern.md)

- **Decision**: For now, implement LDS and Grading Engine sync as direct calls in ContentSyncService. Defer the full template-based notifier pattern (`lablet_synchronization_template`, `lablet_initialization_template`, `lablet_evaluation_template`) to a later phase.
- **Rationale**: The two known upstream services have well-defined APIs. Over-engineering a plugin system before the third/fourth service (pod-automator, variables-generator) APIs are known would be premature. The code will be structured with a `notify_upstream_services()` method that can evolve.

### AD-CS-005: Version Auto-Increment on Content Change

> **Formal ADR**: [ADR-027](../architecture/adr/ADR-027-content-version-auto-increment.md)

- **Decision**: When sync detects a new content hash, the current definition is deprecated and a cloned definition is created with patch-incremented version (e.g., `1.0.0` → `1.0.1`). The user can edit the new version before saving (including overriding the version string).
- **Rationale**: Maintains the immutability principle of LabletDefinitions. Existing sessions continue using the old definition. The user has full control over the final version string.

### AD-CS-006: Definition Initial Status

> **Formal ADR**: [ADR-028](../architecture/adr/ADR-028-definition-initial-status.md)

- **Decision**: New definitions are created with `status=PENDING_SYNC`. Users can edit PENDING_SYNC definitions without requiring sync. Users must manually trigger "Synchronize" to transition to ACTIVE. A PENDING_SYNC definition **cannot** be used for LabletSession creation.
- **Rationale**: Gives users control over when sync happens. Prevents sessions from referencing unsynchronized content.

---

## 3. Phase 1: Domain Model Expansion

> **✅ COMPLETED** (2026-02-25)
>
> All 7 sub-tasks implemented and tested. 69/69 CPA tests + 77/77 lcm-core tests passing. Lint clean.
>
> **Enhancements beyond spec:**
>
> - `port_template` field on `ContentSyncedDomainEvent` + `record_content_sync()` (ADR-029)
> - `PortTemplate.from_cml_nodes()` factory for CML YAML extraction
> - `lds_region` renamed to `user_session_default_region` across all layers
> - `LabletDefinitionSyncRequestedDomainEvent` (Phase 2 artifact) already implemented
> - `form_qualified_name` and `form_id` fields on `LabletDefinitionReadModel`

### 3.1 Add `PENDING_SYNC` to LabletDefinitionStatus Enum

**File**: `src/core/lcm_core/domain/enums/lablet_definition_status.py`

```python
"""Lablet definition status enum — shared across all services."""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class LabletDefinitionStatus(CaseInsensitiveStrEnum):
    """Status of a LabletDefinition."""

    PENDING_SYNC = "pending_sync"  # Created but not yet synchronized
    ACTIVE = "active"              # Definition is active and can be used
    DEPRECATED = "deprecated"      # Definition is deprecated, no new instances
    ARCHIVED = "archived"          # Definition is archived, historical only
```

**Impact**: All services importing this enum (CPA, lablet-controller, resource-scheduler) get the new status automatically since they depend on `lcm-core`.

### 3.2 Expand LabletDefinitionState

**File**: `src/control-plane-api/domain/entities/lablet_definition.py`

Add new fields to `LabletDefinitionState`:

```python
class LabletDefinitionState(AggregateState[str]):
    """Encapsulates the persisted state for the LabletDefinition aggregate."""

    # ... existing fields ...

    # --- NEW: Content synchronization metadata ---

    # Content identification (derived from form_qualified_name)
    bucket_name: str  # Slugified FQN, used as S3 bucket name

    # Package configuration (user-configurable, with defaults)
    user_session_package_name: str  # Filename in bucket for LDS (default: "SVN.zip")
    grading_ruleset_package_name: str  # Filename for grading rules (default: "SVN.zip")

    # User session type
    user_session_type: str  # "LDS" (default), extensible for future types
    user_session_default_region: str | None  # Default LDS region (e.g., "us-east-1"), None = use global default

    # Content metadata (populated by sync job)
    content_package_hash: str | None      # SHA-256 hash of the entire downloaded zip
    upstream_version: str | None          # "Version" field from mosaic_meta.json
    upstream_date_published: str | None   # "DatePublished" from mosaic_meta.json
    upstream_instance_name: str | None    # "InstanceName" from mosaic_meta.json (Mosaic instance)
    upstream_form_id: str | None          # "FormId" from mosaic_meta.json (Mosaic internal ref)
    grade_xml_path: str | None            # Relative path to grade.xml in the package
    cml_yaml_path: str | None             # Relative path to cml.yml/cml.yaml in the package
    cml_yaml_content: str | None          # Cached CML YAML content (for lab import)
    devices_json: str | None              # Cached devices.json content (serialized JSON string)

    # Upstream service sync tracking
    upstream_sync_status: dict | None     # Per-service sync status, e.g.:
    # {
    #   "lds": {"status": "success", "synced_at": "...", "version": "..."},
    #   "grading_engine": {"status": "success", "synced_at": "...", "version": "..."},
    # }
```

**Initialization in `__init__`** — add defaults:

```python
def __init__(self) -> None:
    super().__init__()
    # ... existing inits ...

    self.form_qualified_name = None

    # NEW fields
    self.bucket_name = ""
    self.user_session_package_name = "SVN.zip"
    self.grading_ruleset_package_name = "SVN.zip"
    self.user_session_type = "LDS"
    self.user_session_default_region = None

    self.content_package_hash = None
    self.upstream_version = None
    self.upstream_date_published = None
    self.upstream_instance_name = None
    self.upstream_form_id = None
    self.grade_xml_path = None
    self.cml_yaml_path = None
    self.cml_yaml_content = None
    self.devices_json = None
    self.upstream_sync_status = None
```

### 3.3 Update Domain Events

**File**: `src/control-plane-api/domain/events/lablet_definition_events.py`

#### 3.3.1 Expand `LabletDefinitionCreatedDomainEvent`

Add fields to the creation event:

```python
@dataclass
@cloudevent("lablet_definition.created.v1")
class LabletDefinitionCreatedDomainEvent(DomainEvent):
    """Event raised when a new LabletDefinition is created."""
    # ... existing fields ...
    form_qualified_name: str | None = None  # (already exists but ensure present)

    # NEW fields
    bucket_name: str = ""
    user_session_package_name: str = "SVN.zip"
    grading_ruleset_package_name: str = "SVN.zip"
    user_session_type: str = "LDS"
    user_session_default_region: str | None = None
```

#### 3.3.2 Expand `LabletDefinitionArtifactSyncedDomainEvent`

Rename and expand to carry full sync results:

```python
@dataclass
@cloudevent("lablet_definition.content_synced.v1")
class LabletDefinitionContentSyncedDomainEvent(DomainEvent):
    """Event raised when content synchronization completes for a LabletDefinition."""
    aggregate_id: str = ""
    lab_artifact_uri: str = ""
    lab_yaml_hash: str = ""
    synced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sync_status: str = ""  # "success" | "failed"
    error_message: str | None = None

    # NEW: content metadata from sync
    content_package_hash: str | None = None
    upstream_version: str | None = None
    upstream_date_published: str | None = None
    upstream_instance_name: str | None = None
    upstream_form_id: str | None = None
    grade_xml_path: str | None = None
    cml_yaml_path: str | None = None
    cml_yaml_content: str | None = None
    devices_json: str | None = None
    upstream_sync_status: dict | None = None  # Per-service results
```

#### 3.3.3 Update the `@dispatch` handler on `LabletDefinitionState`

In the state class, update the handler for the content synced event:

```python
@dispatch(LabletDefinitionContentSyncedDomainEvent)
def on(self, event: LabletDefinitionContentSyncedDomainEvent) -> None:
    """Apply the content sync event to the state."""
    self.last_synced_at = event.synced_at
    self.sync_status = event.sync_status
    self.lab_yaml_hash = event.lab_yaml_hash
    self.updated_at = event.synced_at

    # Content metadata
    if event.content_package_hash:
        self.content_package_hash = event.content_package_hash
    if event.upstream_version:
        self.upstream_version = event.upstream_version
    if event.upstream_date_published:
        self.upstream_date_published = event.upstream_date_published
    if event.upstream_instance_name:
        self.upstream_instance_name = event.upstream_instance_name
    if event.upstream_form_id:
        self.upstream_form_id = event.upstream_form_id
    if event.grade_xml_path:
        self.grade_xml_path = event.grade_xml_path
    if event.cml_yaml_path:
        self.cml_yaml_path = event.cml_yaml_path
    if event.cml_yaml_content:
        self.cml_yaml_content = event.cml_yaml_content
    if event.devices_json:
        self.devices_json = event.devices_json
    if event.upstream_sync_status:
        self.upstream_sync_status = event.upstream_sync_status

    # Transition from PENDING_SYNC to ACTIVE on successful sync
    if event.sync_status == "success" and self.status == LabletDefinitionStatus.PENDING_SYNC:
        self.status = LabletDefinitionStatus.ACTIVE
```

### 3.4 Update Aggregate Methods

**File**: `src/control-plane-api/domain/entities/lablet_definition.py`

#### 3.4.1 Update `create()` static factory

The `create()` method must:

- Accept `form_qualified_name` as **required** (no longer optional for content-sync definitions)
- Auto-derive `bucket_name` from slugified FQN
- Auto-derive `lab_artifact_uri` from `bucket_name` + `user_session_package_name`
- Accept new optional fields: `user_session_package_name`, `grading_ruleset_package_name`, `user_session_type`, `user_session_default_region`
- Set initial status to `PENDING_SYNC` (not `ACTIVE`)

```python
@staticmethod
def create(
    name: str,
    version: str,
    form_qualified_name: str,
    resource_requirements: ResourceRequirements,
    license_affinity: list[LicenseType],
    node_count: int,
    port_template: PortTemplate,
    created_by: str,
    # Optional content config
    user_session_package_name: str = "SVN.zip",
    grading_ruleset_package_name: str = "SVN.zip",
    user_session_type: str = "LDS",
    user_session_default_region: str | None = None,
    # Optional lab config (may be populated later by sync)
    lab_yaml_hash: str = "",
    lab_yaml_cached: str | None = None,
    grading_rules_uri: str | None = None,
    max_duration_minutes: int = 60,
    warm_pool_depth: int = 0,
    owner_notification: NotificationConfig | None = None,
) -> "LabletDefinition":
    """Create a new LabletDefinition in PENDING_SYNC status."""
    bucket_name = slugify_fqn(form_qualified_name)
    lab_artifact_uri = f"s3://{bucket_name}/{user_session_package_name}"

    definition = LabletDefinition()
    definition.state.on(
        definition.register_event(
            LabletDefinitionCreatedDomainEvent(
                aggregate_id=str(uuid4()),
                name=name,
                version=version,
                lab_artifact_uri=lab_artifact_uri,
                lab_yaml_hash=lab_yaml_hash,
                lab_yaml_cached=lab_yaml_cached,
                resource_requirements=resource_requirements.to_dict(),
                license_affinity=[lt.value for lt in license_affinity],
                node_count=node_count,
                port_template=port_template.to_dict(),
                grading_rules_uri=grading_rules_uri,
                max_duration_minutes=max_duration_minutes,
                warm_pool_depth=warm_pool_depth,
                owner_notification=owner_notification.to_dict() if owner_notification else None,
                created_by=created_by,
                created_at=datetime.now(timezone.utc),
                form_qualified_name=form_qualified_name,
                # NEW fields
                bucket_name=bucket_name,
                user_session_package_name=user_session_package_name,
                grading_ruleset_package_name=grading_ruleset_package_name,
                user_session_type=user_session_type,
                user_session_default_region=user_session_default_region,
            )
        )
    )
    return definition
```

#### 3.4.2 Add `slugify_fqn` utility

**File**: `src/control-plane-api/domain/utils.py` (new file)

```python
"""Domain utility functions."""

import re


def slugify_fqn(form_qualified_name: str) -> str:
    """Convert a Form Qualified Name to a valid S3 bucket name.

    FQN format: "{trackType} {trackLevel} {trackAcronym} {examVersion} {moduleAcronym} {formName}"
    Example: "Exam Associate CCNA v1.1 LAB 1.3a" → "exam-associate-ccna-v1.1-lab-1.3a"

    Rules:
    - Convert to lowercase
    - Replace spaces with dashes
    - Strip any characters not valid in S3 bucket names

    Args:
        form_qualified_name: The FQN string (6 space-separated components).

    Returns:
        A valid S3 bucket name string.

    Raises:
        ValueError: If the FQN is empty or invalid.
    """
    if not form_qualified_name or not form_qualified_name.strip():
        raise ValueError("form_qualified_name cannot be empty")

    slug = form_qualified_name.strip().lower()
    slug = slug.replace(" ", "-")
    # Remove any chars that aren't lowercase alphanumeric, dash, or dot
    slug = re.sub(r"[^a-z0-9.\-]", "", slug)
    # Collapse multiple dashes
    slug = re.sub(r"-{2,}", "-", slug)
    # Strip leading/trailing dashes
    slug = slug.strip("-")

    if not slug:
        raise ValueError(f"Slugified FQN is empty after processing: '{form_qualified_name}'")

    return slug
```

This utility should also be added to `lcm-core` so it's available to both CPA and lablet-controller:

**File**: `src/core/lcm_core/domain/utils.py` (same content)

#### 3.4.3 Update `record_content_sync()` method

Replace the existing `record_artifact_sync()` on the aggregate:

```python
def record_content_sync(
    self,
    lab_yaml_hash: str,
    sync_status: str,
    content_package_hash: str | None = None,
    upstream_version: str | None = None,
    upstream_date_published: str | None = None,
    upstream_instance_name: str | None = None,
    upstream_form_id: str | None = None,
    grade_xml_path: str | None = None,
    cml_yaml_path: str | None = None,
    cml_yaml_content: str | None = None,
    devices_json: str | None = None,
    upstream_sync_status: dict | None = None,
    error_message: str | None = None,
) -> None:
    """Record the result of a content synchronization operation."""
    self.state.on(
        self.register_event(
            LabletDefinitionContentSyncedDomainEvent(
                aggregate_id=self.id(),
                lab_artifact_uri=self.state.lab_artifact_uri,
                lab_yaml_hash=lab_yaml_hash,
                synced_at=datetime.now(timezone.utc),
                sync_status=sync_status,
                error_message=error_message,
                content_package_hash=content_package_hash,
                upstream_version=upstream_version,
                upstream_date_published=upstream_date_published,
                upstream_instance_name=upstream_instance_name,
                upstream_form_id=upstream_form_id,
                grade_xml_path=grade_xml_path,
                cml_yaml_path=cml_yaml_path,
                cml_yaml_content=cml_yaml_content,
                devices_json=devices_json,
                upstream_sync_status=upstream_sync_status,
            )
        )
    )
```

### 3.5 Update LabletDefinitionState `on(CreatedDomainEvent)` handler

Update the handler for the created event to apply the new fields and set initial status:

```python
@dispatch(LabletDefinitionCreatedDomainEvent)
def on(self, event: LabletDefinitionCreatedDomainEvent) -> None:
    """Apply the creation event to the state."""
    # ... existing field assignments ...
    self.form_qualified_name = event.form_qualified_name
    self.status = LabletDefinitionStatus.PENDING_SYNC  # ← changed from ACTIVE

    # NEW fields
    self.bucket_name = event.bucket_name
    self.user_session_package_name = event.user_session_package_name
    self.grading_ruleset_package_name = event.grading_ruleset_package_name
    self.user_session_type = event.user_session_type
    self.user_session_default_region = event.user_session_default_region
```

### 3.6 Update DTOs

**File**: `src/control-plane-api/application/dtos/lablet_definition_dto.py`

#### 3.6.1 Expand `LabletDefinitionDto`

```python
@dataclass
class LabletDefinitionDto:
    """Full DTO for single LabletDefinition retrieval."""
    # Identity
    id: str
    name: str
    version: str
    form_qualified_name: str | None        # NEW
    bucket_name: str                        # NEW

    # Artifact
    lab_artifact_uri: str
    lab_yaml_hash: str
    lab_yaml_cached: str | None

    # Resources
    resource_requirements: ResourceRequirementsDto
    license_affinity: list[str]
    node_count: int

    # Port configuration
    port_template: PortTemplateDto

    # Assessment
    grading_rules_uri: str | None
    max_duration_minutes: int

    # LDS / Content config
    user_session_package_name: str          # NEW
    grading_ruleset_package_name: str       # NEW
    user_session_type: str                  # NEW
    user_session_default_region: str | None                  # NEW

    # Warm pool
    warm_pool_depth: int

    # Status
    status: str
    previous_version_id: str | None

    # Content metadata (from sync)
    content_package_hash: str | None        # NEW
    upstream_version: str | None            # NEW
    upstream_date_published: str | None     # NEW
    upstream_instance_name: str | None      # NEW
    upstream_form_id: str | None            # NEW
    grade_xml_path: str | None              # NEW
    cml_yaml_path: str | None               # NEW
    upstream_sync_status: dict | None       # NEW

    # Deprecation
    deprecated_by: str | None
    deprecated_at: str | None
    deprecation_reason: str | None
    replacement_version: str | None

    # Sync status
    last_synced_at: str | None
    sync_status: str | None

    # Ownership
    created_by: str
    created_at: str
    updated_at: str
```

#### 3.6.2 Expand `LabletDefinitionSummaryDto`

```python
@dataclass
class LabletDefinitionSummaryDto:
    """Summary DTO for list queries."""
    id: str
    name: str
    version: str
    form_qualified_name: str | None         # NEW
    status: str
    sync_status: str | None                 # NEW
    node_count: int
    max_duration_minutes: int
    warm_pool_depth: int
    is_deprecated: bool
    created_at: str
    updated_at: str
```

#### 3.6.3 Update `map_lablet_definition_to_dto`

Add the new field mappings to the existing mapper function. The mapper must include:

```python
form_qualified_name=state.form_qualified_name,
bucket_name=state.bucket_name,
user_session_package_name=state.user_session_package_name,
grading_ruleset_package_name=state.grading_ruleset_package_name,
user_session_type=state.user_session_type,
user_session_default_region=state.user_session_default_region,
content_package_hash=state.content_package_hash,
upstream_version=state.upstream_version,
upstream_date_published=state.upstream_date_published,
upstream_instance_name=state.upstream_instance_name,
upstream_form_id=state.upstream_form_id,
grade_xml_path=state.grade_xml_path,
cml_yaml_path=state.cml_yaml_path,
upstream_sync_status=state.upstream_sync_status,
```

And the summary mapper:

```python
form_qualified_name=state.form_qualified_name,
sync_status=state.sync_status,
```

### 3.7 Update LabletDefinitionReadModel (lcm-core)

**File**: `src/core/lcm_core/domain/` — find the read model file (used by lablet-controller and resource-scheduler).

Add new fields to the read model:

```python
@dataclass
class LabletDefinitionReadModel:
    """Lightweight read model for LabletDefinition used by downstream controllers."""
    id: str
    name: str
    version: str
    form_qualified_name: str | None
    bucket_name: str
    # ... existing fields ...

    # NEW content metadata fields
    user_session_package_name: str = "SVN.zip"
    grading_ruleset_package_name: str = "SVN.zip"
    user_session_type: str = "LDS"
    user_session_default_region: str | None = None
    content_package_hash: str | None = None
    upstream_version: str | None = None
    cml_yaml_content: str | None = None
    devices_json: str | None = None
    grade_xml_path: str | None = None
    cml_yaml_path: str | None = None

    @staticmethod
    def from_dict(data: dict) -> "LabletDefinitionReadModel":
        """Hydrate from CPA API response dict."""
        return LabletDefinitionReadModel(
            id=data.get("id", ""),
            name=data.get("name", ""),
            version=data.get("version", ""),
            form_qualified_name=data.get("form_qualified_name"),
            bucket_name=data.get("bucket_name", ""),
            # ... all other fields with safe defaults ...
        )
```

---

## 4. Phase 2: CPA Internal API & Sync Trigger

> **✅ COMPLETED** (2026-02-25)
>
> All 7 sub-tasks implemented. CPA-side fully operational: CreateLabletDefinitionCommand (FQN-driven),
> SyncLabletDefinitionCommand (emits domain event → etcd projector), RecordContentSyncResultCommand
> (version-bump logic AD-CS-005), internal API endpoints (GET with sync_status filter + POST content-synced),
> domain events (SyncRequested + ContentSynced), etcd projectors (write + delete), EtcdStateStore methods.
>
> **Remaining gap (deferred to Phase 3)**: `ControlPlaneApiClient` in lcm-core missing
> `get_definitions_needing_sync()` and `record_content_sync_result()` convenience methods.
> Server-side endpoints are fully implemented; only the shared client wrappers are missing.
> These will be added in Phase 3 since the lablet-controller is the consumer.
>
> **Tests**: 69/69 CPA tests passing. Lint clean.

### 4.1 Update `CreateLabletDefinitionCommand`

**File**: `src/control-plane-api/application/commands/lablet_definition/create_lablet_definition_command.py`

The command must:

1. Accept `form_qualified_name` as **required** (replace `lab_artifact_uri` as required)
2. Accept new optional fields: `user_session_package_name`, `grading_ruleset_package_name`, `user_session_type`, `user_session_default_region`
3. Auto-derive `lab_artifact_uri` from slugified FQN + package name
4. Set `lab_yaml_hash = ""` (will be populated by sync)

```python
@dataclass
class CreateLabletDefinitionCommand(Command[OperationResult[LabletDefinitionCreatedDto]]):
    """Command to create a new LabletDefinition in PENDING_SYNC status."""

    name: str = ""
    version: str = ""
    form_qualified_name: str = ""   # REQUIRED (replaces lab_artifact_uri as primary input)
    created_by: str = ""

    # Resource requirements
    cpu_cores: int = 2
    memory_gb: int = 4
    storage_gb: int = 20
    nested_virt: bool = True

    # License affinity
    license_affinity: list[str] | None = None

    # Lab topology
    node_count: int = 1

    # Port template
    port_definitions: list[dict] | None = None

    # Content package configuration
    user_session_package_name: str = "SVN.zip"
    grading_ruleset_package_name: str = "SVN.zip"
    user_session_type: str = "LDS"
    user_session_default_region: str | None = None

    # Optional fields (may be populated later by sync or manually)
    lab_artifact_uri: str | None = None     # Auto-derived if not provided
    lab_yaml_hash: str = ""                 # Empty until sync populates it
    lab_yaml_cached: str | None = None
    grading_rules_uri: str | None = None
    max_duration_minutes: int = 60
    warm_pool_depth: int = 0

    # Notification config
    owner_notification: dict | None = None
```

**Handler changes**:

- Validate `form_qualified_name` is provided and non-empty
- Call `slugify_fqn()` to derive `bucket_name`
- Auto-derive `lab_artifact_uri` if not explicitly provided
- Pass new fields to `LabletDefinition.create()`

### 4.2 Update `SyncLabletDefinitionCommand`

**File**: `src/control-plane-api/application/commands/lablet_definition/sync_lablet_definition_command.py`

This command is the **trigger** (not the sync executor). It:

1. Sets `sync_status = "sync_requested"` on the aggregate
2. Emits `LabletDefinitionSyncRequestedDomainEvent` → picked up by etcd projector
3. Returns 202 Accepted immediately

The domain event triggers the `ContentSyncRequestedEtcdProjector` (section 4.6), which writes
the etcd key that the lablet-controller's `ContentSyncService` watches.

```python
@dataclass
class SyncLabletDefinitionCommand(Command[OperationResult[LabletDefinitionSyncResultDto]]):
    """Command to request content synchronization for a LabletDefinition.

    This does NOT execute the sync — it emits a domain event that triggers
    the etcd projector, notifying the lablet-controller's ContentSyncService
    via reactive etcd watch (AD-CS-001).
    """
    id: str | None = None
    name: str | None = None
    version: str | None = None
    synced_by: str = ""


class SyncLabletDefinitionCommandHandler(
    CommandHandlerBase,
    CommandHandler[SyncLabletDefinitionCommand, OperationResult[LabletDefinitionSyncResultDto]],
):
    def __init__(self, mediator, mapper, cloud_event_bus, cloud_event_publishing_options,
                 lablet_definition_repository: LabletDefinitionRepository):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._repository = lablet_definition_repository

    async def handle_async(self, request: SyncLabletDefinitionCommand, cancellation_token=None):
        # 1. Find the definition (by id or name+version)
        definition = await self._resolve_definition(request, cancellation_token)
        if not definition:
            return self.not_found("LabletDefinition", f"id={request.id}, name={request.name}")

        # 2. Validate it has a form_qualified_name
        if not definition.state.form_qualified_name:
            return self.bad_request("Definition has no form_qualified_name — cannot sync")

        # 3. Request sync via aggregate method → emits LabletDefinitionSyncRequestedDomainEvent
        definition.request_sync(requested_by=request.synced_by)

        # 4. Persist (domain event will be published → etcd projector writes key)
        await self._repository.update_async(definition, cancellation_token)

        # 5. Return 202 Accepted (sync will happen asynchronously via etcd watch)
        return self.accepted(LabletDefinitionSyncResultDto(
            id=definition.id(),
            name=definition.state.name,
            version=definition.state.version,
            sync_status="sync_requested",
            synced_at=None,  # Not synced yet
        ))
```

**Domain aggregate method** (add to `LabletDefinition`):

```python
def request_sync(self, requested_by: str = "") -> None:
    """Request content synchronization. Emits domain event for etcd projector."""
    self.record_event(LabletDefinitionSyncRequestedDomainEvent(
        aggregate_id=self.id(),
        aggregate_type=type(self).__name__,
        form_qualified_name=self.state.form_qualified_name,
        bucket_name=self.state.bucket_name,
        user_session_package_name=self.state.user_session_package_name or "SVN.zip",
        requested_by=requested_by,
        requested_at=datetime.now(timezone.utc).isoformat(),
    ))
```

### 4.3 New: `RecordContentSyncResultCommand`

**File**: `src/control-plane-api/application/commands/lablet_definition/record_content_sync_result_command.py` (NEW)

This command is called by the lablet-controller's ContentSyncService via the CPA internal API to report sync results:

```python
@dataclass
class RecordContentSyncResultCommand(Command[OperationResult[LabletDefinitionSyncResultDto]]):
    """Command to record the result of a content sync operation (from lablet-controller)."""

    definition_id: str = ""
    sync_status: str = ""  # "success" | "failed"
    error_message: str | None = None

    # Content metadata (populated on success)
    lab_yaml_hash: str = ""
    content_package_hash: str | None = None
    upstream_version: str | None = None
    upstream_date_published: str | None = None
    upstream_instance_name: str | None = None
    upstream_form_id: str | None = None
    grade_xml_path: str | None = None
    cml_yaml_path: str | None = None
    cml_yaml_content: str | None = None
    devices_json: str | None = None
    upstream_sync_status: dict | None = None


class RecordContentSyncResultCommandHandler(
    CommandHandlerBase,
    CommandHandler[RecordContentSyncResultCommand, OperationResult[LabletDefinitionSyncResultDto]],
):
    """Handle content sync result recording from lablet-controller."""

    def __init__(self, mediator, mapper, cloud_event_bus, cloud_event_publishing_options,
                 lablet_definition_repository: LabletDefinitionRepository):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._repository = lablet_definition_repository

    async def handle_async(self, request: RecordContentSyncResultCommand) -> OperationResult[...]:
        # 1. Find definition by ID
        definition = await self._repository.get_by_id_async(request.definition_id)
        if not definition:
            return self.not_found(LabletDefinition, request.definition_id)

        # 2. Detect content change (hash comparison)
        content_changed = (
            request.content_package_hash is not None
            and request.content_package_hash != definition.state.content_package_hash
        )

        # 3. If content changed AND definition was already ACTIVE → version bump flow
        if content_changed and definition.state.status == LabletDefinitionStatus.ACTIVE:
            # 3a. Deprecate current definition
            definition.deprecate(
                deprecated_by="content-sync-service",
                deprecation_reason=f"Content updated (new hash: {request.content_package_hash[:12]}...)",
                replacement_version=None,  # Will be set after new version created
            )
            await self._repository.update_async(definition)

            # 3b. Create new version (auto-increment patch)
            new_version = _increment_patch_version(definition.state.version)
            new_definition = LabletDefinition.create_version(
                name=definition.state.name,
                version=new_version,
                previous_version=definition.state.version,
                lab_artifact_uri=definition.state.lab_artifact_uri,
                lab_yaml_hash=request.lab_yaml_hash,
                resource_requirements=definition.state.resource_requirements,
                node_count=definition.state.node_count,
                port_template=definition.state.port_template,
                created_by="content-sync-service",
            )

            # 3c. Record sync result on the NEW definition
            new_definition.record_content_sync(
                lab_yaml_hash=request.lab_yaml_hash,
                sync_status=request.sync_status,
                content_package_hash=request.content_package_hash,
                upstream_version=request.upstream_version,
                # ... all other metadata fields ...
            )
            await self._repository.add_async(new_definition)

            # 3d. Update deprecation on old definition with replacement pointer
            # (already deprecated above, just link to new version)

            return self.ok(LabletDefinitionSyncResultDto(
                id=new_definition.id(),
                name=new_definition.state.name,
                version=new_version,
                sync_status="success",
                synced_at=datetime.now(timezone.utc).isoformat(),
                lab_yaml_hash=request.lab_yaml_hash,
                content_changed=True,
            ))

        # 4. Normal sync (first sync or no content change)
        definition.record_content_sync(
            lab_yaml_hash=request.lab_yaml_hash,
            sync_status=request.sync_status,
            error_message=request.error_message,
            content_package_hash=request.content_package_hash,
            upstream_version=request.upstream_version,
            upstream_date_published=request.upstream_date_published,
            upstream_instance_name=request.upstream_instance_name,
            upstream_form_id=request.upstream_form_id,
            grade_xml_path=request.grade_xml_path,
            cml_yaml_path=request.cml_yaml_path,
            cml_yaml_content=request.cml_yaml_content,
            devices_json=request.devices_json,
            upstream_sync_status=request.upstream_sync_status,
        )
        await self._repository.update_async(definition)

        return self.ok(LabletDefinitionSyncResultDto(
            id=definition.id(),
            name=definition.state.name,
            version=definition.state.version,
            sync_status=request.sync_status,
            synced_at=datetime.now(timezone.utc).isoformat(),
            lab_yaml_hash=request.lab_yaml_hash,
            content_changed=content_changed,
        ))


def _increment_patch_version(version: str) -> str:
    """Increment the patch component of a semver string.

    Examples:
        "1.0.0" → "1.0.1"
        "2.3.7" → "2.3.8"
        "1.0" → "1.1" (non-semver fallback)
    """
    parts = version.split(".")
    if len(parts) >= 3:
        parts[-1] = str(int(parts[-1]) + 1)
    elif len(parts) == 2:
        parts[-1] = str(int(parts[-1]) + 1)
    else:
        parts.append("1")
    return ".".join(parts)
```

### 4.4 CPA Internal API: New Endpoints

**File**: `src/control-plane-api/api/controllers/internal_controller.py`

Add two new internal endpoints:

#### 4.4.1 `GET /internal/lablet-definitions?sync_status=sync_requested`

The existing `list_definitions_internal` endpoint already accepts filters. We need to ensure the query handler supports `sync_status` filtering:

**File**: `src/control-plane-api/application/queries/lablet_definition/list_lablet_definitions_query.py`

Add `sync_status: str | None = None` filter to `ListLabletDefinitionsQuery` and update the handler to filter by `state.sync_status`.

**File**: `src/control-plane-api/domain/repositories/lablet_definition_repository.py`

Add: `async def list_by_sync_status_async(self, sync_status: str) -> list[LabletDefinition]`

**File**: `src/control-plane-api/integration/repositories/motor_lablet_definition_repository.py`

Implement MongoDB query: `{"state.sync_status": sync_status}`

#### 4.4.2 `POST /internal/lablet-definitions/{definition_id}/content-synced`

New internal endpoint for the lablet-controller to report sync results:

```python
@post(
    "/lablet-definitions/{definition_id}/content-synced",
    summary="Record content sync result",
    tags=["Internal - Definitions"],
)
async def record_content_sync_result(
    self,
    definition_id: str,
    request: RecordContentSyncResultRequest,
    api_key: str = Depends(require_internal_api_key),
):
    """Record content synchronization result from lablet-controller.

    Called by lablet-controller's ContentSyncService after completing
    the sync pipeline (download, upload, upstream notification).
    """
    command = RecordContentSyncResultCommand(
        definition_id=definition_id,
        sync_status=request.sync_status,
        error_message=request.error_message,
        lab_yaml_hash=request.lab_yaml_hash,
        content_package_hash=request.content_package_hash,
        upstream_version=request.upstream_version,
        upstream_date_published=request.upstream_date_published,
        upstream_instance_name=request.upstream_instance_name,
        upstream_form_id=request.upstream_form_id,
        grade_xml_path=request.grade_xml_path,
        cml_yaml_path=request.cml_yaml_path,
        cml_yaml_content=request.cml_yaml_content,
        devices_json=request.devices_json,
        upstream_sync_status=request.upstream_sync_status,
    )
    result = await self.mediator.execute_async(command)
    return self.process(result)
```

### 4.5 Update `CreateLabletDefinitionRequest` (API Model)

**File**: `src/control-plane-api/api/controllers/lablet_definitions_controller.py`

```python
class CreateLabletDefinitionRequest(BaseModel):
    """Request model for creating a LabletDefinition."""

    name: str = Field(..., description="Unique name for the lablet definition", min_length=1, max_length=100)
    version: str = Field(..., description="Semantic version (e.g., '1.0.0')", min_length=1, max_length=20)
    form_qualified_name: str = Field(
        ...,
        description="Form Qualified Name (6 space-separated components, e.g., 'Exam Associate CCNA v1.1 LAB 1.3a')",
        min_length=3,
        max_length=200,
    )

    # Resource requirements
    cpu_cores: int = Field(default=2, ge=1, le=64, description="Required CPU cores")
    memory_gb: int = Field(default=4, ge=1, le=256, description="Required memory in GB")
    storage_gb: int = Field(default=20, ge=1, le=1000, description="Required storage in GB")
    nested_virt: bool = Field(default=True, description="Requires nested virtualization")

    # License affinity
    license_affinity: list[str] | None = Field(default=None)

    # Lab topology
    node_count: int = Field(default=1, ge=1, le=50, description="Number of nodes in the lab")

    # Port template
    port_definitions: list[dict] | None = Field(default=None)

    # Content package configuration (NEW)
    user_session_package_name: str = Field(default="SVN.zip", description="Package filename in S3 bucket")
    grading_ruleset_package_name: str = Field(default="SVN.zip", description="Grading rules package filename")
    user_session_type: str = Field(default="LDS", description="User session delivery type")
    user_session_default_region: str | None = Field(default=None, description="Default LDS region for this definition")

    # Optional fields
    lab_artifact_uri: str | None = Field(default=None, description="Auto-derived from FQN if not provided")
    lab_yaml_hash: str = Field(default="", description="Leave empty — populated by content sync")
    lab_yaml_cached: str | None = Field(default=None)
    grading_rules_uri: str | None = Field(default=None)
    max_duration_minutes: int = Field(default=60, ge=1, le=480)
    warm_pool_depth: int = Field(default=0, ge=0, le=10)

    # Notification config
    owner_notification: dict | None = Field(default=None)
```

### 4.6 New Domain Event + etcd Projectors + EtcdStateStore (CPA)

This section implements the **reactive etcd watch trigger** per AD-CS-001. It follows the
exact pattern established by AD-023 (`LabActionRequestedEtcdProjector` → `LabRecordReconciler`).

#### 4.6.1 New Domain Event: `LabletDefinitionSyncRequestedDomainEvent`

**File**: `src/control-plane-api/domain/events/lablet_definition_events.py`

Add alongside the existing 9 events:

```python
@dataclass
class LabletDefinitionSyncRequestedDomainEvent(DomainEvent):
    """Emitted when a user requests content synchronization for a definition.

    This event triggers the ContentSyncRequestedEtcdProjector, which writes
    an etcd key to notify the lablet-controller's ContentSyncService.
    """

    aggregate_id: str = ""
    aggregate_type: str = "LabletDefinition"
    form_qualified_name: str = ""
    bucket_name: str = ""
    user_session_package_name: str = "SVN.zip"
    requested_by: str = ""
    requested_at: str = ""
```

Also add a corresponding "completed" event for the cleanup projector:

```python
@dataclass
class LabletDefinitionContentSyncedDomainEvent(DomainEvent):
    """Emitted when the lablet-controller reports a completed content sync.

    This event triggers the ContentSyncCompletedEtcdProjector, which DELETES
    the etcd key (cleanup — same pattern as LabActionCompletedEtcdProjector).

    NOTE: This is distinct from the existing LabletDefinitionArtifactSyncedDomainEvent
    which tracks the sync result in the aggregate state. This event specifically
    handles the etcd key lifecycle.
    """

    aggregate_id: str = ""
    aggregate_type: str = "LabletDefinition"
    sync_status: str = ""   # "success" | "failed"
    synced_at: str = ""
```

#### 4.6.2 EtcdStateStore: New Key + Methods

**File**: `src/control-plane-api/integration/services/etcd_state_store.py`

Add the key template alongside existing ones:

```python
class EtcdStateStore:
    # Existing keys...
    SESSION_STATE_KEY = "/sessions/{id}/state"
    WORKER_STATE_KEY = "/workers/{id}/state"
    LAB_RECORD_PENDING_ACTION_KEY = "/lab_records/{id}/pending_action"

    # NEW: Content sync notification key (AD-CS-001)
    DEFINITION_CONTENT_SYNC_KEY = "/definitions/{id}/content_sync"
```

Add methods following the exact pattern of `set_lab_pending_action` / `delete_lab_pending_action`:

```python
    # =========================================================================
    # Definition Content Sync (AD-CS-001)
    # =========================================================================

    async def get_definition_content_sync(self, definition_id: str) -> dict | None:
        """Get pending content sync request for a definition."""
        key = self._format_key(self.DEFINITION_CONTENT_SYNC_KEY, id=definition_id)
        value = await self._client.get(key)
        if value:
            return json.loads(value)
        return None

    async def set_definition_content_sync(
        self,
        definition_id: str,
        form_qualified_name: str,
        bucket_name: str,
        user_session_package_name: str,
        requested_by: str,
        requested_at: str,
    ) -> None:
        """Write content sync request to etcd (triggers lablet-controller watch).

        Pattern: Same as set_lab_pending_action (AD-023).
        """
        key = self._format_key(self.DEFINITION_CONTENT_SYNC_KEY, id=definition_id)
        payload = json.dumps({
            "definition_id": definition_id,
            "form_qualified_name": form_qualified_name,
            "bucket_name": bucket_name,
            "user_session_package_name": user_session_package_name,
            "requested_by": requested_by,
            "requested_at": requested_at,
        })
        await self._client.put(key, payload)
        logger.info(f"etcd: SET definition content_sync {key}")

    async def delete_definition_content_sync(self, definition_id: str) -> None:
        """Delete content sync key from etcd (cleanup after sync completion).

        Pattern: Same as delete_lab_pending_action (AD-023).
        """
        key = self._format_key(self.DEFINITION_CONTENT_SYNC_KEY, id=definition_id)
        await self._client.delete(key)
        logger.info(f"etcd: DELETE definition content_sync {key}")
```

#### 4.6.3 etcd Projectors: ContentSyncRequested + ContentSyncCompleted

**File**: `src/control-plane-api/application/events/domain/etcd_state_projector.py`

Add alongside the existing `LabAction*EtcdProjector` classes:

```python
# ---------------------------------------------------------------------------
# Definition Content Sync projectors (AD-CS-001)
# Pattern: identical to LabAction* projectors (AD-023)
# ---------------------------------------------------------------------------

class ContentSyncRequestedEtcdProjector(DomainEventHandler[LabletDefinitionSyncRequestedDomainEvent]):
    """Projects sync request to etcd — triggers lablet-controller ContentSyncService watch."""

    def __init__(self, etcd_state_store: EtcdStateStore):
        self._etcd = etcd_state_store

    async def handle_async(self, event: LabletDefinitionSyncRequestedDomainEvent) -> None:
        logger.info(
            f"Projecting definition sync request to etcd: "
            f"definition={event.aggregate_id}, fqn='{event.form_qualified_name}'"
        )
        await self._etcd.set_definition_content_sync(
            definition_id=event.aggregate_id,
            form_qualified_name=event.form_qualified_name,
            bucket_name=event.bucket_name,
            user_session_package_name=event.user_session_package_name,
            requested_by=event.requested_by,
            requested_at=event.requested_at,
        )


class ContentSyncCompletedEtcdProjector(DomainEventHandler[LabletDefinitionContentSyncedDomainEvent]):
    """Cleans up etcd key after sync completion — same pattern as LabActionCompletedEtcdProjector."""

    def __init__(self, etcd_state_store: EtcdStateStore):
        self._etcd = etcd_state_store

    async def handle_async(self, event: LabletDefinitionContentSyncedDomainEvent) -> None:
        logger.info(
            f"Cleaning up definition sync etcd key: "
            f"definition={event.aggregate_id}, status={event.sync_status}"
        )
        await self._etcd.delete_definition_content_sync(definition_id=event.aggregate_id)
```

> **Note**: The `RecordContentSyncResultCommandHandler` (section 4.3) must emit the
> `LabletDefinitionContentSyncedDomainEvent` after recording results, so the cleanup
> projector deletes the etcd key. Add `definition.emit_content_synced(...)` in step 4
> of that handler.

### 4.7 Extend ControlPlaneApiClient (lcm-core)

**File**: `src/core/lcm_core/integration/clients/control_plane_client.py`

Add methods used by lablet-controller's ContentSyncService:

```python
async def get_definitions_needing_sync(self) -> list[dict[str, Any]]:
    """Get lablet definitions with sync_status='sync_requested'."""
    response = await self._client.get(
        f"{self._base_url}/api/internal/lablet-definitions",
        params={"sync_status": "sync_requested"},
        headers=self._internal_headers,
    )
    response.raise_for_status()
    return response.json()

async def record_content_sync_result(
    self,
    definition_id: str,
    sync_result: dict[str, Any],
) -> dict[str, Any]:
    """Report content sync result to CPA.

    Args:
        definition_id: The definition ID.
        sync_result: Dict with sync_status, content_package_hash, upstream_version,
                     grade_xml_path, cml_yaml_path, cml_yaml_content, devices_json, etc.

    Returns:
        Response from CPA (LabletDefinitionSyncResultDto).
    """
    response = await self._client.post(
        f"{self._base_url}/api/internal/lablet-definitions/{definition_id}/content-synced",
        json=sync_result,
        headers=self._internal_headers,
    )
    response.raise_for_status()
    return response.json()
```

---

## 5. Phase 3: Integration Clients (lablet-controller)

> ✅ **Phase 3 complete** (2026-02-25). All integration clients implemented and lint-clean.
> Files created: `oauth2_token_manager.py`, `s3_client.py`, `environment_resolver_client.py`, `mosaic_client.py`.
> Files modified: `settings.py`, `lds_spi.py`, `control_plane_client.py` (lcm-core).
> Also closed Phase 2 gap: added `get_definitions_needing_sync()` + `record_content_sync_result()` to `ControlPlaneApiClient`.

### 5.1 Settings Expansion

**File**: `src/lablet-controller/application/settings.py`

Add new configuration sections:

```python
class Settings(ApplicationSettings):
    # ... existing settings ...

    # =========================================================================
    # S3 / RustFS Object Storage
    # =========================================================================
    s3_endpoint: str = "http://localhost:9000"  # RustFS/MinIO S3 API endpoint
    s3_access_key: str = "admin"
    s3_secret_key: str = "admin123"
    s3_region: str = "us-east-1"              # Default region for S3 client
    s3_secure: bool = False                    # Use HTTPS for S3

    # =========================================================================
    # Environment Resolver Service
    # =========================================================================
    environment_resolver_url: str = "https://environment-resolver.expert.certs.cloud"
    environment_resolver_environment: str = "CERTS-DEV"  # Default resolver environment
    # OAuth2 client credentials for Environment Resolver (optional)
    environment_resolver_token_url: str | None = None
    environment_resolver_client_id: str | None = None
    environment_resolver_client_secret: str | None = None
    environment_resolver_scopes: str = ""  # Space-separated scopes

    # =========================================================================
    # Mosaic (Content Authoring Platform)
    # =========================================================================
    # Mosaic base URL is resolved dynamically via Environment Resolver
    # (MOSAIC_BASE_URL from resolver response)
    # OAuth2 client credentials for Mosaic API
    mosaic_token_url: str | None = None      # Keycloak token endpoint
    mosaic_client_id: str | None = None
    mosaic_client_secret: str | None = None
    mosaic_scopes: str = ""                  # Space-separated scopes

    # =========================================================================
    # Grading Engine (Deferred — config ready for future use)
    # =========================================================================
    grading_engine_base_url: str | None = None
    grading_engine_token_url: str | None = None
    grading_engine_client_id: str | None = None
    grading_engine_client_secret: str | None = None
    grading_engine_scopes: str = "api"

    # =========================================================================
    # Content Sync Service
    # =========================================================================
    content_sync_enabled: bool = True                   # Master switch
    content_sync_watch_enabled: bool = True              # PRIMARY: etcd watch for immediate reaction
    content_sync_poll_enabled: bool = False              # FALLBACK: opt-in polling (disabled by default)
    content_sync_poll_interval: int = 300                # Seconds between polls (only if poll_enabled=True)
```

### 5.2 S3 Client

**File**: `src/lablet-controller/integration/services/s3_client.py` (NEW)

```python
"""S3-compatible object storage client for RustFS/MinIO.

Provides bucket and object management operations used by the
ContentSyncService to upload content packages.

Uses boto3 with S3-compatible endpoint configuration.
"""

import logging
from io import BytesIO
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3Client:
    """S3-compatible storage client for RustFS/MinIO."""

    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        secure: bool = False,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )
        logger.info(f"S3Client initialized (endpoint={endpoint_url})")

    async def ensure_bucket_exists(self, bucket_name: str) -> None:
        """Create bucket if it doesn't exist."""
        try:
            self._client.head_bucket(Bucket=bucket_name)
            logger.debug(f"Bucket '{bucket_name}' already exists")
        except ClientError as e:
            error_code = int(e.response["Error"]["Code"])
            if error_code == 404:
                self._client.create_bucket(Bucket=bucket_name)
                logger.info(f"Created bucket '{bucket_name}'")
            else:
                raise

    async def upload_bytes(
        self,
        bucket_name: str,
        object_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload bytes to S3.

        Returns:
            The S3 URI of the uploaded object.
        """
        self._client.upload_fileobj(
            BytesIO(data),
            bucket_name,
            object_key,
            ExtraArgs={"ContentType": content_type},
        )
        uri = f"s3://{bucket_name}/{object_key}"
        logger.info(f"Uploaded {len(data)} bytes to {uri}")
        return uri

    async def object_exists(self, bucket_name: str, object_key: str) -> bool:
        """Check if an object exists."""
        try:
            self._client.head_object(Bucket=bucket_name, Key=object_key)
            return True
        except ClientError:
            return False

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        secure: bool = False,
    ) -> None:
        """Register S3Client as singleton in DI container."""

        def factory(sp: Any) -> "S3Client":
            return cls(
                endpoint_url=endpoint_url,
                access_key=access_key,
                secret_key=secret_key,
                region=region,
                secure=secure,
            )

        services.add_singleton(cls, implementation_factory=factory)
```

### 5.3 OAuth2 Token Manager (Shared Utility)

**File**: `src/lablet-controller/integration/services/oauth2_token_manager.py` (NEW)

A reusable client-credentials token cache used by Environment Resolver and Mosaic clients:

```python
"""OAuth2 Client Credentials token manager with auto-refresh.

Provides cached token acquisition for service-to-service authentication.
Used by EnvironmentResolverClient and MosaicClient.
"""

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TokenConfig:
    """OAuth2 client credentials configuration."""
    token_url: str
    client_id: str
    client_secret: str
    scopes: str = ""  # Space-separated


class OAuth2TokenManager:
    """Manages OAuth2 client credentials tokens with caching and auto-refresh."""

    def __init__(self, config: TokenConfig, leeway_seconds: int = 60) -> None:
        self._config = config
        self._leeway = leeway_seconds
        self._token: str | None = None
        self._expires_at: float = 0
        self._http = httpx.AsyncClient(verify=False)

    async def get_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        if self._token and time.time() < self._expires_at:
            return self._token

        data = {
            "grant_type": "client_credentials",
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }
        if self._config.scopes:
            data["scope"] = self._config.scopes

        response = await self._http.post(self._config.token_url, data=data)
        response.raise_for_status()
        token_data = response.json()

        self._token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 300)
        self._expires_at = time.time() + expires_in - self._leeway

        logger.debug(f"OAuth2 token acquired (expires_in={expires_in}s)")
        return self._token

    async def get_auth_headers(self) -> dict[str, str]:
        """Get Authorization header dict."""
        token = await self.get_token()
        return {"Authorization": f"Bearer {token}"}

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()
```

### 5.4 Environment Resolver Client

**File**: `src/lablet-controller/integration/services/environment_resolver_client.py` (NEW)

```python
"""Environment Resolver client for resolving FQN to service base URLs.

Calls the Environment Resolver service to get environment-specific URLs
(Mosaic base URL, LDS base URL, etc.) for a given form_qualified_name.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from integration.services.oauth2_token_manager import OAuth2TokenManager, TokenConfig

logger = logging.getLogger(__name__)


@dataclass
class ResolvedEnvironment:
    """Resolved environment URLs from the Environment Resolver service."""
    mosaic_base_url: str
    lds_base_url: str | None = None
    minio_base_url: str | None = None
    mozart_base_url: str | None = None
    grading_engine_base_url: str | None = None
    variables_generator_base_url: str | None = None
    raw_response: dict | None = None  # Full response for extensibility


class EnvironmentResolverClient:
    """Client for the Environment Resolver service."""

    def __init__(
        self,
        base_url: str,
        default_environment: str = "CERTS-DEV",
        token_manager: OAuth2TokenManager | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_environment = default_environment
        self._token_manager = token_manager
        self._http = httpx.AsyncClient(verify=False, timeout=30.0)

    async def resolve(
        self,
        qualified_name: str,
        environment: str | None = None,
    ) -> ResolvedEnvironment:
        """Resolve a form qualified name to environment-specific URLs.

        Calls: POST {base_url}/resolve
        Body: {"qualifiedName": "...", "environment": "..."}

        Args:
            qualified_name: The form qualified name from the LabletDefinition.
            environment: Override environment (default: configured default).

        Returns:
            ResolvedEnvironment with parsed URLs.

        Raises:
            httpx.HTTPStatusError: On non-2xx response.
        """
        env = environment or self._default_environment
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        if self._token_manager:
            auth_headers = await self._token_manager.get_auth_headers()
            headers.update(auth_headers)

        payload = {
            "qualifiedName": qualified_name,
            "environment": env,
        }

        logger.info(f"Resolving environment for FQN='{qualified_name}' env='{env}'")
        response = await self._http.post(
            f"{self._base_url}/resolve",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        result = ResolvedEnvironment(
            mosaic_base_url=data.get("MOSAIC_BASE_URL", "").rstrip("/"),
            lds_base_url=data.get("PYLDS_BASE_URL"),
            minio_base_url=data.get("MINIO_BASE_URL"),
            mozart_base_url=data.get("MOZART_BASE_URL"),
            grading_engine_base_url=data.get("GRADING_ENGINE_BASE_URL"),
            variables_generator_base_url=data.get("VARIABLES_GENERATOR_BASE_URL"),
            raw_response=data,
        )

        logger.info(f"Resolved: mosaic={result.mosaic_base_url}, lds={result.lds_base_url}")
        return result

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        base_url: str,
        default_environment: str = "CERTS-DEV",
        token_config: TokenConfig | None = None,
    ) -> None:
        """Register EnvironmentResolverClient as singleton in DI container."""

        def factory(sp: Any) -> "EnvironmentResolverClient":
            token_manager = None
            if token_config and token_config.token_url:
                token_manager = OAuth2TokenManager(token_config)
            return cls(
                base_url=base_url,
                default_environment=default_environment,
                token_manager=token_manager,
            )

        services.add_singleton(cls, implementation_factory=factory)
```

### 5.5 Mosaic Client

**File**: `src/lablet-controller/integration/services/mosaic_client.py` (NEW)

```python
"""Mosaic content authoring platform client.

Provides methods to:
1. Get latest publish records for a form qualified name
2. Download content packages (zip archives)

The Mosaic base URL is resolved dynamically via the Environment Resolver
(MOSAIC_BASE_URL from resolver response). The base_url is NOT configured
statically — it must be passed per-call or cached after resolution.

Authentication: OAuth2 client credentials via Keycloak.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from integration.services.oauth2_token_manager import OAuth2TokenManager, TokenConfig

logger = logging.getLogger(__name__)


@dataclass
class PublishRecord:
    """Represents a Mosaic publish record."""
    id: str             # publishedRecordId (24-char hex)
    form_name: str
    layout: str
    version: str
    date_published: str
    raw_data: dict      # Full response for extensibility


class MosaicClient:
    """Client for the Mosaic content authoring platform API."""

    def __init__(self, token_manager: OAuth2TokenManager | None = None) -> None:
        self._token_manager = token_manager
        self._http = httpx.AsyncClient(verify=False, timeout=120.0)  # Large downloads

    async def _get_auth_headers(self) -> dict[str, str]:
        """Get auth headers (Bearer token from client credentials)."""
        if self._token_manager:
            return await self._token_manager.get_auth_headers()
        return {}

    async def get_latest_publish_records(
        self,
        mosaic_base_url: str,
        qualified_name: str,
    ) -> list[PublishRecord]:
        """Get latest publish records for all packages given a qualified name.

        Calls: GET {mosaic_base_url}/api/v1/latest/publishrecords?qualifiedName={fqn}

        Args:
            mosaic_base_url: Mosaic instance base URL (from Environment Resolver).
            qualified_name: The form qualified name.

        Returns:
            List of PublishRecord objects (one per layout/package type).
        """
        headers = await self._get_auth_headers()
        headers["Accept"] = "application/json"

        url = f"{mosaic_base_url.rstrip('/')}/api/v1/latest/publishrecords"
        logger.info(f"Fetching publish records for FQN='{qualified_name}' from {url}")

        response = await self._http.get(
            url,
            params={"qualifiedName": qualified_name},
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        # Response is a dict keyed by layout type, each containing a list of records
        records = []
        if isinstance(data, dict):
            for layout_key, layout_records in data.items():
                if isinstance(layout_records, list):
                    for rec in layout_records:
                        records.append(PublishRecord(
                            id=rec.get("_id", rec.get("id", "")),
                            form_name=rec.get("formName", ""),
                            layout=rec.get("layout", layout_key),
                            version=str(rec.get("version", "")),
                            date_published=rec.get("datePublished", ""),
                            raw_data=rec,
                        ))
        elif isinstance(data, list):
            for rec in data:
                records.append(PublishRecord(
                    id=rec.get("_id", rec.get("id", "")),
                    form_name=rec.get("formName", ""),
                    layout=rec.get("layout", ""),
                    version=str(rec.get("version", "")),
                    date_published=rec.get("datePublished", ""),
                    raw_data=rec,
                ))

        logger.info(f"Found {len(records)} publish records for '{qualified_name}'")
        return records

    async def download_export_package(
        self,
        mosaic_base_url: str,
        published_record_id: str,
    ) -> bytes:
        """Download a content package (zip archive) by published record ID.

        Calls: GET {mosaic_base_url}/api/v1/download/export_package/{publishedRecordId}

        Args:
            mosaic_base_url: Mosaic instance base URL.
            published_record_id: The 24-char hex ID of the publish record.

        Returns:
            Raw bytes of the zip archive.
        """
        headers = await self._get_auth_headers()
        url = f"{mosaic_base_url.rstrip('/')}/api/v1/download/export_package/{published_record_id}"
        logger.info(f"Downloading package {published_record_id} from {url}")

        response = await self._http.get(url, headers=headers)
        response.raise_for_status()

        content = response.content
        logger.info(f"Downloaded package: {len(content)} bytes")
        return content

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        token_config: TokenConfig | None = None,
    ) -> None:
        """Register MosaicClient as singleton in DI container."""

        def factory(sp: Any) -> "MosaicClient":
            token_manager = None
            if token_config and token_config.token_url:
                token_manager = OAuth2TokenManager(token_config)
            return cls(token_manager=token_manager)

        services.add_singleton(cls, implementation_factory=factory)
```

### 5.6 Extend LDS SPI Client

**File**: `src/lablet-controller/integration/services/lds_spi.py`

Add the `sync_content` method to the existing `LdsSpiClient`:

```python
async def sync_content(
    self,
    form_qualified_name: str,
    region: str | None = None,
) -> dict[str, Any]:
    """Trigger LDS to refresh content from MinIO for the given FQN.

    Calls: PUT /reservations/v3/lab_folder/minio/{form_qualified_name}
    Auth: HTTP Basic Auth per deployment.

    Args:
        form_qualified_name: The FQN as stored in the LabletDefinition.
        region: Optional region override (uses default_region if None).

    Returns:
        LabFolder response dict from LDS.

    Raises:
        LdsApiError: On non-2xx response.
    """
    deployment = self._get_deployment(region)
    url = f"{deployment.base_url}/reservations/v3/lab_folder/minio/{form_qualified_name}"

    logger.info(f"LDS sync_content: PUT {url}")
    response = await self._http.put(
        url,
        auth=(deployment.username, deployment.password),
    )

    if response.status_code != 200:
        raise LdsApiError(
            f"LDS sync_content failed: {response.status_code} {response.text}",
            status_code=response.status_code,
        )

    data = response.json()
    logger.info(f"LDS sync_content success for '{form_qualified_name}': version={data.get('Version')}")
    return data
```

---

## 6. Phase 4: Content Sync Service (lablet-controller)

> ✅ **Phase 4 complete** (2026-02-25). ContentSyncService implemented with etcd watch (primary)
>
> - opt-in polling (fallback). Integrated into LabletReconciler leader lifecycle.
> Files created: `content_sync_service.py`.
> Files modified: `lablet_reconciler.py` (init, _become_leader, _step_down, configure),
> `main.py` (DI wiring for S3Client, EnvironmentResolverClient, MosaicClient),
> `hosted_services/__init__.py`, `integration/services/__init__.py`.
> Decisions stored: AD-CS-002 (lifecycle pattern). Insights: PortTemplate only in CPA.

### 6.1 ContentSyncService

**File**: `src/lablet-controller/application/hosted_services/content_sync_service.py` (NEW)

This service follows the **`LabRecordReconciler` pattern** (AD-023):

- Registered as a singleton (not a `HostedService`)
- Started/stopped by the `LabletReconciler` in `_become_leader()` / `_step_down()`
- **Primary**: Runs an asyncio etcd watch loop (immediate reaction to PUT events)
- **Fallback** (opt-in): Optionally runs a polling loop for consistency

```python
\"\"\"Content Synchronization Service for LabletDefinition content packages.

Lifecycle managed by LabletReconciler (leader-only, like LabRecordReconciler).

PRIMARY trigger (AD-CS-001): Watches etcd /definitions/ prefix for content_sync
PUT events. When the CPA emits a LabletDefinitionSyncRequestedDomainEvent, the
ContentSyncRequestedEtcdProjector writes to /lcm/definitions/{id}/content_sync,
and this service reacts immediately.

FALLBACK trigger (opt-in): Polls CPA internal API for definitions with
sync_status=sync_requested at a configurable interval. Disabled by default.

Pipeline:
  1. Resolve Mosaic base URL via Environment Resolver
  2. Get latest publish records from Mosaic
  3. Download content package (zip archive)
  4. Compute SHA-256 hash of the package
  5. Extract metadata (mosaic_meta.json, cml.yaml, grade.xml, devices.json)
  6. Upload package to RustFS bucket
  7. Notify upstream services (LDS)
  8. Report results to CPA

All mutations go through Control Plane API (ADR-001).
\"\"\"

import asyncio
import hashlib
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import Any

from lcm_core.integration.clients import ControlPlaneApiClient
from lcm_core.integration.clients.etcd_client import EtcdClient

from application.settings import Settings
from integration.services.environment_resolver_client import EnvironmentResolverClient
from integration.services.lds_spi import LdsSpiClient
from integration.services.mosaic_client import MosaicClient
from integration.services.s3_client import S3Client

logger = logging.getLogger(__name__)


class ContentSyncService:
    \"\"\"Orchestrates content synchronization for LabletDefinitions.

    Pattern: etcd watch loop (same as LabRecordReconciler — AD-023).
    Leader-only: started by LabletReconciler._become_leader().
    \"\"\"

    def __init__(
        self,
        api_client: ControlPlaneApiClient,
        etcd_client: EtcdClient,
        environment_resolver: EnvironmentResolverClient,
        mosaic_client: MosaicClient,
        s3_client: S3Client,
        lds_client: LdsSpiClient,
        settings: Settings,
    ) -> None:
        self._api = api_client
        self._etcd = etcd_client
        self._env_resolver = environment_resolver
        self._mosaic = mosaic_client
        self._s3 = s3_client
        self._lds = lds_client
        self._settings = settings

        self._watch_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._running = False

        # Metrics
        self._syncs_received = 0
        self._syncs_succeeded = 0
        self._syncs_failed = 0
        self._last_sync_at: str | None = None

    # =========================================================================
    # Lifecycle (called by LabletReconciler)
    # =========================================================================

    async def start_async(self) -> None:
        \"\"\"Start the watch loop (and optional poll loop).\"\"\"
        if self._running:
            return
        self._running = True

        # PRIMARY: etcd watch loop (always enabled when content_sync_watch_enabled)
        if self._settings.content_sync_watch_enabled:
            self._watch_task = asyncio.create_task(self._watch_loop())
            logger.info(\"ContentSyncService: started etcd watch loop (primary trigger)\")
        else:
            logger.warning(\"ContentSyncService: etcd watch DISABLED by configuration\")

        # FALLBACK: optional polling loop (opt-in, disabled by default)
        if self._settings.content_sync_poll_enabled:
            self._poll_task = asyncio.create_task(self._poll_loop())
            logger.info(
                f\"ContentSyncService: started poll loop \"
                f\"(interval={self._settings.content_sync_poll_interval}s)\"
            )
        else:
            logger.info(\"ContentSyncService: polling DISABLED (opt-in only)\")

    async def stop_async(self) -> None:
        \"\"\"Stop all loops.\"\"\"
        self._running = False
        for task in [self._watch_task, self._poll_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._watch_task = None
        self._poll_task = None
        logger.info(\"ContentSyncService stopped\")

    # =========================================================================
    # PRIMARY: etcd watch loop (AD-CS-001, follows LabRecordReconciler pattern)
    # =========================================================================

    def _get_watch_prefix(self) -> str:
        \"\"\"Return the etcd key prefix to watch for content sync requests.

        Convention: {etcd_key_prefix}/definitions/
        e.g., /lcm/definitions/
        \"\"\"
        base = self._settings.etcd_key_prefix.rstrip(\"/\")
        return f\"{base}/definitions/\"

    async def _watch_loop(self) -> None:
        \"\"\"Watch etcd for definition content sync requests.

        Reconnects with exponential backoff on failure.
        Pattern: identical to LabRecordReconciler._watch_loop() (AD-023).
        \"\"\"
        prefix = self._get_watch_prefix()
        reconnect_delay = 1.0
        max_delay = 30.0

        logger.info(f\"ContentSyncService: watching etcd prefix '{prefix}'\")

        while self._running:
            try:
                async for event in self._etcd.watch_prefix(prefix):
                    if not self._running:
                        break
                    await self._handle_watch_event(event)

                # If watch ends normally, reconnect
                reconnect_delay = 1.0

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f\"ContentSyncService: watch error (reconnecting in {reconnect_delay}s): {e}\",
                    exc_info=True,
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)

    async def _handle_watch_event(self, event: Any) -> None:
        \"\"\"Handle a single etcd watch event.

        Only reacts to PUT events (key created/updated).
        Pattern: identical to LabRecordReconciler._handle_watch_event().
        \"\"\"
        # Only react to PUT events (new sync requests)
        if not hasattr(event, \"type\") or event.type != \"PUT\":
            return

        try:
            # Parse the key to extract definition_id
            # Key format: /lcm/definitions/{definition_id}/content_sync
            key = event.key
            parts = key.rstrip(\"/\").split(\"/\")
            # Expected: ['', 'lcm', 'definitions', '{definition_id}', 'content_sync']
            if len(parts) < 4 or not parts[-1] == \"content_sync\":
                logger.warning(f\"ContentSyncService: ignoring unexpected key: {key}\")
                return

            definition_id = parts[-2]

            # Parse JSON payload from the etcd value
            payload = json.loads(event.value) if event.value else {}
            fqn = payload.get(\"form_qualified_name\", \"\")

            logger.info(
                f\"ContentSyncService: received sync request via etcd watch: \"
                f\"definition={definition_id}, fqn='{fqn}'\"
            )

            self._syncs_received += 1

            # Fetch full definition from CPA (need all fields for sync pipeline)
            defn = await self._api.get_definition(definition_id)
            if not defn:
                logger.error(f\"ContentSyncService: definition {definition_id} not found in CPA\")
                self._syncs_failed += 1
                return

            # Execute the sync pipeline
            await self._sync_definition(defn)

        except Exception as e:
            logger.error(f\"ContentSyncService: error handling watch event: {e}\", exc_info=True)
            self._syncs_failed += 1

    # =========================================================================
    # FALLBACK: opt-in polling loop (consistency catch-up)
    # =========================================================================

    async def _poll_loop(self) -> None:
        \"\"\"Polling loop — fetch definitions needing sync, process each.

        Opt-in fallback (CONTENT_SYNC_POLL_ENABLED=true). Catches definitions
        that may have been missed during etcd watch reconnection gaps.
        \"\"\"
        while self._running:
            try:
                definitions = await self._api.get_definitions_needing_sync()
                if definitions:
                    logger.info(f\"ContentSyncService poll: found {len(definitions)} definitions needing sync\")
                    for defn in definitions:
                        await self._sync_definition(defn)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f\"ContentSyncService poll error: {e}\", exc_info=True)

            await asyncio.sleep(self._settings.content_sync_poll_interval)

    # =========================================================================
    # Sync pipeline (shared by watch + poll paths)
    # =========================================================================

    async def _sync_definition(self, defn: dict[str, Any]) -> None:
        """Execute the full sync pipeline for one definition."""
        definition_id = defn.get("id", "unknown")
        fqn = defn.get("form_qualified_name", "")
        bucket_name = defn.get("bucket_name", "")
        package_name = defn.get("user_session_package_name", "SVN.zip")

        logger.info(f"Syncing definition {definition_id}: FQN='{fqn}', bucket='{bucket_name}'")
        self._syncs_attempted += 1

        try:
            # Step 1: Resolve Mosaic base URL
            resolved = await self._env_resolver.resolve(fqn)
            mosaic_url = resolved.mosaic_base_url
            if not mosaic_url:
                raise ValueError(f"No MOSAIC_BASE_URL resolved for FQN '{fqn}'")

            # Step 2: Get latest publish records
            records = await self._mosaic.get_latest_publish_records(mosaic_url, fqn)
            if not records:
                raise ValueError(f"No publish records found for FQN '{fqn}'")

            # Find the LDSv3 layout record (preferred) or first available
            target_record = None
            for rec in records:
                if rec.layout == "LDSv3":
                    target_record = rec
                    break
            if not target_record:
                target_record = records[0]

            logger.info(
                f"Using publish record: id={target_record.id}, "
                f"form={target_record.form_name}, version={target_record.version}"
            )

            # Step 3: Download the package
            package_bytes = await self._mosaic.download_export_package(mosaic_url, target_record.id)

            # Step 4: Compute SHA-256 hash of the entire package
            content_package_hash = hashlib.sha256(package_bytes).hexdigest()

            # Step 5: Extract metadata from the zip
            metadata = self._extract_metadata(package_bytes)

            # Step 6: Upload to RustFS
            await self._s3.ensure_bucket_exists(bucket_name)
            await self._s3.upload_bytes(
                bucket_name=bucket_name,
                object_key=package_name,
                data=package_bytes,
                content_type="application/zip",
            )

            # Step 7: Notify upstream services
            upstream_status = {}

            # 7a: LDS sync
            try:
                user_session_default_region = defn.get("user_session_default_region")
                lds_result = await self._lds.sync_content(fqn, region=user_session_default_region)
                upstream_status["lds"] = {
                    "status": "success",
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "version": lds_result.get("Version", ""),
                }
            except Exception as lds_err:
                logger.error(f"LDS sync failed for '{fqn}': {lds_err}")
                upstream_status["lds"] = {
                    "status": "failed",
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(lds_err),
                }

            # 7b: Grading Engine sync (deferred — placeholder for extensibility)
            # When ready, add: upstream_status["grading_engine"] = await self._sync_grading_engine(...)

            # Step 8: Report results to CPA
            sync_result = {
                "sync_status": "success",
                "lab_yaml_hash": metadata.get("cml_yaml_hash", ""),
                "content_package_hash": content_package_hash,
                "upstream_version": metadata.get("upstream_version"),
                "upstream_date_published": metadata.get("upstream_date_published"),
                "upstream_instance_name": metadata.get("upstream_instance_name"),
                "upstream_form_id": metadata.get("upstream_form_id"),
                "grade_xml_path": metadata.get("grade_xml_path"),
                "cml_yaml_path": metadata.get("cml_yaml_path"),
                "cml_yaml_content": metadata.get("cml_yaml_content"),
                "devices_json": metadata.get("devices_json"),
                "port_template": metadata.get("port_template"),  # ADR-029: auto-extracted from CML nodes[].tags
                "upstream_sync_status": upstream_status,
            }

            await self._api.record_content_sync_result(definition_id, sync_result)
            self._syncs_succeeded += 1
            logger.info(f"Content sync SUCCESS for {definition_id} (hash={content_package_hash[:12]}...)")

        except Exception as e:
            self._syncs_failed += 1
            logger.error(f"Content sync FAILED for {definition_id}: {e}", exc_info=True)

            # Report failure to CPA
            try:
                await self._api.record_content_sync_result(definition_id, {
                    "sync_status": "failed",
                    "error_message": str(e),
                    "lab_yaml_hash": defn.get("lab_yaml_hash", ""),
                })
            except Exception as report_err:
                logger.error(f"Failed to report sync failure: {report_err}")

    def _extract_metadata(self, package_bytes: bytes) -> dict[str, Any]:
        """Extract metadata from a downloaded content package (zip).

        Searches for:
        - mosaic_meta.json → DatePublished, Version, InstanceName, FormId
        - cml.yaml or cml.yml → full content + SHA-256 hash + port_template (ADR-029)
        - grade.xml → relative path
        - devices.json → full content

        Args:
            package_bytes: Raw zip archive bytes.

        Returns:
            Dict with extracted metadata.
        """
        metadata: dict[str, Any] = {}

        with zipfile.ZipFile(io.BytesIO(package_bytes)) as zf:
            names = zf.namelist()

            # Find mosaic_meta.json (anywhere in the archive)
            meta_files = [n for n in names if n.endswith("mosaic_meta.json")]
            if meta_files:
                meta_content = zf.read(meta_files[0]).decode("utf-8")
                meta_data = json.loads(meta_content)
                metadata["upstream_version"] = meta_data.get("Version")
                metadata["upstream_date_published"] = meta_data.get("DatePublished")
                metadata["upstream_instance_name"] = meta_data.get("InstanceName")
                metadata["upstream_form_id"] = meta_data.get("FormId")

            # Find cml.yaml or cml.yml (anywhere in the archive)
            cml_files = [n for n in names if n.endswith(("cml.yaml", "cml.yml"))]
            if cml_files:
                cml_content = zf.read(cml_files[0]).decode("utf-8")
                metadata["cml_yaml_path"] = cml_files[0]
                metadata["cml_yaml_content"] = cml_content
                metadata["cml_yaml_hash"] = hashlib.sha256(cml_content.encode("utf-8")).hexdigest()

                # Extract port_template from CML topology nodes[].tags (ADR-029)
                try:
                    import yaml
                    parsed = yaml.safe_load(cml_content)
                    nodes = parsed.get("nodes", []) if isinstance(parsed, dict) else []
                    port_template = PortTemplate.from_cml_nodes(nodes)
                    if port_template.port_definitions:
                        metadata["port_template"] = port_template.to_dict()
                except Exception as pt_err:
                    logger.warning(f"Failed to extract port_template from CML YAML: {pt_err}")

            # Find grade.xml (anywhere in the archive)
            grade_files = [n for n in names if n.endswith("grade.xml")]
            if grade_files:
                metadata["grade_xml_path"] = grade_files[0]

            # Find devices.json (anywhere in the archive)
            devices_files = [n for n in names if n.endswith("devices.json")]
            if devices_files:
                devices_content = zf.read(devices_files[0]).decode("utf-8")
                metadata["devices_json"] = devices_content

        logger.info(
            f"Extracted metadata: version={metadata.get('upstream_version')}, "
            f"cml={metadata.get('cml_yaml_path')}, grade={metadata.get('grade_xml_path')}, "
            f"devices={'yes' if metadata.get('devices_json') else 'no'}"
        )
        return metadata

    def get_stats(self) -> dict[str, Any]:
        """Return service stats for admin/metrics endpoints."""
        return {
            "running": self._running,
            "watch_enabled": self._settings.content_sync_watch_enabled,
            "poll_enabled": self._settings.content_sync_poll_enabled,
            "syncs_received": self._syncs_received,
            "syncs_succeeded": self._syncs_succeeded,
            "syncs_failed": self._syncs_failed,
            "last_sync_at": self._last_sync_at,
        }

    @classmethod
    def configure(cls, services: "ServiceCollection") -> None:
        """Register ContentSyncService as singleton in DI container.

        Lifecycle managed by LabletReconciler (not registered as HostedService).
        Pattern: same as LabRecordReconciler.configure() (AD-023).
        """
        from application.settings import Settings

        def factory(sp: Any) -> "ContentSyncService":
            settings = sp.get_required_service(Settings)
            return cls(
                api_client=sp.get_required_service(ControlPlaneApiClient),
                etcd_client=sp.get_required_service(EtcdClient),
                environment_resolver=sp.get_required_service(EnvironmentResolverClient),
                mosaic_client=sp.get_required_service(MosaicClient),
                s3_client=sp.get_required_service(S3Client),
                lds_client=sp.get_required_service(LdsSpiClient),
                settings=settings,
            )

        services.add_singleton(cls, implementation_factory=factory)
```

### 6.2 Integrate ContentSyncService into LabletReconciler

**File**: `src/lablet-controller/application/hosted_services/lablet_reconciler.py`

#### 6.2.1 Update `__init__`

Add `content_sync_service` parameter:

```python
def __init__(
    self,
    api_client: ControlPlaneApiClient,
    etcd_client: EtcdClient,
    cml_labs_client: CmlLabsSpiClient,
    lds_client: LdsSpiClient,
    settings: Settings,
    lab_discovery_service: "LabDiscoveryService | None" = None,
    lab_record_reconciler: "LabRecordReconciler | None" = None,
    content_sync_service: "ContentSyncService | None" = None,  # NEW
) -> None:
    # ... existing init ...
    self._content_sync_service: ContentSyncService | None = content_sync_service
```

#### 6.2.2 Update `_become_leader()`

```python
async def _become_leader(self) -> None:
    await super()._become_leader()

    # ... existing lab discovery + lab record reconciler start ...

    # Start content sync service (if configured)
    if self._content_sync_service:
        await self._content_sync_service.start_async()
        logger.info(f"{self._config.service_name}: Started content sync service (leader-only)")
    else:
        logger.info(f"{self._config.service_name}: Content sync service not configured")
```

#### 6.2.3 Update `_step_down()`

```python
async def _step_down(self) -> None:
    # Stop content sync service
    if self._content_sync_service:
        await self._content_sync_service.stop_async()
        logger.info(f"{self._config.service_name}: Stopped content sync service")

    # ... existing lab record reconciler + lab discovery stop ...
    await super()._step_down()
```

#### 6.2.4 Update `configure()` classmethod

```python
@classmethod
def configure(cls, services, settings):
    from application.hosted_services.content_sync_service import ContentSyncService
    # ... existing imports ...

    # Register ContentSyncService as singleton
    ContentSyncService.configure(services)

    # ... existing LabDiscoveryService.configure + LabRecordReconciler.configure ...

    def factory(sp) -> LabletReconciler:
        # ... existing resolves ...

        # Resolve optional content sync service
        try:
            content_sync = sp.get_required_service(ContentSyncService)
        except Exception:
            content_sync = None
            logger.warning("ContentSyncService not available — content sync disabled")

        return cls(
            # ... existing params ...
            content_sync_service=content_sync,
        )
```

### 6.3 Update lablet-controller `main.py`

**File**: `src/lablet-controller/main.py`

Add DI configuration for the new integration clients:

```python
from integration.services.environment_resolver_client import EnvironmentResolverClient
from integration.services.mosaic_client import MosaicClient
from integration.services.oauth2_token_manager import TokenConfig
from integration.services.s3_client import S3Client

# ... in create_app() after existing DI setup ...

# Configure S3 client (RustFS/MinIO)
S3Client.configure(
    builder.services,
    endpoint_url=settings.s3_endpoint,
    access_key=settings.s3_access_key,
    secret_key=settings.s3_secret_key,
    region=settings.s3_region,
    secure=settings.s3_secure,
)

# Configure Environment Resolver client
env_resolver_token = None
if settings.environment_resolver_token_url and settings.environment_resolver_client_id:
    env_resolver_token = TokenConfig(
        token_url=settings.environment_resolver_token_url,
        client_id=settings.environment_resolver_client_id,
        client_secret=settings.environment_resolver_client_secret or "",
        scopes=settings.environment_resolver_scopes,
    )
EnvironmentResolverClient.configure(
    builder.services,
    base_url=settings.environment_resolver_url,
    default_environment=settings.environment_resolver_environment,
    token_config=env_resolver_token,
)

# Configure Mosaic client
mosaic_token = None
if settings.mosaic_token_url and settings.mosaic_client_id:
    mosaic_token = TokenConfig(
        token_url=settings.mosaic_token_url,
        client_id=settings.mosaic_client_id,
        client_secret=settings.mosaic_client_secret or "",
        scopes=settings.mosaic_scopes,
    )
MosaicClient.configure(
    builder.services,
    token_config=mosaic_token,
)
```

---

## 7. Phase 5: UI Changes

### 7.1 Definitions Tab — "Synchronize" Action Button

**File**: `src/control-plane-api/ui/src/` (Bootstrap 5 + Vanilla JS)

In the Definitions tab (Sessions nav view), add a "Synchronize" button to each definition row.

#### 7.1.1 Row Action Button

In the definitions table, add a column or action dropdown with:

```html
<button class="btn btn-sm btn-outline-primary sync-btn"
        data-definition-id="${def.id}"
        data-bs-toggle="tooltip"
        title="Synchronize content from Mosaic">
    <i class="bi bi-arrow-repeat"></i> Sync
</button>
```

The button should be:

- **Visible** only if user has `content:rw` scope (check via injected user claims)
- **Disabled** if `sync_status === "sync_requested"` (already pending)
- Show a **spinner** after click while waiting for API response

#### 7.1.2 Sync Button Click Handler

```javascript
document.addEventListener('click', async (e) => {
    const syncBtn = e.target.closest('.sync-btn');
    if (!syncBtn) return;

    const defId = syncBtn.dataset.definitionId;
    syncBtn.disabled = true;
    syncBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Syncing...';

    try {
        const response = await fetch(`/api/lablet-definitions/${defId}/sync`, {
            method: 'POST',
            credentials: 'include',  // Send session cookie
        });
        if (response.ok) {
            showToast('success', 'Sync requested. The content will be synchronized shortly.');
            // Refresh the definitions list
            await refreshDefinitions();
        } else {
            const err = await response.json();
            showToast('error', `Sync failed: ${err.detail || err.error_message}`);
        }
    } catch (err) {
        showToast('error', `Network error: ${err.message}`);
    } finally {
        syncBtn.disabled = false;
        syncBtn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Sync';
    }
});
```

#### 7.1.3 Definition Detail Modal — Sync Button

In the definition detail modal, add a "Synchronize" button next to the status badge:

```html
<div class="d-flex align-items-center gap-2">
    <span class="badge ${statusBadgeClass}">${def.status}</span>
    <button class="btn btn-sm btn-outline-primary sync-btn"
            data-definition-id="${def.id}"
            ${def.sync_status === 'sync_requested' ? 'disabled' : ''}>
        <i class="bi bi-arrow-repeat"></i> Synchronize
    </button>
</div>
```

### 7.2 Status Badge Styling

Add a `PENDING_SYNC` badge style:

```html
<!-- Status badges -->
<span class="badge bg-warning text-dark">pending_sync</span>   <!-- Yellow -->
<span class="badge bg-success">active</span>                    <!-- Green -->
<span class="badge bg-secondary">deprecated</span>              <!-- Gray -->
<span class="badge bg-dark">archived</span>                     <!-- Dark -->
```

Also show `sync_status` as a secondary indicator:

```html
<span class="badge bg-info">sync_requested</span>              <!-- Blue - waiting for lablet-controller -->
<span class="badge bg-success">success</span>                   <!-- Green - last sync succeeded -->
<span class="badge bg-danger">failed</span>                     <!-- Red - last sync failed -->
```

### 7.3 Create Definition Form Update

Update the "New Definition" form to:

1. **Remove** `lab_artifact_uri` as a required input field
2. **Add** `form_qualified_name` as required input
3. **Add** `user_session_package_name` (default "SVN.zip", editable)
4. **Add** `grading_ruleset_package_name` (default "SVN.zip", editable)
5. **Add** `user_session_type` (default "LDS", dropdown)
6. **Add** `user_session_default_region` (optional, dropdown)
7. Show auto-derived `bucket_name` as read-only preview

```html
<div class="mb-3">
    <label for="form_qualified_name" class="form-label">Form Qualified Name *</label>
    <input type="text" class="form-control" id="form_qualified_name"
           placeholder="e.g., Exam Associate CCNA v1.1 LAB 1.3a" required>
    <div class="form-text">
        Format: {trackType} {trackLevel} {trackAcronym} {examVersion} {moduleAcronym} {formName}
    </div>
    <div class="form-text text-muted" id="bucket_preview">
        Bucket: <code id="bucket_name_preview">-</code>
    </div>
</div>

<script>
// Live preview of slugified bucket name
document.getElementById('form_qualified_name').addEventListener('input', (e) => {
    const slug = e.target.value.trim().toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9.\-]/g, '');
    document.getElementById('bucket_name_preview').textContent = slug || '-';
});
</script>
```

### 7.4 Definition Detail — Show Content Metadata

In the definition detail modal, show the content sync metadata when available:

```html
<!-- Content Synchronization Section -->
<h6 class="mt-3">Content Synchronization</h6>
<table class="table table-sm">
    <tr><td>Bucket</td><td><code>${def.bucket_name}</code></td></tr>
    <tr><td>Package</td><td>${def.user_session_package_name}</td></tr>
    <tr><td>Content Hash</td><td><code>${def.content_package_hash || 'Not synced'}</code></td></tr>
    <tr><td>Upstream Version</td><td>${def.upstream_version || '-'}</td></tr>
    <tr><td>Date Published</td><td>${def.upstream_date_published || '-'}</td></tr>
    <tr><td>Mosaic Instance</td><td>${def.upstream_instance_name || '-'}</td></tr>
    <tr><td>CML YAML</td><td>${def.cml_yaml_path || 'Not extracted'}</td></tr>
    <tr><td>Grade XML</td><td>${def.grade_xml_path || 'Not extracted'}</td></tr>
    <tr><td>Last Synced</td><td>${def.last_synced_at || 'Never'}</td></tr>
    <tr><td>Sync Status</td><td><span class="badge ${syncBadgeClass}">${def.sync_status || '-'}</span></td></tr>
</table>

<!-- Upstream Service Sync Status -->
${def.upstream_sync_status ? `
<h6>Upstream Services</h6>
<table class="table table-sm">
    ${Object.entries(def.upstream_sync_status).map(([svc, info]) => `
        <tr>
            <td>${svc}</td>
            <td><span class="badge ${info.status === 'success' ? 'bg-success' : 'bg-danger'}">${info.status}</span></td>
            <td>${info.synced_at || '-'}</td>
            <td>${info.version || '-'}</td>
        </tr>
    `).join('')}
</table>
` : ''}
```

---

## 8. Phase 6: Keycloak & Authorization

### 8.1 Add `content:rw` Scope

**Keycloak realm configuration** (`deployment/keycloak/`):

1. Add `content:rw` as a new **client scope** in the `aix` realm
2. Assign it to the `lcm-public` client as an optional scope
3. Map it to user roles that should have definition management access

### 8.2 Enforce Scope in API

**File**: `src/control-plane-api/api/dependencies.py`

Add a new dependency function:

```python
async def require_content_scope(
    user: dict = Depends(get_current_user),
) -> dict:
    """Require 'content:rw' scope in the JWT token.

    Raises 403 Forbidden if the scope is missing.
    """
    scopes = user.get("scope", "").split()
    if "content:rw" not in scopes:
        raise HTTPException(status_code=403, detail="Requires 'content:rw' scope")
    return user
```

Apply to definition management endpoints:

```python
# In LabletDefinitionsController
@post("/", ...)
async def create_definition(
    self,
    request: CreateLabletDefinitionRequest,
    user: dict = Depends(require_content_scope),  # ← Changed from require_roles
):
    ...

@post("/{definition_id}/sync", ...)
async def sync_definition(
    self,
    definition_id: str,
    user: dict = Depends(require_content_scope),
):
    ...

@put("/{definition_id}", ...)
async def update_definition(
    self,
    definition_id: str,
    request: UpdateLabletDefinitionRequest,
    user: dict = Depends(require_content_scope),
):
    ...
```

### 8.3 `track_acronym` Claim (Deferred)

The `track_acronym` claim in JWT will be used **later** to filter which definitions a user can view/edit/instantiate. For now, document the plan:

- Keycloak will include `track_acronym` as a user attribute claim (e.g., `"AUTO"`, `"CCNA"`)
- The query handlers will accept a `track_acronym` filter parameter
- Enforcement will be at the query handler level, not middleware

---

## 9. Phase 7: Testing

### 9.1 Unit Tests — Domain Model

**File**: `src/control-plane-api/tests/test_lablet_definition_domain.py`

```python
class TestLabletDefinitionAggregate:
    """Test LabletDefinition aggregate with new content sync fields."""

    def test_create_sets_pending_sync_status(self):
        """New definitions start in PENDING_SYNC status."""

    def test_create_derives_bucket_name_from_fqn(self):
        """bucket_name is auto-derived from slugified form_qualified_name."""

    def test_create_derives_lab_artifact_uri(self):
        """lab_artifact_uri is auto-computed as s3://{bucket}/{package_name}."""

    def test_record_content_sync_transitions_to_active(self):
        """Successful sync transitions PENDING_SYNC → ACTIVE."""

    def test_record_content_sync_stores_metadata(self):
        """Sync result populates content metadata fields."""

    def test_content_change_detection(self):
        """Different content_package_hash triggers version creation."""


class TestSlugifyFqn:
    """Test FQN slugification utility."""

    def test_basic_slugification(self):
        assert slugify_fqn("Exam Associate CCNA v1.1 LAB 1.3a") == "exam-associate-ccna-v1.1-lab-1.3a"

    def test_preserves_dots(self):
        assert slugify_fqn("Exam CCIE INF v1 DES 1.1") == "exam-ccie-inf-v1-des-1.1"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            slugify_fqn("")

    def test_strips_invalid_chars(self):
        assert slugify_fqn("Test / Special @ Chars v1 MOD 1") == "test-special-chars-v1-mod-1"
```

### 9.2 Unit Tests — Content Sync Service

**File**: `src/lablet-controller/tests/test_content_sync_service.py`

```python
class TestContentSyncService:
    """Test ContentSyncService orchestration pipeline."""

    @pytest.fixture
    def mock_deps(self):
        """Create mock dependencies."""
        return {
            "api_client": AsyncMock(spec=ControlPlaneApiClient),
            "env_resolver": AsyncMock(spec=EnvironmentResolverClient),
            "mosaic_client": AsyncMock(spec=MosaicClient),
            "s3_client": AsyncMock(spec=S3Client),
            "lds_client": AsyncMock(spec=LdsSpiClient),
        }

    async def test_sync_pipeline_success(self, mock_deps):
        """Full sync pipeline: resolve → download → hash → upload → notify → report."""

    async def test_sync_pipeline_mosaic_failure(self, mock_deps):
        """Mosaic download failure reports error to CPA."""

    async def test_sync_pipeline_s3_upload_failure(self, mock_deps):
        """S3 upload failure reports error to CPA."""

    async def test_sync_pipeline_lds_failure_partial_success(self, mock_deps):
        """LDS failure results in partial success (content stored, upstream failed)."""

    async def test_extract_metadata_from_zip(self):
        """Metadata extraction finds mosaic_meta.json, cml.yaml, grade.xml, devices.json."""


class TestMetadataExtraction:
    """Test zip metadata extraction."""

    def test_extract_mosaic_meta(self):
        """Extracts Version, DatePublished, InstanceName, FormId from mosaic_meta.json."""

    def test_extract_cml_yaml(self):
        """Finds cml.yaml or cml.yml and computes hash."""

    def test_extract_grade_xml_path(self):
        """Finds grade.xml relative path."""

    def test_extract_devices_json(self):
        """Extracts devices.json content."""

    def test_handles_missing_files_gracefully(self):
        """Missing optional files don't cause failure."""
```

### 9.3 Integration Tests

**File**: `src/lablet-controller/tests/integration/test_s3_client.py`

Test against a local MinIO/RustFS instance (Docker).

**File**: `src/lablet-controller/tests/integration/test_environment_resolver.py`

Test with mocked HTTP responses.

---

## 10. Phase 8: Documentation

### 10.1 Files to Update

| File | Changes |
|------|---------|
| `CHANGELOG.md` | Add entry under "Unreleased" for content sync feature |
| `README.md` | Update feature list, add content sync section |
| `docs/features.md` | Add content synchronization feature documentation |
| `docs/getting-started.md` | Add S3/RustFS setup instructions |
| `deployment/docker-compose.shared.yml` | Add env vars for new services |
| `.env-shared` / `.env` | Add new environment variables |

### 10.2 New Environment Variables

Add to `.env-shared` and docker-compose:

```bash
# Content Sync (lablet-controller)
CONTENT_SYNC_ENABLED=true
CONTENT_SYNC_WATCH_ENABLED=true        # PRIMARY: reactive etcd watch (recommended)
CONTENT_SYNC_POLL_ENABLED=false         # FALLBACK: opt-in polling (disabled by default)
CONTENT_SYNC_POLL_INTERVAL=300          # Seconds between polls (only if poll_enabled=true)

# S3/RustFS (shared by lablet-controller)
S3_ENDPOINT=http://aix-rustfs:9000
S3_ACCESS_KEY=admin
S3_SECRET_KEY=admin123
S3_REGION=us-east-1
S3_SECURE=false

# Environment Resolver
ENVIRONMENT_RESOLVER_URL=https://environment-resolver.expert.certs.cloud
ENVIRONMENT_RESOLVER_ENVIRONMENT=CERTS-DEV
# Optional OAuth2 for resolver
ENVIRONMENT_RESOLVER_TOKEN_URL=
ENVIRONMENT_RESOLVER_CLIENT_ID=
ENVIRONMENT_RESOLVER_CLIENT_SECRET=
ENVIRONMENT_RESOLVER_SCOPES=

# Mosaic OAuth2
MOSAIC_TOKEN_URL=
MOSAIC_CLIENT_ID=
MOSAIC_CLIENT_SECRET=
MOSAIC_SCOPES=

# Grading Engine (deferred)
GRADING_ENGINE_BASE_URL=
GRADING_ENGINE_TOKEN_URL=
GRADING_ENGINE_CLIENT_ID=
GRADING_ENGINE_CLIENT_SECRET=
GRADING_ENGINE_SCOPES=api
```

---

## Appendix A: Sample Data

### A.1 Sample `mosaic_meta.json`

Source: `deployment/lds/content/minio/exam-associate-auto-v1.1-lab-2.5.1/mosaic_meta.json`

```json
{
  "DatePublished": "2025-Oct-31 01:51:43",
  "Version": "40",
  "Publisher": "epm-support",
  "Layout": "LDSv3",
  "FormName": "LAB-2.5.1",
  "FormStatus": "New",
  "FormId": "689def820afbb9684397e666",
  "FormSetId": "689def820afbb9684397e661",
  "ModuleId": "689cbd3048c08965b1ea3651",
  "ModuleTypeName": "Lablet",
  "ExamId": "63f4db8fdde08f3096df2103",
  "ExamVersion": "1.1",
  "TrackId": "63f4db8edde08f3096df2101",
  "TrackShortName": "AUTO",
  "TrackLongName": "200-901 CCNAAUTO",
  "InstanceName": "mosaic-auto.aps.certs.cloud",
  "InstanceType": "aws-k8s-pod",
  "InstanceRegion": "us-west-1",
  "InstanceAudience": "private",
  "InstanceDB": "mongodb-auto-aps",
  "OutstandingCommentsCount": 1,
  "OutstandingRatings": 0,
  "ValidatedBeforePublishing": false,
  "Language": "ENU",
  "storageFolder": "200-901"
}
```

**Fields to extract**:

- `Version` → `upstream_version`
- `DatePublished` → `upstream_date_published`
- `InstanceName` → `upstream_instance_name`
- `FormId` → `upstream_form_id`

### A.2 Sample Package Structure (extracted zip)

```
Lablet_LAB-2.5.1/
├── content/
│   └── section_01.xml
├── resources/
│   └── guidelines.html
├── RCUv1/
│   ├── cml.yaml              ← cml_yaml_path = "Lablet_LAB-2.5.1/RCUv1/cml.yaml"
│   ├── devices.json           ← extracted and stored in state
│   ├── grade.xml              ← grade_xml_path = "Lablet_LAB-2.5.1/RCUv1/grade.xml"
│   └── pod.xml
├── images/
│   └── topology.png
├── mosaic_meta.json           ← metadata extraction
└── content.xml                ← device definitions (<device> elements)
```

### A.3 Sample `devices.json`

```json
{
  "default_instance_type": "m5zn.metal",
  "device_type": "cml",
  "ami_name": "cisco-cml2.9-lablet-v0.1.5",
  "disk_type": "io1",
  "disk_size": 256,
  "public_ip": 1,
  "lab_type": "lablet"
}
```

### A.4 Sample Environment Resolver Response

```json
{
  "MOSAIC_BASE_URL": "https://mosaic-inf.ccie.certs.cloud/",
  "PYLDS_BASE_URL": "https://labs.expert.certs.cloud",
  "MINIO_BASE_URL": "https://minio.expert.certs.cloud",
  "MOZART_BASE_URL": "https://mozart.expert.certs.cloud",
  "VARIABLES_GENERATOR_BASE_URL": "https://variables-generator.sj.ccie.cisco.com",
  "MOSAIC_MAJOR_RELEASE": "7"
}
```

---

## Appendix B: API Endpoint Reference

### B.1 Mosaic API

| Method | Endpoint | Purpose | Auth |
|--------|----------|---------|------|
| `GET` | `/api/v1/latest/publishrecords?qualifiedName={fqn}` | Get latest publish records | JWT (client credentials) |
| `GET` | `/api/file/download/package/{publishedRecordId}` | Download zip package | JWT (client credentials) |

### B.2 LDS API

| Method | Endpoint | Purpose | Auth |
|--------|----------|---------|------|
| `PUT` | `/reservations/v3/lab_folder/minio/{form_qualified_name}` | Trigger content refresh from MinIO | HTTP Basic |
| `GET` | `/reservations/v3/lab_folder/minio/{form_qualified_name}` | Get content stats | HTTP Basic |
| `GET` | `/reservations/v3/lab_folder/minio/{form_qualified_name}/validate` | Validate content integrity | HTTP Basic |

### B.3 Grading Engine API (Deferred)

| Method | Endpoint | Purpose | Auth |
|--------|----------|---------|------|
| `POST` | `/api/v1/sessions/parts/ruleset/grading/synchronize` | Sync grading toolkit | OAuth2 (Keycloak) |

Body: `{ "partId": "{form_qualified_name}" }`

### B.4 Environment Resolver API

| Method | Endpoint | Purpose | Auth |
|--------|----------|---------|------|
| `POST` | `/resolve` | Resolve FQN to service URLs | JWT (optional, client credentials) |

Body: `{ "qualifiedName": "...", "environment": "CERTS-DEV" }`

### B.5 CPA Internal API (New Endpoints)

| Method | Endpoint | Purpose | Auth |
|--------|----------|---------|------|
| `GET` | `/api/internal/lablet-definitions?sync_status=sync_requested` | Get definitions needing sync | X-API-Key |
| `POST` | `/api/internal/lablet-definitions/{id}/content-synced` | Report sync result | X-API-Key |

---

## Appendix C: Upstream Notifier Pattern (Deferred)

### Future Vision

Define per-definition notification templates as seed configs:

```yaml
# data/seeds/sync_templates/lablet_synchronization.yaml
name: "lablet_synchronization"
description: "Notifications during content synchronization"
notifications:
  - service: "lds"
    method: "PUT"
    url_template: "{lds_base_url}/reservations/v3/lab_folder/minio/{form_qualified_name}"
    auth_type: "basic"
    auth_config_ref: "lds_deployments"
    required: true

  - service: "grading_engine"
    method: "POST"
    url_template: "{grading_engine_base_url}/api/v1/sessions/parts/ruleset/grading/synchronize"
    auth_type: "oauth2_client_credentials"
    auth_config_ref: "grading_engine_oauth"
    body_template: '{"partId": "{form_qualified_name}"}'
    required: false

  - service: "pod_automator"
    method: "POST"
    url_template: "{pod_automator_base_url}/api/v1/sync"
    auth_type: "oauth2_client_credentials"
    auth_config_ref: "pod_automator_oauth"
    required: false
```

Each LabletDefinition would reference a template:

```python
sync_template_name: str = "lablet_synchronization"  # References seed config
```

The ContentSyncService would load the template and execute notifications in parallel.

**Not implemented in this phase** — the direct LDS call suffices for now. The pattern will be introduced when Pod-Automator and Variables-Generator APIs are defined.

---

## Implementation Order Summary

| Phase | Scope | Effort | Status | Dependencies |
|-------|-------|--------|--------|-------------|
| **Phase 1** | Domain model (lcm-core + CPA entities, events, DTOs) | Medium | ✅ Complete | None |
| **Phase 2** | CPA commands, internal API, controller updates | Medium | ✅ Complete | Phase 1 ✅ |
| **Phase 3** | Integration clients (S3, EnvResolver, Mosaic, LDS, OAuth2) | Medium | ✅ Complete | Phase 2 ✅ |
| **Phase 4** | ContentSyncService + LabletReconciler integration | Large | ✅ Complete | Phase 1–3 ✅ |
| **Phase 5** | UI changes (sync button, form updates, status badges) | Medium | ⬜ Not started | Phase 2 ✅ |
| **Phase 6** | Keycloak scope + authorization | Small | ⬜ Not started | Phase 2 ✅ |
| **Phase 7** | Tests | Large | ⬜ Not started | Phase 1–4 ✅ |
| **Phase 8** | Documentation & env config | Small | ⬜ Not started | All phases |

**Recommended execution**: ~~Phase 1~~ → ~~Phase 2~~ → ~~Phase 3~~ → ~~Phase 4~~ → **Phase 5** → Phase 6 → Phase 7 → Phase 8

**Next up**: Phase 5 (UI Changes) — all prerequisites satisfied (Phase 2 complete).
