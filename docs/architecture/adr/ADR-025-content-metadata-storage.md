# ADR-025: Content Metadata Storage in MongoDB

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-02-25 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-024](./ADR-024-content-package-storage.md) (Package Storage in RustFS), [ADR-005](./ADR-005-state-store-architecture.md) (Dual State Store) |
| **Implementation** | [Content Synchronization Plan](../../implementation/content_synchronization.md) §2 (AD-CS-003), §3 (Phase 1), §4.3 |

## Context

When the lablet-controller's `ContentSyncService` downloads a content package from Mosaic, it extracts several metadata artifacts:

| Artifact | Source File | Used By | When |
|----------|------------|---------|------|
| CML YAML content | `cml.yaml` / `cml.yml` | lablet-controller | Lab import during LabletSession instantiation |
| CML YAML hash | SHA-256 of `cml.yaml` | CPA | Content change detection between syncs |
| Devices JSON | `devices.json` | lablet-controller | LDS session creation (device definitions) |
| Grade XML path | `grade.xml` (relative path) | Grading Engine | Grading ruleset location |
| Upstream version | `mosaic_meta.json` → `Version` | CPA/UI | Display to user, change tracking |
| Upstream publish date | `mosaic_meta.json` → `DatePublished` | CPA/UI | Freshness indicator |
| Upstream instance name | `mosaic_meta.json` → `InstanceName` | CPA | Mosaic instance identification |
| Upstream form ID | `mosaic_meta.json` → `FormId` | CPA | Cross-reference with Mosaic |
| Content package hash | SHA-256 of entire zip | CPA | Immutability check, version auto-increment |

Two storage strategies were considered:

1. **MongoDB fields**: Store extracted metadata as fields on `LabletDefinitionState` in MongoDB
2. **S3 sidecar files**: Extract files from zip and store alongside the archive in RustFS

## Decision

Extract metadata from the downloaded zip during sync, then store it as fields on the `LabletDefinitionState` aggregate in MongoDB. Do NOT store extracted files in S3.

### LabletDefinitionState Fields

```python
class LabletDefinitionState(AggregateState[str]):
    # ... existing fields ...

    # Content metadata (populated by content sync)
    content_package_hash: str | None = None       # SHA-256 of the entire zip archive
    upstream_version: str | None = None            # Mosaic Version
    upstream_date_published: str | None = None     # Mosaic DatePublished
    upstream_instance_name: str | None = None      # Mosaic InstanceName
    upstream_form_id: str | None = None            # Mosaic FormId
    grade_xml_path: str | None = None              # Relative path within zip
    cml_yaml_path: str | None = None               # Relative path within zip
    cml_yaml_content: str | None = None            # Full YAML content (for lab import)
    devices_json: str | None = None                # Full JSON content (for LDS)
```

### Sync Result Flow

```
ContentSyncService → extracts metadata from zip
  → POST /api/internal/lablet-definitions/{id}/content-synced
  → RecordContentSyncResultCommandHandler
  → definition.record_content_sync(hash, metadata...)
  → MongoDB (LabletDefinitionState updated)
```

## Rationale

### Why MongoDB (not S3)?

- **Simpler access pattern**: lablet-controller already fetches the full LabletDefinition from CPA API during LabletSession instantiation. Metadata is included in the response — no additional S3 read needed.
- **Atomic update**: All metadata fields are updated in a single MongoDB write operation via the aggregate's `record_content_sync()` method.
- **Query support**: MongoDB supports filtering by metadata fields (e.g., "find all definitions from Mosaic instance X" or "find definitions with outdated upstream_version").
- **No S3 dependency for reads**: LabletSession instantiation only needs metadata, not the full package. Decoupling from S3 for reads reduces failure modes.

### Why not S3 sidecar files?

- Would require additional S3 GET operations during session instantiation
- Adds an S3 dependency for metadata reads (currently only needed for package delivery to LDS)
- Multiple S3 objects increase sync complexity (partial failure, consistency)
- No consumer needs individual extracted files from S3 (LDS uses the zip, lablet-controller uses metadata from MongoDB)

### Content size considerations

- `cml_yaml_content`: Typically 5-50 KB (lab topology YAML) — well within MongoDB document limits
- `devices_json`: Typically 1-10 KB (device definitions) — negligible
- Total metadata footprint per definition: < 100 KB in the worst case

## Consequences

### Positive

- Single source of truth for definition + metadata (MongoDB document)
- No additional S3 reads during session instantiation
- Rich query capabilities on metadata fields
- Consistent with existing aggregate state pattern (Neuroglia AggregateState)

### Negative

- MongoDB document size increases per definition (< 100 KB overhead — negligible)
- Full CML YAML stored in MongoDB (could be large for complex topologies, but still within limits)
- Metadata is a copy of what's in the zip — potential staleness if zip is modified outside the system (not a realistic scenario)

### Risks

- Very large CML YAML files (> 1 MB) could affect MongoDB performance (mitigated: 16 MB document limit, typical files are < 50 KB)

## Related Documents

- [Content Synchronization Implementation Plan](../../implementation/content_synchronization.md)
- [ADR-024: Content Package Storage in RustFS](./ADR-024-content-package-storage.md)
- [ADR-005: Dual State Store Architecture](./ADR-005-state-store-architecture.md)
- [ADR-029: Port Template Extraction from CML YAML](./ADR-029-port-template-extraction-from-cml-yaml.md) — extends the metadata extracted during content sync to include `port_template` (auto-derived from CML YAML `nodes[].tags`)
