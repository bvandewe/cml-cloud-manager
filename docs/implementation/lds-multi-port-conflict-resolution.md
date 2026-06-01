# Implementation Plan: LDS Multi-Port Device Conflict Resolution

**Status:** Phase 1 Complete ✅ | Phase 2 Complete ✅ | Phase 3 Complete ✅
**Date:** 2026-05-31
**Priority:** P0 (production failure)
**Affected Services:** lablet-controller, control-plane-api (UI)
**Related ADRs:** AD-LDS-001, AD-LDS-002

---

## Problem Statement

When a CML node has **multiple annotations** (e.g., `serial:2003` + `vnc:2004` on `ubuntu-desktop`), the `lds_provision` pipeline step creates multiple `DeviceAccessInfo` entries with the **same `device_label`**. LDS rejects the duplicate with a `UniqueViolation` on `(session_part_id, device_label)`.

### Root Cause

1. `cml.xml` node `ubuntu-desktop` has two annotations → `serial:2003`, `vnc:2004`
2. Content sync creates two port definitions: `ubuntu-desktop_serial`, `ubuntu-desktop_vnc`
3. `ports_alloc` allocates both → `{"ubuntu-desktop_serial": 2003, "ubuntu-desktop_vnc": 2004}`
4. `build_device_access_from_allocated_ports()` parses both, producing two `DeviceAccessInfo` entries with `device_label="ubuntu-desktop"`
5. LDS INSERT fails on second device: unique constraint violation

### Key Constraint

LDS `user_access_mode` has only two values:

- `web`: Traffic is proxied via LDS access_proxy (routes telnet/vnc → websocket)
- `local`: Native protocol URLs (`telnet://`, `vnc://`, `rdp://`, `http://`)

`user_access_mode` does **NOT** indicate protocol preference — it indicates transport delivery mode. The system must independently determine which single protocol to send per device.

---

## Solution Design (AD-LDS-002)

### Approach: Global Protocol Priority + User Override

**Phase 1** (immediate): Global setting defining default protocol priority for resolving multi-port conflicts (e.g., `vnc > http > rdp > ssh > serial > telnet`). Applied automatically at runtime.

**Phase 2** (later): Detection at content sync time — flag conflicting devices in the DTO.

**Phase 3** (later): User-configurable per-device port preferences stored on `LabletDefinition`, overriding the global default.

---

## Phase 1: Global Protocol Priority (Runtime Fix)

### Design

Add a `lds_protocol_priority` setting to the lablet-controller:

```python
lds_protocol_priority: list[str] = ["vnc", "http", "https", "rdp", "ssh", "serial", "telnet"]
```

When `build_device_access_from_allocated_ports()` encounters multiple ports mapping to the same `device_label`, it selects the **highest-priority protocol** from this list.

### Changes

| File | Change |
|------|--------|
| `application/settings.py` | Add `lds_protocol_priority` setting |
| `application/services/reconciler_helpers/lds_helpers.py` | Add dedup logic to `build_device_access_from_allocated_ports()` |
| `application/services/step_handlers/binding_steps.py` | Pass `protocol_priority` from context/settings |
| `application/models/pipeline_context.py` | Add `lds_protocol_priority` to context |
| `tests/test_lds_device_mapping.py` | Fix existing test + add multi-port dedup tests |

### Data Flow (Fixed)

```
allocated_ports = {"ubuntu-desktop_serial": 2003, "ubuntu-desktop_vnc": 2004}
                                       │
                     ┌─────────────────┘
                     ▼
    group by device_label → {"ubuntu-desktop": [("serial", 2003), ("vnc", 2004)]}
                     │
                     ▼
    apply priority  → pick "vnc" (higher in lds_protocol_priority)
                     │
                     ▼
    result: [DeviceAccessInfo(device_label="ubuntu-desktop", protocol="vnc", port=2004)]
```

### Implementation Details

#### 1. Settings (`application/settings.py`)

```python
# LDS protocol priority for multi-port device resolution (AD-LDS-002)
lds_protocol_priority: list[str] = ["vnc", "http", "https", "rdp", "ssh", "serial", "telnet"]
```

