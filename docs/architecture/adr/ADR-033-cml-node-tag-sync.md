# ADR-033: CML Node Tag Sync with Allocated Ports

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-02 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-004](./ADR-004-port-allocation-per-worker.md) (Port Allocation), [ADR-017](./ADR-017-lab-operations-via-lablet-controller.md) (Lab Operations via Lablet-Controller), [ADR-029](./ADR-029-port-template-extraction-from-cml-yaml.md) (Port Template Extraction), [ADR-031](./ADR-031-checkpoint-instantiation-pipeline.md) (Checkpoint Pipeline), [ADR-032](./ADR-032-port-allocation-labrecord-topology.md) (Port Allocation on LabRecord) |
| **Implementation** | [Instantiation Pipeline Plan §3](../../implementation/instantiation-pipeline.md) |

## Context

CML node tags serve a dual purpose in the LCM system:

1. **Input**: `PortTemplate.from_cml_nodes()` (ADR-029) reads tags from the CML YAML topology to derive port requirements. Tags in format `protocol:port_number` (e.g., `serial:4567`) declare which protocols each node needs.
2. **Output**: After `PortAllocationService` allocates real host ports (e.g., port 3001 from the worker's 2000-9999 range), the allocated port number should be written back to the CML node's tags so the topology reflects the actual port mapping.

Currently, only the **input** direction exists. The system reads tags to build port templates but never writes allocated ports back to CML. This creates several problems:

- **Tag drift**: CML node tags still show the original placeholder port numbers from the YAML (e.g., `serial:4567`) while the actual allocated port is different (e.g., `serial:3001`). Any external tool reading CML node tags gets incorrect port information.
- **Lab discovery inconsistency**: When `LabDiscoveryService` discovers an already-running lab and reads its node tags to reconstruct port mappings, the tags contain stale placeholder values — not the actual allocated ports.
- **Observation inaccuracy**: Resource observation (ADR-030) reads runtime port data. If tags haven't been updated, observed ports won't match allocated ports, triggering false drift detection.

## Decision

### 1. New Pipeline Step: `tags_sync`

Add a `tags_sync` step to the instantiation pipeline DAG, positioned between `ports_alloc` and `lab_binding`:

```
... → ports_alloc → tags_sync → lab_binding → ...
```

The `tags_sync` step writes allocated port numbers back to CML node tags using the CML REST API.

### 2. Tag Format

Tags use the same `protocol:port_number` format established in ADR-029:

```
serial:3001
vnc:3002
ssh:3003
```

- **protocol**: From `CML_TCP_PROTOCOLS` (`serial`, `vnc`, `ssh`, `telnet`, `tcp`, `http`, `https`)
- **port_number**: The actual allocated host port from `PortAllocationService`
- **Max length**: 64 characters per tag (CML specification limit)

### 3. CML SPI Extension: `patch_node_tags()`

Add a new method to the CML SPI client:

```python
async def patch_node_tags(
    self,
    worker_id: str,
    lab_id: str,
    node_id: str,
    tags: list[str],
) -> bool:
    """
    Update tags on a CML node via PATCH /api/v0/labs/{lab_id}/nodes/{node_id}.

    Args:
        worker_id: Worker hosting the CML instance
        lab_id: CML lab identifier
        node_id: CML node identifier within the lab
        tags: Complete tag list to set on the node (replaces existing tags)

    Returns:
        True if tags were successfully updated, False otherwise
    """
```

This calls `PATCH /api/v0/labs/{lab_id}/nodes/{node_id}` with body `{"tags": tags}`.

**Important**: The PATCH replaces the entire tag list on the node. The `tags_sync` step must preserve any non-port tags that already exist on the node and only update/add port-related tags.

### 4. Step Implementation

```python
async def _step_tags_sync(self, instance, progress) -> StepResult:
    """Write allocated ports as CML node tags."""
    lab_record = await self._get_lab_record(instance)
    if not lab_record or not lab_record.allocated_ports:
        return StepResult(step="tags_sync", status="skipped")

    # Build tag updates per node from allocated_ports
    # port_name format: "{node_label}_{protocol}" → tag: "{protocol}:{port}"
    node_tags: dict[str, list[str]] = {}
    for port_name, port_number in lab_record.allocated_ports.items():
        # Parse "PC_serial" → node_label="PC", protocol="serial"
        parts = port_name.rsplit("_", 1)
        if len(parts) == 2:
            node_label, protocol = parts
            node_tags.setdefault(node_label, []).append(f"{protocol}:{port_number}")

    # Resolve node labels to CML node IDs
    nodes = await self._cml_spi.get_lab_nodes(worker_id, lab_id)
    label_to_id = {n["label"]: n["id"] for n in nodes}

    # PATCH each node's tags
    for label, tags in node_tags.items():
        node_id = label_to_id.get(label)
        if not node_id:
            logger.warning(f"Node '{label}' not found in lab — skipping tag sync")
            continue

        # Preserve existing non-port tags
        existing = next((n.get("tags", []) for n in nodes if n["id"] == node_id), [])
        non_port_tags = [t for t in existing if not self._is_port_tag(t)]
        merged_tags = non_port_tags + tags

        success = await self._cml_spi.patch_node_tags(worker_id, lab_id, node_id, merged_tags)
        if not success:
            logger.warning(f"Failed to sync tags for node '{label}' — continuing")

    return StepResult(step="tags_sync", status="completed")
```

### 5. Non-Fatal Step

The `tags_sync` step treats failures as **non-fatal warnings**:

- If the CML instance doesn't support `PATCH` on nodes (older CML versions), the step logs a warning and marks itself as `completed` (not `failed`).
- If individual node tag updates fail, the step continues with remaining nodes and still marks as `completed`.
- The lab can function without updated tags — tags are primarily for port documentation and external-interface resolution.

**Rationale**: Tag sync is a "nice to have" for correctness, not a hard requirement for lab functionality. Blocking the entire instantiation pipeline on a tag write failure would be disproportionate.

### 6. Tag Lifecycle

Tags follow the same lifecycle as ports (ADR-032):

| Event | Tags Action | Rationale |
|-------|-------------|-----------|
| `ports_alloc` step | — | Ports allocated, tags not yet written |
| `tags_sync` step | **WRITE** | Tags set to `protocol:allocated_port` |
| Session expires | **UNCHANGED** | Tags are topology-level |
| Lab stopped | **UNCHANGED** | Stop preserves topology (nodes, edges, tags) |
| Lab wiped | **UNCHANGED** | Wipe resets state, not topology |
| New session on same lab | **SKIP** | Tags already correct from LabRecord ports |
| Lab deleted from CML | **REMOVED** | Topology destroyed by CML |

### 7. Idempotency

When a LabRecord already has `allocated_ports` and is bound to a new session, the `tags_sync` step checks whether CML node tags already match the allocated ports. If they do, the step completes immediately without issuing PATCH calls.

When re-executing after a failure (retry), the step is safe to re-run — PATCH is idempotent (setting the same tags twice has no effect).

## Rationale

### Why sync tags (not just read them)?

- ADR-029 established that tags are the canonical source for port-to-protocol mapping. Without syncing allocated ports back to tags, the canonical source contains stale placeholder values.
- Lab discovery (`LabDiscoveryService`) reads tags to reconstruct port mappings for already-running labs. If tags aren't updated, discovery produces incorrect port data.
- The `PortTemplate.from_cml_nodes()` factory is bidirectional: it reads tags to build templates AND (now) the system writes templates back as tags.

### Why a separate step (not part of `ports_alloc`)?

- **Single Responsibility**: Port allocation (etcd) and tag writing (CML API) are different concerns with different failure modes. Separating them allows independent retry.
- **Non-fatal semantics**: Tag sync can be non-fatal without affecting port allocation's correctness. If combined, a tag write failure would block port allocation completion.
- **Network isolation**: Port allocation talks to etcd (internal); tag sync talks to CML API on a remote worker (external). Different timeout and retry characteristics.

### Why PATCH (not PUT)?

CML's `PATCH /api/v0/labs/{lab_id}/nodes/{node_id}` allows partial updates — only the `tags` field is modified. A `PUT` would require sending the entire node object, risking unintended changes to other node properties.

### Why replace existing port tags (not append)?

Port tags may have stale values from previous allocations or from the original CML YAML. Replacing all port-pattern tags (while preserving non-port tags) ensures the tag list always reflects the current allocation. This is safe because port allocation is authoritative.

## Consequences

### Positive

- **Tag accuracy**: CML node tags always reflect actual allocated ports, not YAML placeholder values
- **Lab discovery consistency**: Discovered labs have accurate port mappings in their tags
- **Observation accuracy**: Port drift detection (ADR-030) compares against correct baseline tags
- **External tool compatibility**: Any tool reading CML node tags (CML web UI, external scripts) sees correct port mappings
- **Bidirectional tag flow**: Tags are both read (ADR-029) and written (this ADR), creating a complete round-trip

### Negative

- **Additional CML API calls**: One `GET` (list nodes) + N `PATCH` calls per lab (one per node with ports). For a 5-node lab, this is ~6 API calls. Mitigated: happens once per LabRecord lifetime, not per session.
- **CML API dependency**: Tag sync requires CML API availability during instantiation. Mitigated: non-fatal step — failure doesn't block pipeline.
- **Tag ownership ambiguity**: LCM now writes tags to CML nodes. If an operator also edits tags manually via CML web UI, the next tag sync could overwrite manual changes. Mitigated: non-port tags are preserved; only port-pattern tags are managed by LCM.

### Risks

- **CML version compatibility**: Older CML versions may not support `PATCH` on the nodes endpoint. Mitigated: non-fatal step with graceful fallback.
- **Tag format collision**: If a non-port tag happens to match the `protocol:port` regex pattern, it could be incorrectly classified as a port tag and overwritten. Mitigated: the regex is specific (`^[a-zA-Z][a-zA-Z0-9_-]*:\d+$`) and only matches known protocols from `CML_TCP_PROTOCOLS`.

## Implementation Notes

### CML SPI Client Extension

```python
# New method on CmlLabsApiClient (or equivalent SPI class):
async def patch_node_tags(
    self, worker_id: str, lab_id: str, node_id: str, tags: list[str]
) -> bool:
    """Update tags on a CML node."""
    url = f"{base_url}/api/v0/labs/{lab_id}/nodes/{node_id}"
    response = await self._session.patch(url, json={"tags": tags}, headers=auth_headers)
    return response.status_code == 200
```

### Port Tag Detection Helper

```python
import re

_PORT_TAG_PATTERN = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*):(\d+)$")

CML_TCP_PROTOCOLS = frozenset({"serial", "vnc", "ssh", "telnet", "tcp", "http", "https"})

def _is_port_tag(tag: str) -> bool:
    """Check if a tag matches the protocol:port pattern."""
    match = _PORT_TAG_PATTERN.match(tag)
    return bool(match and match.group(1).lower() in CML_TCP_PROTOCOLS)
```

### Cross-Service Changes

| Service | Changes |
|---------|---------|
| **lcm-core** or **lablet-controller integration** | `patch_node_tags()` method on CML SPI client |
| **lablet-controller** | `_step_tags_sync()` method on reconciler, `_is_port_tag()` helper |
| **control-plane-api** | No changes (tag sync is a lablet-controller → CML interaction) |

## Related Documents

- [Instantiation Pipeline Plan §3](../../implementation/instantiation-pipeline.md)
- [ADR-029: Port Template Extraction from CML YAML](./ADR-029-port-template-extraction-from-cml-yaml.md)
- [ADR-030: Resource & Port Observation](./ADR-030-resource-observation-learn-from-live.md)
- [ADR-031: Checkpoint-Based Instantiation Pipeline](./ADR-031-checkpoint-instantiation-pipeline.md)
- [ADR-032: Port Allocation as LabRecord Topology Concern](./ADR-032-port-allocation-labrecord-topology.md)
- `domain/value_objects/port_template.py` — PortTemplate, `from_cml_nodes()`, `CML_TCP_PROTOCOLS`
