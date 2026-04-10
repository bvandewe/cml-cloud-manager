# Batch I: LabletDefinitionState → TimedResourceState (Layer 2) — Bootstrap Prompt

> **Date:** 2026-03-10
> **Decision:** AD-I0
> **Scope:** Promote the last aggregate extending raw `AggregateState[str]` into the resource hierarchy
> **Audience:** AI coding agent implementing the changes

---

## 1. MISSION

Change `LabletDefinitionState`'s base class from `AggregateState[str]` to `TimedResourceState` (Layer 2),
making LabletDefinition a **time-bounded, lifecycle-tracked managed resource**. After this batch,
**every managed aggregate** in the system extends the resource hierarchy — closing the last gap in ADR-036.

**Key Semantic:** Definitions are templates with **timeslots that control availability**. A definition is
only available for instantiation during its valid timeslot window. When the timeslot expires, the definition
automatically becomes unavailable. Authorized users can extend timeslots via `Timeslot.extend()`.

---

## 2. REFERENCE ARCHITECTURE

### 2.1 Inheritance Hierarchy (Target)

```
AggregateState[str]                           ← Neuroglia base
  └── ResourceState                           ← Layer 1 (lcm_core)
        │   id, resource_type, status, desired_status, owner_id,
        │   state_history: list, pipeline_progress, created_at, updated_at
        │   _record_transition()
        │
        └── TimedResourceState                ← Layer 2 (lcm_core)
              │   timeslot: dict|None, lifecycle: dict|None,
              │   started_at, ended_at, duration_seconds, terminated_at
              │   get_timeslot()/set_timeslot(), get_lifecycle()/set_lifecycle()
              │
              ├── CMLWorkerState              ← ✅ Batch E
              ├── LabletSessionState          ← ✅ Batch F
              └── LabletDefinitionState       ← ⬜ THIS BATCH (I)

  └── ResourceState (Layer 1 only)
        └── LabRecordState                    ← ✅ Batch G (no timeslots)
```

### 2.2 Key Base Class Files

| Class | Location |
|-------|----------|
| `ResourceState` | `src/core/lcm_core/domain/entities/resource.py` (~101 lines) |
| `TimedResourceState` | `src/core/lcm_core/domain/entities/timed_resource.py` (~125 lines) |
| `StateTransition` | `src/core/lcm_core/domain/value_objects/state_transition.py` (~73 lines) |
| `Timeslot` | `src/core/lcm_core/domain/value_objects/timeslot.py` (~170 lines) |
| `ManagedLifecycle` | `src/core/lcm_core/domain/value_objects/managed_lifecycle.py` (~136 lines) |

---

## 3. CURRENT STATE — LabletDefinitionState

**File:** `src/control-plane-api/domain/entities/lablet_definition.py` (777 lines)

**Current base:** `AggregateState[str]`

### 3.1 Class-Level Field Annotations (All Fields)

```python
class LabletDefinitionState(AggregateState[str]):
    # Identity
    id: str
    name: str
    version: str
    form_qualified_name: str | None

    # Content / Artifact
    lab_artifact_uri: str
    lab_yaml_hash: str
    lab_yaml_cached: str | None
    bucket_name: str

    # Resource Requirements
    resource_requirements: ResourceRequirements
    license_affinity: list[LicenseType]
    node_count: int
    port_template: PortTemplate

    # Assessment
    grading_rules_uri: str | None
    user_session_package_name: str
    grading_ruleset_package_name: str
    user_session_type: str
    user_session_default_region: str | None

    # Configuration
    warm_pool_depth: int
    max_duration_minutes: int
    owner_notification: NotificationConfig | None
    pipelines: dict | None

    # Status & Lifecycle
    status: LabletDefinitionStatus              # ← Will shadow ResourceState.status (str)
    created_by: str                              # ← Will map to ResourceState.owner_id
    created_at: datetime                         # ← Overlaps with ResourceState.created_at
    updated_at: datetime                         # ← Overlaps with ResourceState.updated_at

    # Deprecation Tracking
    previous_version_id: str | None
    deprecated_by: str | None
    deprecated_at: datetime | None
    deprecation_reason: str | None
    replacement_version: str | None

    # Sync State
    last_synced_at: datetime | None
    sync_status: str | None
    content_package_hash: str | None

    # Upstream Metadata
    upstream_version: str | None
    upstream_date_published: str | None
    upstream_instance_name: str | None
    upstream_form_id: str | None
    upstream_sync_status: dict | None

    # Content Paths
    grade_xml_path: str | None
    cml_yaml_path: str | None
    cml_yaml_content: str | None
    devices_json: str | None

    # Init-only fields (not in class annotations)
    # self.lab_reuse_enabled: bool = False
    # self.multi_lab_enabled: bool = False
    # self.boot_lead_time_minutes: int | None = None
```