#### 2. `lds_helpers.py` — Deduplication Logic

The `build_device_access_from_allocated_ports()` function receives an optional `protocol_priority` parameter. When multiple ports resolve to the same `device_label`, the entry with the highest-priority protocol wins.

#### 3. `binding_steps.py` — Pass Priority

Read from `context.settings.lds_protocol_priority` and pass to the helper.

#### 4. `PipelineContext` — Add Setting

Either pass settings directly or expose `lds_protocol_priority` on context.

---

## Phase 2: Content Sync Detection (Future)

During content sync, cross-reference `port_template` ports with `user_visible_devices`:

```python
port_conflicts = [
    {
        "device_label": "ubuntu-desktop",
        "available_ports": ["ubuntu-desktop_serial", "ubuntu-desktop_vnc"],
        "resolved_port": "ubuntu-desktop_vnc",  # Based on global priority
    }
]
```

Store as `port_conflicts` on `LabletDefinitionState` and expose in DTO.

### Changes

| File | Change |
|------|--------|
| `src/lablet-controller/application/hosted_services/content_sync_service.py` | `_detect_port_conflicts()` static method + `_resolve_port_by_priority()` helper. Called after metadata extraction, cross-references port_template with user_visible_devices |
| `src/control-plane-api/domain/events/lablet_definition_events.py` | Added `port_conflicts: list[dict[str, Any]] \| None` to `LabletDefinitionContentSyncedDomainEvent` |
| `src/control-plane-api/domain/entities/lablet_definition.py` | Added `port_conflicts` to `LabletDefinitionState.__init__()` and `on(ContentSynced)` handler. Added parameter to `record_content_sync()` |
| `src/control-plane-api/application/commands/lablet_definition/record_content_sync_result_command.py` | Added `port_conflicts` field to command dataclass, passed to aggregate |
| `src/control-plane-api/api/controllers/internal_controller.py` | Added `port_conflicts` to `RecordContentSyncResultRequest` Pydantic model and command construction |
| `src/control-plane-api/application/dtos/lablet_definition_dto.py` | Added `port_conflicts` to `LabletDefinitionDto` and `map_lablet_definition_to_dto()` |
| `src/control-plane-api/ui/src/scripts/components/shared/definition-details-renderer.js` | `_renderPortConflictsWarning()` — warning alert with conflict table in Overview tab |
| `src/lablet-controller/tests/test_port_conflict_detection.py` | 15 tests: `TestResolvePortByPriority` (6 tests) + `TestDetectPortConflicts` (9 tests) |

---

## Phase 3: User-Configurable Port Preferences (Future)

- New field on `LabletDefinition`: `lds_port_preferences: dict[str, str] | None`
  (maps `device_label → port_name`, e.g., `{"ubuntu-desktop": "ubuntu-desktop_vnc"}`)
- New CQRS command: `SetLdsPortPreferencesCommand`
- UI: Warning badge + dropdown selector per conflicting device
- Runtime: preferences override global priority

---

## Test Plan

### Phase 1 Tests

1. **Multi-port device picks highest priority** — `ubuntu-desktop_serial` + `ubuntu-desktop_vnc` → only `vnc` sent
2. **Single-port devices unaffected** — no dedup needed, pass through unchanged
3. **Custom priority order** — configurable list changes winner selection
4. **Unknown protocol fallback** — protocol not in priority list → lowest priority (included only if no other candidate)
5. **Integration test fix** — `test_full_pipeline_visible_and_hidden_devices` updated to expect 2 devices (not 3)

---

## Execution Order

```
Phase 1 → Implement + test + deploy (unblocks production)  ✅ DONE 2026-05-31
Phase 2 → Surface conflicts in UI (informational)          ✅ DONE 2026-05-31
Phase 3 → User override (full control)                     ✅ DONE 2026-05-31
```

---

## Phase 1 Completion Record

**Implemented:** 2026-05-31
**Tests:** 27 pass (9 new dedup tests), full suite 481 pass

### Files Modified

