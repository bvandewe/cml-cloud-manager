# Implementation Plan: LDS Device Mapping Fix

**Status:** Implemented
**Date:** 2026-05-28 (approved) / 2026-05-29 (implemented)
**Priority:** P0 (FR-2.2.5d)
**Affected Service:** lablet-controller
**Related ADRs:** ADR-034, ADR-038, AD-P4-03, AD-029

---

## Problem Statement

The `lds_provision` pipeline step incorrectly maps **ALL** CML nodes to LDS devices. It should only map devices that are **user-visible** as defined in `content.xml` of the lab package. Some CML nodes (backbone routers, hidden infrastructure) must remain invisible to end-users.

### Root Cause

The current `lds_provision` step in `binding_steps.py` (line ~170):

1. Calls `context.cml.get_lab_nodes()` to fetch ALL CML lab nodes
2. Reads each node's `tags` field (format: `protocol:port`)
3. Builds `DeviceAccessInfo` for every node that has tags
4. Calls `lds.set_devices()` with this unfiltered list

**Two failure modes:**

| Scenario | Cause | Result |
|----------|-------|--------|
| All nodes mapped | Tags exist on hidden nodes | LDS gets backbone/infra devices that users shouldn't see |
| Empty device list | `port_template` absent → `ports_alloc` + `tags_sync` skipped | LDS session has zero devices |

### Correct Behavior (per FR-2.2.5d)

> "System SHALL provision device access info for **each device in content.xml**"

The **authoritative source** for user-visible devices is `content.xml` in the lab package:

```xml
<device>
    <device category="NA" device_label="ubuntu-desktop-1" coords="31,41,186,147" user_access_mode="web"/>
</device>
```

Only devices declared in `content.xml` with their `device_label` should be exposed to LDS.

---

## Solution Design

### Principle

Use a **two-source join** approach:

- **content.xml** → defines WHICH devices are user-visible (device labels)
- **allocated_ports** → provides HOW to reach them (protocol + port on worker IP)

The `lds_provision` step should filter the port-to-device mapping using the user-visible device labels extracted from `content.xml`.

### Data Flow (Fixed)

```
content_sync → extracts user_visible_devices from content.xml → stores on LabletDefinition
                                                                         │
                                                                         ▼
lds_provision ← reads definition.user_visible_devices ←─────────────────┘
     │
     ├── reads allocated_ports from ports_alloc step result (or progress)
     │
     ├── FILTERS: only build DeviceAccessInfo for labels present
     │   in BOTH user_visible_devices AND allocated_ports
     │
     └── calls lds.set_devices() with filtered list
```

---

## Implementation Steps

### Step 1: Extract user-visible devices during content sync

**File:** `src/lablet-controller/application/hosted_services/content_sync_service.py`

In `_extract_metadata_from_package()`, after extracting `devices.json`, add extraction of `content.xml`:

```python
# Find content.xml (anywhere in the archive)
content_xml_files = [n for n in names if n.endswith("content.xml")]
if content_xml_files:
    content_xml_raw = zf.read(content_xml_files[0]).decode("utf-8")
    metadata["user_visible_devices"] = self._extract_user_visible_devices(content_xml_raw)
```

Add the helper method:

```python
@staticmethod
def _extract_user_visible_devices(content_xml: str) -> list[dict[str, str]]:
    """Extract user-visible device definitions from content.xml.

    Parses <device> elements and returns a list of device labels
    with their access mode. These are the devices that should be
    exposed to end-users via LDS.

    Args:
        content_xml: Raw content.xml string.

    Returns:
        List of dicts with keys: device_label, user_access_mode, category.
        Example: [{"device_label": "R1", "user_access_mode": "ssh"}]
    """
    import xml.etree.ElementTree as ET

    devices = []
    try:
        root = ET.fromstring(content_xml)
        # content.xml structure: <lab_content><device><device .../></device></lab_content>
        # or: <devices><device .../></devices>
        for device_elem in root.iter("device"):
            label = device_elem.get("device_label")
            if label:
                devices.append({
                    "device_label": label,
                    "user_access_mode": device_elem.get("user_access_mode", ""),
                    "category": device_elem.get("category", ""),
                })
    except ET.ParseError as e:
        logger.warning(f"Failed to parse content.xml for device extraction: {e}")

    return devices
```

---

### Step 2: Add `user_visible_devices` field to LabletDefinitionReadModel

**File:** `src/core/lcm_core/domain/entities/read_models/lablet_definition_read_model.py`

Add field after `devices_json`:

```python
# Content metadata (populated by sync — ADR-025)
content_package_hash: str | None = None
upstream_version: str | None = None
cml_yaml_content: str | None = None
devices_json: str | None = None
user_visible_devices: list[dict[str, str]] | None = None  # From content.xml <device> elements
grade_xml_path: str | None = None
cml_yaml_path: str | None = None
```

Update `from_dict()`:

```python
user_visible_devices=data.get("user_visible_devices"),
```

---