### 3.2 @dispatch Event Handlers (7 handlers for 7 event types)

| Handler Event | Status Change | Key State Mutations |
|---------------|---------------|---------------------|
| `LabletDefinitionCreatedDomainEvent` | → `PENDING_SYNC` | Sets ALL identity, content, config, resource fields. `created_by`, `created_at`, `updated_at` |
| `LabletDefinitionVersionCreatedDomainEvent` | → `PENDING_SYNC` | Creates new version: identity, resources, `previous_version_id` |
| `LabletDefinitionDeprecatedDomainEvent` | → `DEPRECATED` | Sets `deprecated_by`, `deprecated_at`, `deprecation_reason`, `replacement_version` |
| `LabletDefinitionArtifactSyncedDomainEvent` | Updates `sync_status` | Legacy sync: `last_synced_at`, `sync_status`, `content_package_hash` |
| `LabletDefinitionSyncRequestedDomainEvent` | → `PENDING_SYNC` | Status only |
| `LabletDefinitionContentSyncedDomainEvent` | → `ACTIVE` (on success) | Upstream metadata, content paths, sync result fields |
| `LabletDefinitionWarmPoolUpdatedDomainEvent` | — | `warm_pool_depth` only |
| `LabletDefinitionUpdatedDomainEvent` | — | Generic: applies `changes` dict to mutable fields |

### 3.3 Aggregate Methods on `LabletDefinition`

```python
LabletDefinition.create(id, name, version, lab_artifact_uri, ...) → LabletDefinition   # 20+ params
LabletDefinition.create_version(id, name, version, ...) → LabletDefinition              # 9 params
LabletDefinition.deprecate(deprecated_by, reason, replacement_version)
LabletDefinition.request_sync()                                                          # Legacy
LabletDefinition.record_artifact_sync(content_package_hash, sync_status)                 # Legacy
LabletDefinition.record_content_sync(sync_status, ..., cml_yaml_content, ...)           # 14 params
LabletDefinition.update_warm_pool_depth(warm_pool_depth)
LabletDefinition.update(changes)                                                         # Generic dict
```

### 3.4 LabletDefinitionStatus Enum

```python
# src/core/lcm_core/domain/enums/lablet_definition_status.py
class LabletDefinitionStatus(CaseInsensitiveStrEnum):
    PENDING_SYNC = "pending_sync"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"
```

**Design consideration:** Add `EXPIRED = "expired"` for timeslot-driven automatic expiry
(distinct from manual `DEPRECATED`). This is _optional_ for Batch I — can be deferred.

### 3.5 Domain Events (10 defined, 7 used by handlers)

**File:** `src/control-plane-api/domain/events/lablet_definition_events.py` (443 lines)

All extend `DomainEvent`, decorated with `@cloudevent` and `@dataclass`:

| Event Class | CloudEvent Type |
|-------------|-----------------|
| `LabletDefinitionCreatedDomainEvent` | `lablet_definition.created.v1` |
| `LabletDefinitionVersionCreatedDomainEvent` | `lablet_definition.version_created.v1` |
| `LabletDefinitionDeprecatedDomainEvent` | `lablet_definition.deprecated.v1` |
| `LabletDefinitionArtifactSyncedDomainEvent` | `lablet_definition.artifact_synced.v1` |
| `LabletDefinitionSyncRequestedDomainEvent` | `lablet_definition.sync_requested.v1` |
| `LabletDefinitionContentSyncedDomainEvent` | `lablet_definition.content_synced.v1` |
| `LabletDefinitionWarmPoolUpdatedDomainEvent` | `lablet_definition.warm_pool_updated.v1` |
| `LabletDefinitionUpdatedDomainEvent` | `lablet_definition.updated.v1` |
| `LabletDefinitionArchivedDomainEvent` | `lablet_definition.archived.v1` _(unused)_ |
| `LabletDefinitionActivatedDomainEvent` | `lablet_definition.activated.v1` _(unused)_ |
| `LabletDefinitionDeletedDomainEvent` | `lablet_definition.deleted.v1` _(unused)_ |