| File | Change |
|------|--------|
| `src/lablet-controller/application/settings.py` | Added `lds_protocol_priority: list[str]` with default `["vnc", "http", "https", "rdp", "ssh", "serial", "telnet"]` |
| `src/lablet-controller/application/models/pipeline_context.py` | Added `lds_protocol_priority: list[str] \| None = None` field |
| `src/lablet-controller/application/services/reconciler_helpers/lds_helpers.py` | Two-pass algorithm: group by `device_label`, resolve via `_select_by_priority()`. Added `DEFAULT_PROTOCOL_PRIORITY` constant |
| `src/lablet-controller/application/services/step_handlers/binding_steps.py` | Passes `protocol_priority=context.lds_protocol_priority` to helper |
| `src/lablet-controller/application/hosted_services/lablet_reconciler.py` | Passes `lds_protocol_priority=self._settings.lds_protocol_priority` to PipelineContext |
| `src/lablet-controller/tests/test_lds_device_mapping.py` | Fixed integration test (was expecting 3 devices, now correctly expects 2). Added `TestMultiPortDeviceDedup` class with 9 tests |

### Behavior Change

```
Before: ubuntu-desktop_serial + ubuntu-desktop_vnc → 2 DeviceAccessInfo → LDS UniqueViolation ❌
After:  ubuntu-desktop_serial + ubuntu-desktop_vnc → 1 DeviceAccessInfo (vnc wins) → LDS success ✅
```

### Configuration

Override default priority via env var: `LDS_PROTOCOL_PRIORITY='["ssh","serial","vnc"]'`

---

## Phase 2 Completion Record

**Implemented:** 2026-05-31
**Tests:** 15 new tests (6 priority resolution + 9 conflict detection), full lablet-controller suite 496 pass, CPA suite 1037 pass

### Files Modified

| File | Change |
|------|--------|
| `src/lablet-controller/application/hosted_services/content_sync_service.py` | Added `_detect_port_conflicts()` static method + `_resolve_port_by_priority()` module helper. Cross-references port_template with user_visible_devices after metadata extraction |
| `src/control-plane-api/domain/events/lablet_definition_events.py` | Added `port_conflicts: list[dict[str, Any]] \| None` to `LabletDefinitionContentSyncedDomainEvent` |
| `src/control-plane-api/domain/entities/lablet_definition.py` | Added `port_conflicts` to `LabletDefinitionState.__init__()`, `on(ContentSynced)` handler, and `record_content_sync()` aggregate method |
| `src/control-plane-api/application/commands/lablet_definition/record_content_sync_result_command.py` | Added `port_conflicts` field to command dataclass, passed through to aggregate |
| `src/control-plane-api/api/controllers/internal_controller.py` | Added `port_conflicts` to `RecordContentSyncResultRequest` Pydantic model and command construction |
| `src/control-plane-api/application/dtos/lablet_definition_dto.py` | Added `port_conflicts` to `LabletDefinitionDto` and `map_lablet_definition_to_dto()` |
| `src/control-plane-api/ui/src/scripts/components/shared/definition-details-renderer.js` | `_renderPortConflictsWarning()` — warning alert with conflict table in Overview tab |
| `src/lablet-controller/tests/test_port_conflict_detection.py` | 15 tests: `TestResolvePortByPriority` (6) + `TestDetectPortConflicts` (9) |

### Data Flow

```
ContentSyncService._extract_metadata()
    → extracts port_template + user_visible_devices from zip
    → _detect_port_conflicts(port_template, devices, priority)
    → port_conflicts list added to sync_result dict
    → CPA internal API POST /content-synced
    → RecordContentSyncResultCommand.port_conflicts
    → LabletDefinition.record_content_sync(port_conflicts=...)
    → LabletDefinitionContentSyncedDomainEvent(port_conflicts=...)
    → LabletDefinitionState.port_conflicts
    → LabletDefinitionDto.port_conflicts
    → UI _renderPortConflictsWarning()
```

### UI Behavior

When `port_conflicts` is non-empty, the definition details modal Overview tab shows a warning alert:

- Orange `⚠ Port Conflicts (N)` banner
- Table with Device, Available Ports, and Resolved columns
- Informational only — auto-resolution happens at runtime via Phase 1 logic