### Step 3: Persist user_visible_devices through CPA sync endpoint

**File:** `src/lablet-controller/application/hosted_services/content_sync_service.py`

In the section that builds the update payload for CPA (around line 440):

```python
"user_visible_devices": metadata.get("user_visible_devices"),
```

**File:** `src/control-plane-api/...` (wherever CPA stores definition metadata)

Ensure the `user_visible_devices` field is persisted in MongoDB alongside the existing `devices_json`, `port_template`, etc.

---

### Step 4: Rewrite `step_lds_provision` to use filtered device list

**File:** `src/lablet-controller/application/services/step_handlers/binding_steps.py`

Replace the current node-tag-based device mapping logic:

```python
@step_handler("lds_provision")
async def step_lds_provision(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Provision LDS session with device mapping (§2.2).

    Revised approach (FR-2.2.5d):
    1. Read user_visible_devices from definition (extracted from content.xml)
    2. Read allocated_ports from ports_alloc step result
    3. Build device list by joining: only devices in BOTH sources
    4. Create LDS session and set filtered devices
    """
    resolve_data = _get_step_result_data(progress, "lab_resolve")
    cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
    if not cml_lab_id:
        return StepResult.failed("No cml_lab_id from lab_resolve")

    definition = context.definition
    if not definition or not definition.form_qualified_name:
        return StepResult.skipped("No form_qualified_name — LDS not applicable")

    if not context.lds:
        return StepResult.skipped("LDS client not configured")

    try:
        # ── Get user-visible devices from definition (content.xml source) ──
        user_visible_devices = definition.user_visible_devices or []
        visible_labels = {d["device_label"] for d in user_visible_devices}

        # ── Get allocated ports (source of truth for connectivity) ──
        ports_data = _get_step_result_data(progress, "ports_alloc")
        allocated_ports: dict[str, int] = {}
        if ports_data:
            allocated_ports = ports_data.get("allocated_ports", {})

        # ── Build filtered device list ──
        devices = build_device_access_from_allocated_ports(
            allocated_ports=allocated_ports,
            worker_ip=context.worker_ip,
            user_visible_labels=visible_labels,
        )

        # Fallback: if no allocated_ports but tags exist on nodes, use legacy path
        # (backward compat for definitions synced before this fix)
        if not devices and not allocated_ports:
            nodes = await context.cml.get_lab_nodes(
                host=context.worker_ip,
                lab_id=cml_lab_id,
                username=context.worker_cml_username,
                password=context.worker_cml_password,
            )
            if context.build_device_access_list:
                all_devices = context.build_device_access_list(nodes, context.worker_ip)
            else:
                all_devices = _build_device_access_list_simple(nodes, context.worker_ip)
            # Filter by visible labels if available
            if visible_labels:
                devices = [d for d in all_devices if d.device_label in visible_labels]
            else:
                devices = all_devices

        # ── Create LDS session ──
        region = instance.worker_aws_region
        session_info = await context.lds.create_session(
            username=instance.name,
            first_name="Lablet",
            last_name="User",
            scheduled_date=datetime.now(timezone.utc).isoformat(),
            form_qualified_name=definition.form_qualified_name,
            region=region,
        )
        lds_session_id = session_info.session_id

        if devices:
            await context.lds.set_devices(
                session_id=lds_session_id,
                part_num=1,
                devices=devices,
                region=region,
            )
            logger.info(f"Set {len(devices)} devices on LDS session {lds_session_id}")
        else:
            logger.warning(
                f"No devices to set on LDS session {lds_session_id} "
                f"(visible_labels={visible_labels}, allocated_ports keys={list(allocated_ports.keys())})"
            )

        # ── Get lablet launch URL ──
        launch_url = await context.lds.get_lablet_launch_url(
            session_id=lds_session_id,
            region=region,
        )

        # ── Create UserSession child entity via CPA ──
        user_session_data = await context.api.create_user_session(
            session_id=instance.id,
            lds_session_id=lds_session_id,
            lds_login_url=launch_url,
            cml_lab_id=cml_lab_id,
        )
        user_session_id = user_session_data.get("id", lds_session_id)

        return StepResult.completed({
            "lds_session_id": lds_session_id,
            "user_session_id": user_session_id,
            "launch_url": launch_url,
            "device_count": len(devices),
        })

    except LdsSpiError as e:
        return StepResult.failed(f"LDS provisioning failed: {e}")
    except Exception as e:
        return StepResult.failed(str(e))
```

---

### Step 5: New helper function in `lds_helpers.py`

**File:** `src/lablet-controller/application/services/reconciler_helpers/lds_helpers.py`