---

## 4. MIGRATION PATTERN — What Batch G Did (Follow This Pattern)

Batch G promoted `LabRecordState` from `AggregateState[str]` → `ResourceState` (Layer 1).
Batch I follows the **same pattern** but targets `TimedResourceState` (Layer 2).

### 4.1 Base Class Change

```python
# BEFORE (Batch G):
class LabRecordState(AggregateState[str]):

# AFTER (Batch G):
class LabRecordState(ResourceState):
```

**For Batch I:**

```python
# BEFORE:
class LabletDefinitionState(AggregateState[str]):

# AFTER:
class LabletDefinitionState(TimedResourceState):
```

### 4.2 `__init__` Method — Wire Inherited Fields

```python
def __init__(self):
    super().__init__()  # Initializes all ResourceState + TimedResourceState fields

    # Wire resource_type (mandatory for ResourceState)
    self.resource_type = "lablet_definition"

    # status and desired_status are inherited — status will be shadowed by enum field
    self.desired_status = None  # Not used initially

    # owner_id is inherited — will be set from created_by in event handlers
    # state_history is inherited — initialized to [] by parent
    # timeslot, lifecycle, etc. — initialized to None by parent

    # ... existing LabletDefinitionState-specific field defaults ...
```

### 4.3 `_record_transition()` Override

Override in `LabletDefinitionState` to match Batch G/F pattern:

```python
def _record_transition(self, from_state, to_state, triggered_by="system",
                       reason=None, metadata=None):
    """Override to store StateTransition dicts (Neuroglia serialization compatible)."""
    transition = StateTransition(
        from_state=str(from_state) if from_state else None,
        to_state=str(to_state),
        transitioned_at=datetime.now(UTC),
        triggered_by=triggered_by,
        reason=reason,
        metadata=metadata,
    )
    self.state_history.append(transition.to_dict())
    self.updated_at = transition.transitioned_at
```

### 4.4 Event Handlers — Add `_record_transition()` Calls

Every `@dispatch` handler that changes `self.status` must call `_record_transition()`:

```python
@dispatch(LabletDefinitionCreatedDomainEvent)
def on(self, event: LabletDefinitionCreatedDomainEvent) -> None:
    # ... existing field assignments ...
    self.status = LabletDefinitionStatus.PENDING_SYNC

    # NEW: Wire owner_id from created_by
    self.owner_id = event.created_by

    # NEW: Record initial transition
    self._record_transition(
        from_state=None,
        to_state=self.status.value,
        triggered_by=event.created_by,
        reason="Definition created",
    )

    # NEW: Set lifecycle (optional — if LABLET_DEFINITION_LIFECYCLE is defined)
    # self.set_lifecycle(LABLET_DEFINITION_LIFECYCLE)

    # NEW: Set timeslot (if provided via event — likely None at creation time)
    # if event.timeslot:
    #     self.set_timeslot(event.timeslot)
```

**Apply to ALL status-changing handlers:**

| Event Handler | From → To | triggered_by | reason |
|---------------|-----------|--------------|--------|
| `Created` | None → `PENDING_SYNC` | `event.created_by` | "Definition created" |
| `VersionCreated` | None → `PENDING_SYNC` | `"system"` | "New version created" |
| `Deprecated` | current → `DEPRECATED` | `event.deprecated_by` | event reason or "Definition deprecated" |
| `SyncRequested` | current → `PENDING_SYNC` | `"system"` | "Sync requested" |
| `ContentSynced` | (conditionally) → `ACTIVE` | `"system"` | "Content sync completed" |

