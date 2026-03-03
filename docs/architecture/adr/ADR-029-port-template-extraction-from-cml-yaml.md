# ADR-029: Port Template Extraction from CML YAML

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-02-25 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-025](./ADR-025-content-metadata-storage.md) (Content Metadata Storage), [ADR-028](./ADR-028-definition-initial-status.md) (Definition Initial Status) |
| **Implementation** | [Content Synchronization Plan](../../implementation/content_synchronization.md), `domain/value_objects/port_template.py` |

## Context

A `LabletDefinition` declares a `port_template` — a list of named port placeholders that the `PortAllocationService` allocates when a `LabletSession` is scheduled on a worker.  Until now, port templates were **manually authored** in seed files or via the Create command.

CML topology files (`cml.yaml` / `cml.yml`) already encode per-node port requirements in the `tags` field using CML's colon-separated protocol serialization:

```yaml
nodes:
  - label: PC
    node_definition: ubuntu-desktop-24-04-v2
    tags:
      - serial:4567
      - vnc:4568
  - label: iosv-0
    node_definition: iosv
    tags:
      - serial:4566
```

The tag format is `protocol:port_number`, where:

- **protocol** identifies the access type (`serial`, `vnc`, `ssh`, `telnet`, etc.)
- **port_number** is a CML-internal placeholder (ignored for our purposes — actual ports are allocated dynamically)

Since the content sync pipeline already downloads and caches the CML YAML content, the port template can be **automatically derived** from the topology, eliminating manual authoring and ensuring consistency.

## Decision

### 1. Add `PortTemplate.from_cml_nodes()` Factory Method

A static factory on `PortTemplate` that accepts the parsed `nodes` list from a CML YAML file and produces a `PortTemplate`:

```python
@staticmethod
def from_cml_nodes(nodes: list[dict]) -> PortTemplate:
    """Extract port definitions from CML topology nodes[].tags."""
```

**Naming convention**: `{node_label}_{protocol}` (e.g., `PC_serial`, `PC_vnc`, `iosv-0_serial`).

**Protocol mapping**: All recognised CML protocols (`serial`, `vnc`, `ssh`, `telnet`, `tcp`, `http`, `https`) map to `protocol="tcp"` in the `PortDefinition`, since CML console access runs over TCP.

**Behaviour**:

- Tags that don't match `protocol:port` format are silently skipped (logged at DEBUG)
- Duplicate `(label, protocol)` pairs are de-duplicated
- Nodes without `tags` or without a `label` are skipped
- Node labels are sanitised for port names (spaces → underscores, special chars removed)

### 2. Carry `port_template` in Content Sync Events

`LabletDefinitionContentSyncedDomainEvent` gains an optional `port_template: dict | None` field.

`record_content_sync()` on the aggregate gains a `port_template: PortTemplate | None` parameter.

The `@dispatch(ContentSyncedDomainEvent)` handler applies the extracted template if provided, preserving the existing template when `None`.

### 3. Content Sync Job Populates Port Template

During Phase 4 (Content Sync Job implementation), the `_extract_metadata()` step will:

1. Parse the cached `cml_yaml_content` as YAML
2. Call `PortTemplate.from_cml_nodes(parsed["nodes"])`
3. Pass the result into `record_content_sync(port_template=extracted_template)`

This closes the loop: **definition creation** → **content sync** → **port template populated** → **ready for session scheduling**.

### 4. Port Allocation Flow (Downstream)

When a `LabletSession` is instantiated on a selected worker:

1. The `port_template` from the `LabletDefinition` is read
2. `PortAllocationService.allocate(template, worker)` assigns real port numbers from the worker's available pool
3. The allocated ports (e.g., `{"PC_serial": 5041, "PC_vnc": 5042, ...}`) are used to set device access info in the LDS session

This downstream flow is **not implemented in this ADR** — it is documented here for context only. The current scope is extraction and storage.

## Rationale

### Why auto-extract (not manual-only)?

- **Consistency**: The CML YAML is the single source of truth for lab topology. Deriving port templates from it eliminates drift between topology and port allocation expectations.
- **Reduced operator burden**: Content authors don't need to manually compute port templates — they define tags in CML (which they already do) and the system derives the rest.
- **Version safety**: When content is re-synced (new upstream version), the port template automatically adjusts to match the updated topology.

### Why ignore the port number in tags?

- CML port numbers in tags (`serial:4567`) are CML-internal defaults that may not match the actual allocated ports on our workers.
- Our `PortAllocationService` dynamically assigns ports from the worker's available range.
- We only need the _protocol type_ and _node association_ — not the specific port number.

### Why `{label}_{protocol}` naming?

- Uniquely identifies each port across all nodes in the topology
- Human-readable and matches the existing manual convention in seed files
- Compatible with the downstream LDS device access info mapping

## Consequences

### Positive

- Port templates are always in sync with CML topology content
- No manual port template authoring required for new definitions
- Existing manually-authored templates are overwritten on first successful content sync (intentional: topology is the source of truth)
- Factory method is pure (no I/O), easily testable

### Negative

- If a node has no tags, it won't appear in the port template (expected: not all nodes need external access)
- Port template changes on re-sync could affect warm pool pre-allocated ports (mitigated: warm pool re-allocation happens on definition update events)

### Risks

- CML YAML format changes in future CML versions could break tag parsing (mitigated: regex is flexible, unrecognised tags are skipped gracefully)

## Related Documents

- [Content Synchronization Implementation Plan](../../implementation/content_synchronization.md)
- [ADR-025: Content Metadata Storage](./ADR-025-content-metadata-storage.md)
- `domain/value_objects/port_template.py` — `PortTemplate.from_cml_nodes()` implementation
- `data/cml_labs/TEST-LAB-1.1.yaml` — Reference CML topology with node tags