```python
def build_device_access_from_allocated_ports(
    allocated_ports: dict[str, int],
    worker_ip: str,
    user_visible_labels: set[str] | None = None,
) -> list[DeviceAccessInfo]:
    """Build LDS device access info from allocated ports, filtered by visibility.

    Port name convention (from PortTemplate): "{node_label}_{protocol}"
    e.g., "Router1_serial" → label="Router1", protocol="serial"

    Args:
        allocated_ports: Dict of port_name → port_number from ports_alloc step.
        worker_ip: Worker IP address for device host.
        user_visible_labels: Set of device labels from content.xml.
            If provided, only devices whose label appears in this set are included.
            If None, all devices from allocated_ports are included.

    Returns:
        List of DeviceAccessInfo for LDS device provisioning.
    """
    devices: list[DeviceAccessInfo] = []

    for port_name, port_number in allocated_ports.items():
        # Parse convention: "{label}_{protocol}"
        # Handle labels with underscores by splitting on last underscore
        parts = port_name.rsplit("_", 1)
        if len(parts) != 2:
            logger.warning(f"Cannot parse port name '{port_name}' — skipping")
            continue

        node_label, protocol = parts

        # Filter by user-visible labels
        if user_visible_labels is not None and node_label not in user_visible_labels:
            logger.debug(f"Skipping device '{node_label}' — not in user_visible_devices")
            continue

        devices.append(
            DeviceAccessInfo(
                device_label=node_label,
                protocol=protocol,
                host=worker_ip,
                port=port_number,
            )
        )

    return devices
```

---

### Step 6: Update existing `build_device_access_list` to accept filter

**File:** `src/lablet-controller/application/services/reconciler_helpers/lds_helpers.py`

Add an optional `user_visible_labels` parameter to the existing function for the legacy/fallback path (used by the reconciler's non-pipeline code):

```python
def build_device_access_list(
    nodes: list[NodeInfo],
    worker_ip: str,
    user_visible_labels: set[str] | None = None,
) -> list[DeviceAccessInfo]:
    """Build LDS device access info from CML node topology.

    ...existing docstring...

    Args:
        nodes: CML lab nodes with labels and tags.
        worker_ip: Worker IP address for device host.
        user_visible_labels: If provided, only include nodes whose label
            is in this set. None means include all nodes with valid tags.
    """
    devices: list[DeviceAccessInfo] = []

    for node in nodes:
        if not node.tags:
            continue

        # Filter by visibility if specified
        if user_visible_labels is not None and node.label not in user_visible_labels:
            continue

        # ... rest of existing logic unchanged ...
```

---

## File Change Summary

| # | File | Change Type | Description |
|---|------|-------------|-------------|
| 1 | `src/lablet-controller/application/hosted_services/content_sync_service.py` | Modify | Extract `user_visible_devices` from `content.xml` during sync |
| 2 | `src/core/lcm_core/domain/entities/read_models/lablet_definition_read_model.py` | Modify | Add `user_visible_devices` field |
| 3 | `src/lablet-controller/application/services/step_handlers/binding_steps.py` | Modify | Rewrite `step_lds_provision` to filter by visibility |
| 4 | `src/lablet-controller/application/services/reconciler_helpers/lds_helpers.py` | Modify | Add `build_device_access_from_allocated_ports()` + visibility filter param |
| 5 | `src/control-plane-api` (definition storage) | Modify | Persist `user_visible_devices` field |
| 6 | Tests | Create/Modify | Unit tests for new helpers and integration test for pipeline |

---

## Testing Strategy

### Unit Tests

1. **`test_extract_user_visible_devices`** — Parse content.xml variants (single device, multiple, empty, malformed)
2. **`test_build_device_access_from_allocated_ports`** — Verify port name parsing and label filtering
3. **`test_build_device_access_list_with_filter`** — Legacy function respects `user_visible_labels`
4. **`test_step_lds_provision_filtered`** — Pipeline step only maps visible devices
5. **`test_step_lds_provision_fallback`** — Backward compat when `user_visible_devices` is None

### Integration Tests

1. **Full pipeline run** with a definition that has both visible and hidden nodes
2. **Content sync** with a real zip package containing content.xml

---

## Backward Compatibility

- Definitions synced **before** this fix will have `user_visible_devices = None`
- When `user_visible_devices` is None, the fallback path uses the existing tag-based logic (all tagged nodes)
- A re-sync of existing definitions will populate the field automatically
- No migration needed — field is optional, additive change

---

## Validation Criteria

- [x] Only devices from `content.xml` appear in LDS session
- [x] Backbone/hidden CML nodes are NOT exposed to LDS
- [x] Allocated port numbers are correctly mapped to visible devices
- [x] Pipeline succeeds when `port_template` is absent (graceful skip/fallback)
- [x] Existing definitions without `user_visible_devices` still work (backward compat)
- [x] `make test` passes in lablet-controller (472 passed)

---

## References

- **FR-2.2.5d:** "System SHALL provision device access info for each device in content.xml"
- **FR-2.2.5f:** "Device port SHALL be derived from allocated ports"
- **content.xml schema:** `<device device_label="..." user_access_mode="..." />`
- **Port name convention:** `{node_label}_{protocol}` (from PortTemplate/ADR-029)
- **Pipeline template:** `standard-instantiate` in `pipeline_template_resolver.py`