**Non-status-changing handlers** (`ArtifactSynced`, `WarmPoolUpdated`, `Updated`):
No `_record_transition()` needed (only for actual status changes, matching Batch G conditional pattern).

### 4.5 Status Shadowing

`LabletDefinitionStatus` (typed enum) must shadow `ResourceState.status` (str).
Declare it at class level with type annotation:

```python
class LabletDefinitionState(TimedResourceState):
    status: LabletDefinitionStatus  # Shadows ResourceState.status (str)
```

This works because `LabletDefinitionStatus` extends `CaseInsensitiveStrEnum` which is str-compatible.

### 4.6 Field Overlap Resolution

| ResourceState Field | LabletDefinitionState Equivalent | Resolution |
|---------------------|----------------------------------|------------|
| `id: str` | `id: str` | ✅ Same — no change needed |
| `resource_type: str` | _(new)_ | Set to `"lablet_definition"` in `__init__` |
| `status: str` | `status: LabletDefinitionStatus` | Shadow with typed enum (§4.5) |
| `desired_status: str\|None` | _(new)_ | Default `None` — unused initially |
| `owner_id: str` | `created_by: str` | Map `owner_id = created_by` in Created handler. Keep `created_by` for backward compat. |
| `state_history: list` | _(new)_ | Inherited, `[]` default. Populated by `_record_transition()` |
| `pipeline_progress: dict\|None` | `pipelines: dict\|None` | Different semantics! `pipeline_progress` = runtime execution state, `pipelines` = pipeline configuration. Keep both. |
| `created_at: datetime` | `created_at: datetime` | ✅ Same — shadows parent, keep class-level annotation |
| `updated_at: datetime` | `updated_at: datetime` | ✅ Same — shadows parent, keep class-level annotation |
| `timeslot: dict\|None` | _(new)_ | Inherited from TimedResourceState, `None` default |
| `lifecycle: dict\|None` | _(new)_ | Inherited from TimedResourceState, `None` default |
| `started_at: datetime\|None` | _(new)_ | Inherited, `None` default |
| `ended_at: datetime\|None` | _(new)_ | Inherited, `None` default |
| `duration_seconds: float\|None` | _(new)_ | Inherited, `None` default |
| `terminated_at: datetime\|None` | _(new)_ | Inherited, `None` default |

### 4.7 Lifecycle Constant (NEW — Create in Batch I)

Add `LABLET_DEFINITION_LIFECYCLE` to `src/control-plane-api/domain/lifecycles.py`:

```python
LABLET_DEFINITION_LIFECYCLE = ManagedLifecycle(
    phases=(
        LifecyclePhase(name="sync_content",       engine="pipeline", trigger_on_status="pending_sync", is_required=True),
        LifecyclePhase(name="activate",            engine="pipeline", trigger_on_status="active",       is_required=True),
        LifecyclePhase(name="deprecate",           engine="pipeline", trigger_on_status="deprecated",   is_required=False),
        LifecyclePhase(name="archive",             engine="pipeline", trigger_on_status="archived",     is_required=False),
    ),
)
```

**Note:** This is a _minimal_ lifecycle. Adjust phases based on actual definition lifecycle flows.
The `sync_content` phase is the most important — it maps to the content sync pipeline that transitions
`PENDING_SYNC → ACTIVE`.

### 4.8 Import Changes

Add to `lablet_definition.py` imports:

```python
from lcm_core.domain.entities.timed_resource import TimedResourceState
from lcm_core.domain.value_objects.state_transition import StateTransition

# Optional — if wiring lifecycle at creation time:
# from domain.lifecycles import LABLET_DEFINITION_LIFECYCLE
```

Remove or keep `AggregateState` import based on whether other code in the file uses it.

---

## 5. COMMANDS & QUERIES (Impact Assessment)

### 5.1 Commands

| File | Command | Impact |
|------|---------|--------|
| `application/commands/create_definition_command.py` | `CreateDefinitionCommand` | **Low** — No changes needed. Handler calls `LabletDefinition.create()` which records the event. |
| `application/commands/create_definition_version_command.py` | `CreateDefinitionVersionCommand` | **Low** — Same pattern. |
| `application/commands/deprecate_definition_command.py` | `DeprecateDefinitionCommand` | **Low** — Same pattern. |
| `application/commands/update_definition_command.py` | `UpdateDefinitionCommand` | **Low** — Same pattern. |