---

## Phase 3 Completion Record

**Implemented:** 2026-05-31
**Tests:** 7 new preference tests, full lablet-controller suite 503 pass, CPA suite 1178 pass

### Files Modified

| File | Change |
|------|--------|
| `src/control-plane-api/domain/entities/lablet_definition.py` | Added `lds_port_preferences: dict[str, str] \| None` to `LabletDefinitionState.__init__()` and `on(Updated)` handler |
| `src/control-plane-api/application/commands/lablet_definition/set_lds_port_preferences_command.py` | **New file** — `SetLdsPortPreferencesCommand` + handler. Validates preferences against `port_conflicts` |
| `src/control-plane-api/application/commands/lablet_definition/__init__.py` | Registered new command in package exports |
| `src/control-plane-api/application/dtos/lablet_definition_dto.py` | Added `lds_port_preferences` to `LabletDefinitionDto` and mapping function |
| `src/control-plane-api/api/controllers/lablet_definitions_controller.py` | Added `PATCH /{id}/port-preferences` endpoint with `SetLdsPortPreferencesRequest` model |
| `src/core/lcm_core/domain/entities/read_models/lablet_definition_read_model.py` | Added `lds_port_preferences` field and `from_dict()` deserialization |
| `src/lablet-controller/application/models/pipeline_context.py` | Added `lds_port_preferences: dict[str, str] \| None = None` field |
| `src/lablet-controller/application/hosted_services/lablet_reconciler.py` | Passes `lds_port_preferences` from definition to PipelineContext |
| `src/lablet-controller/application/services/reconciler_helpers/lds_helpers.py` | Added `port_preferences` parameter. User preferences checked before protocol priority; graceful fallback on mismatch |
| `src/lablet-controller/application/services/step_handlers/binding_steps.py` | Passes `port_preferences=context.lds_port_preferences` to helper |
| `src/control-plane-api/ui/src/scripts/components/shared/definition-details-renderer.js` | Replaced static conflict table with dropdown selectors + Save Preferences button. Added `mountPortPreferenceHandlers()` export |
| `src/control-plane-api/ui/src/scripts/components/pages/LabletsPage.js` | Import and call `mountPortPreferenceHandlers` |
| `src/control-plane-api/ui/src/scripts/components/pages/SessionsPageV2.js` | Import and call `mountPortPreferenceHandlers` |
| `src/control-plane-api/ui/src/scripts/components/modals/SessionDetailsModal.js` | Import and call `mountPortPreferenceHandlers` |
| `src/lablet-controller/tests/test_lds_device_mapping.py` | Added `TestPortPreferencesOverride` class with 7 tests |

### Data Flow

```
UI: User selects preferred port from dropdown
    → Save Preferences button
    → PATCH /api/lablet-definitions/{id}/port-preferences
    → SetLdsPortPreferencesCommand (validates against port_conflicts)
    → LabletDefinition.update(changes={"lds_port_preferences": ...})
    → LabletDefinitionUpdatedDomainEvent
    → LabletDefinitionState.lds_port_preferences
    → LabletDefinitionDto.lds_port_preferences

Runtime: LabletReconciler builds PipelineContext
    → definition.lds_port_preferences → context.lds_port_preferences
    → binding_steps.step_lds_provision()
    → build_device_access_from_allocated_ports(port_preferences=...)
    → User preference checked BEFORE protocol priority
    → Graceful fallback to priority if preferred protocol not in candidates
```

### UI Behavior

Port conflicts warning now shows:

- Dropdown selector per device (pre-selected to current preference or auto-resolved default)
- Options labeled with `(auto)` suffix for the system default
- **Save Preferences** button to persist selections
- `override` badge for user-overridden devices, `auto` badge for auto-resolved

### Preference Resolution Logic

```
For each multi-port device:
  1. Check port_preferences for device_label → preferred_port_name
  2. If found: parse protocol from port_name, match against candidates
     - Match found → use preferred protocol
     - No match → fall back to protocol priority (log warning)
  3. If not found: apply protocol priority (existing Phase 1 behavior)
```