### 5.2 Queries

| File | Query | Impact |
|------|-------|--------|
| `application/queries/get_definition_query.py` | `GetDefinitionQuery` | **Low** — Returns existing DTO. |
| `application/queries/list_definitions_query.py` | `ListDefinitionsQuery` | **Low** — Returns existing DTOs. |
| `application/queries/get_definition_names_query.py` | `GetDefinitionNamesQuery` | **Low** — Returns names only. |

**Verdict:** Commands and queries are unlikely to need changes. The entity itself
handles the base class migration transparently via its event handlers.

### 5.3 DTOs (Optional Enhancement)

After Batch I, `LabletDefinitionDetailDto` can be enriched with:

- `desired_status: str | None`
- `state_history: list[dict]`
- `timeslot: dict | None`
- `lifecycle: dict | None`
- `owner_id: str`

These are additive changes to the mapper function `_map_to_detail_dto()`.
This can be done as a follow-up or as part of Batch I — your choice.

---

## 6. REPOSITORY (Impact Assessment)

**Interface:** `src/control-plane-api/domain/repositories/lablet_definition_repository.py`
**Implementation:** `src/control-plane-api/integration/repositories/lablet_definition_repository.py`

**Impact: None.** The Motor repository serializes/deserializes via Neuroglia's `AggregateState`
machinery, which walks the MRO for field annotations. New fields from `ResourceState` and
`TimedResourceState` (state_history, timeslot, lifecycle, etc.) are automatically handled
with their `__init__` defaults.

**Backward compatibility:** Existing MongoDB documents without the new fields will
deserialize correctly because all new fields have sensible defaults (`[]`, `None`, `""`, etc.)
via the `__init__` chain.

---

## 7. TESTS TO WRITE

Follow the Batch G test structure from `tests/domain/test_lab_record_resource_state_migration.py`.

### 7.1 Test File

Create: `src/control-plane-api/tests/domain/test_lablet_definition_timed_resource_migration.py`

### 7.2 Test Classes

```python
class TestLabletDefinitionInheritsTimedResourceState:
    """Verify LabletDefinitionState properly inherits TimedResourceState (Layer 2)."""

    def test_inherits_timed_resource_state(self):
        """LabletDefinitionState must be a subclass of TimedResourceState."""

    def test_has_resource_type(self):
        """resource_type should be 'lablet_definition'."""

    def test_has_desired_status_none_by_default(self):
        """desired_status defaults to None."""

    def test_has_state_history_empty_by_default(self):
        """state_history defaults to empty list."""

    def test_has_owner_id_field(self):
        """owner_id field inherited from ResourceState."""

    def test_has_timeslot_none_by_default(self):
        """timeslot defaults to None (no timeslot assigned at creation)."""

    def test_has_lifecycle_none_by_default(self):
        """lifecycle defaults to None."""

    def test_has_timed_fields(self):
        """started_at, ended_at, duration_seconds, terminated_at default to None."""

    def test_has_pipeline_progress_none_by_default(self):
        """pipeline_progress defaults to None."""


class TestLabletDefinitionStateHistory:
    """Verify state_history tracking via _record_transition()."""

    def test_created_event_records_initial_transition(self):
        """Creating a definition should add a transition from None → PENDING_SYNC."""

    def test_deprecation_records_transition(self):
        """Deprecating should record current → DEPRECATED transition."""

    def test_content_sync_records_transition_to_active(self):
        """Successful content sync should record → ACTIVE transition."""

    def test_sync_requested_records_transition(self):
        """Requesting sync should record → PENDING_SYNC transition."""

    def test_state_history_stores_dicts(self):
        """Each entry in state_history should be a plain dict (not StateTransition)."""

    def test_state_history_dict_has_required_keys(self):
        """Each dict must have from_state, to_state, transitioned_at, triggered_by."""

    def test_state_history_accumulates(self):
        """Multiple transitions should accumulate in state_history list."""

    def test_updated_at_tracks_transitions(self):
        """updated_at should be updated on each transition."""


class TestLabletDefinitionConditionalTransitions:
    """Verify no spurious transitions on non-status-changing events."""

    def test_warm_pool_update_no_transition(self):
        """WarmPoolUpdated should NOT add to state_history."""

    def test_artifact_sync_no_transition(self):
        """ArtifactSynced should NOT add to state_history (status may be unchanged)."""

    def test_generic_update_no_transition(self):
        """Updated event should NOT add to state_history."""


class TestLabletDefinitionStatusShadowing:
    """Verify LabletDefinitionStatus enum shadows ResourceState.status correctly."""

    def test_status_is_lablet_definition_status_enum(self):
        """After creation, status should be LabletDefinitionStatus instance."""

    def test_status_is_str_comparable(self):
        """Status should be comparable to plain strings (CaseInsensitiveStrEnum)."""


class TestLabletDefinitionOwnerMapping:
    """Verify created_by → owner_id mapping."""

    def test_owner_id_set_on_create(self):
        """owner_id should equal created_by after creation."""

    def test_created_by_still_available(self):
        """created_by field should still be populated (backward compat)."""


class TestLabletDefinitionStateTransitionImport:
    """Verify StateTransition comes from lcm_core."""

    def test_state_transition_from_lcm_core(self):
        """StateTransition should be importable from lcm_core.domain.value_objects."""

    def test_state_transition_round_trip(self):
        """StateTransition.to_dict() and from_dict() should round-trip correctly."""
```

**Estimated: ~25 tests** (matches Batch G's ~30 tests, minus the pending_action-specific tests
that don't apply to definitions).

---

## 8. IMPLEMENTATION CHECKLIST

### Phase 1: Entity Migration

- [ ] **Change base class:** `AggregateState[str]` → `TimedResourceState`
- [ ] **Update imports:** Add `TimedResourceState`, `StateTransition` from `lcm_core`
- [ ] **Wire `__init__`:** Set `resource_type = "lablet_definition"`, `desired_status = None`
- [ ] **Override `_record_transition()`:** Store dicts via `StateTransition.to_dict()`
- [ ] **Update Created handler:** Map `owner_id = created_by`, call `_record_transition()`
- [ ] **Update VersionCreated handler:** Call `_record_transition()` (None → PENDING_SYNC)
- [ ] **Update Deprecated handler:** Record status → DEPRECATED transition
- [ ] **Update SyncRequested handler:** Record status → PENDING_SYNC transition
- [ ] **Update ContentSynced handler:** Conditionally record → ACTIVE transition (only when status changes)
- [ ] **Verify non-status handlers:** `ArtifactSynced`, `WarmPoolUpdated`, `Updated` should NOT call `_record_transition()`
- [ ] **Shadow status field:** Keep `status: LabletDefinitionStatus` class annotation (shadows parent `str`)

### Phase 2: Lifecycle Constant (Optional)

- [ ] **Create `LABLET_DEFINITION_LIFECYCLE`** in `domain/lifecycles.py`
- [ ] **Wire in Created handler** (optional — set lifecycle at creation time)

### Phase 3: Tests

- [ ] **Create test file:** `tests/domain/test_lablet_definition_timed_resource_migration.py`
- [ ] **Implement ~25 tests** per §7.2 test plan
- [ ] **Run existing tests:** All 1109 CPA tests must still pass
- [ ] **Run all services:** RS (172), WC (100), LC (427) must still pass

### Phase 4: DTO Enhancement (Optional — can defer)

- [ ] **Extend `LabletDefinitionDetailDto`** with `desired_status`, `state_history`, `owner_id`
- [ ] **Extend `LabletDefinitionDetailDto`** with `timeslot`, `lifecycle` (after timeslot support is wired)
- [ ] **Update mapper function** `_map_to_detail_dto()`

### Phase 5: Verification

- [ ] `make lint` passes (CPA)
- [ ] `make test` passes (CPA — all 1109+ tests)
- [ ] `make test` passes (core — all 263+ tests)
- [ ] `make test` passes (RS, WC, LC — unchanged)
- [ ] No MongoDB backward compatibility issues (new fields default gracefully)

---

## 9. CONSTRAINTS & GUIDELINES

1. **Backward compatible** — Existing MongoDB documents MUST deserialize correctly without migration
2. **No behavioral changes** — Existing aggregate methods MUST produce identical domain events
3. **Dict-based state_history** — Use `StateTransition.to_dict()` for Neuroglia serialization (not raw objects)
4. **`.value` for enum-to-str** — When calling `_record_transition()`, pass `self.status.value` not `self.status`
5. **Shadow, don't rename** — Keep `status: LabletDefinitionStatus` annotation to shadow parent's `str`
6. **Keep `created_by`** — Set `owner_id = created_by` in handler but don't remove `created_by` field
7. **Keep `pipelines`** — It's pipeline _configuration_, distinct from `pipeline_progress` (runtime state)
8. **All imports at module level** — No inline imports (per project convention)
9. **Conditional transitions only** — Only call `_record_transition()` when `self.status` actually changes
10. **Test naming** — Follow `test_lablet_definition_timed_resource_migration.py` pattern from Batch G

---

## 10. FILES TO MODIFY

| File | Change |
|------|--------|
| `control-plane-api/domain/entities/lablet_definition.py` | Base class, `__init__`, `_record_transition()`, 5 event handlers |
| `control-plane-api/domain/lifecycles.py` | Add `LABLET_DEFINITION_LIFECYCLE` constant |
| `control-plane-api/tests/domain/test_lablet_definition_timed_resource_migration.py` | **NEW** — ~25 migration tests |

**Optional (can defer):**

| File | Change |
|------|--------|
| `control-plane-api/application/dtos/lablet_definition_dtos.py` | Add `desired_status`, `state_history`, `owner_id`, `timeslot`, `lifecycle` |
| `control-plane-api/application/mapping/lablet_definition_mapper.py` | Map new fields in `_map_to_detail_dto()` |
| `docs/implementation/adr036-phase2-implementation-plan.md` | Mark Batch I ✅ Complete |
| `docs/implementation/IMPLEMENTATION_STATUS.md` | Update Batch I status |
| `TODO.md` | Mark Batch I complete |

---

## 11. VERIFICATION COMMANDS

```bash
# From project root:
cd src/control-plane-api && make lint       # Ruff linting
cd src/control-plane-api && make test       # All CPA tests (~1109)
cd src/core && make test                    # All core tests (~263)
cd src/resource-scheduler && make test      # RS tests (~172) — should be unaffected
cd src/worker-controller && make test       # WC tests (~100) — should be unaffected
cd src/lablet-controller && make test       # LC tests (~427) — should be unaffected
```

---

## 12. REFERENCE: Batch G diff-like Summary (LabRecordState Migration)

For quick pattern reference, here is how Batch G modified `LabRecordState`:

```python
# 1. Base class: AggregateState[str] → ResourceState
class LabRecordState(ResourceState):  # was AggregateState[str]

# 2. __init__: wire resource_type
    def __init__(self):
        super().__init__()
        self.resource_type = "lab_record"
        self.desired_status = None
        # ... existing fields ...

# 3. _record_transition() override
    def _record_transition(self, from_state, to_state, triggered_by="system",
                           reason=None, metadata=None):
        transition = StateTransition(
            from_state=str(from_state) if from_state else None,
            to_state=str(to_state),
            transitioned_at=datetime.now(UTC),
            triggered_by=triggered_by,
            reason=reason,
            metadata=metadata,
        )
        self.state_history.append(transition.to_dict())
        self.updated_at = transition.transitioned_at

# 4. In EVERY status-changing @dispatch handler:
    @dispatch(SomeStatusChangingEvent)
    def on(self, event):
        old_status = self.status
        # ... existing logic ...
        self.status = NewStatus
        if str(self.status) != str(old_status):
            self._record_transition(
                from_state=old_status.value if old_status else None,
                to_state=self.status.value,
                triggered_by="system",
                reason="Descriptive reason",
            )
```

**Apply this exact pattern to LabletDefinitionState — just targeting TimedResourceState
instead of ResourceState, and adding the Layer 2 fields (timeslot, lifecycle) initialization.**
