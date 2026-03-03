# ADR-024: Content Package Storage in RustFS

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-02-25 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-023](./ADR-023-content-sync-trigger.md) (Content Sync Trigger), [ADR-025](./ADR-025-content-metadata-storage.md) (Content Metadata in MongoDB) |
| **Implementation** | [Content Synchronization Plan](../../implementation/content_synchronization.md) §2 (AD-CS-002) |

## Context

LabletDefinition content packages are downloaded from Mosaic as zip archives containing:

- `cml.yaml` — CML lab topology (used during lab import)
- `grade.xml` — Grading rules (used by Grading Engine)
- `devices.json` — Device/connection definitions (used during LDS session creation)
- `mosaic_meta.json` — Authoring metadata (version, publish date, form ID)

These packages must be stored in object storage for consumption by:

1. **LDS** (Lab Delivery System) — expects a specific zip archive at a predictable URL
2. **Grading Engine** — expects access to the same or a derived package
3. **lablet-controller** — needs metadata during LabletSession instantiation

Two storage strategies were considered:

1. **Archive-as-is**: Store the zip archive as a single object in a dedicated bucket
2. **Extracted contents**: Unzip and store individual files as separate S3 objects

### Naming Convention

Each LabletDefinition has a `form_qualified_name` (FQN) — a 6-component string like `"Exam Associate CCNA v1.1 LAB 1.3a"`. The FQN is slugified to produce a valid S3 bucket name:

```
"Exam Associate CCNA v1.1 LAB 1.3a" → "exam-associate-ccna-v1.1-lab-1.3a"
```

## Decision

### 1. Store Package Archive as Single Object

Upload the downloaded zip archive to the root of the slugified-FQN bucket with a configurable filename. Do NOT extract contents into the bucket.

### 2. Bucket Structure

```
<slugified-fqn>/                    # Bucket name (derived from FQN)
└── SVN.zip                         # Configurable filename (user_session_package_name)
```

Example:

```
exam-associate-ccna-v1.1-lab-1.3a/  # Bucket
└── SVN.zip                         # Default package name
```

### 3. Configurable Package Name

The filename within the bucket is controlled by `user_session_package_name` on the LabletDefinition (default: `"SVN.zip"`). This allows different definitions to use different naming conventions if needed by downstream consumers.

## Rationale

### Why archive-as-is (not extracted)?

- **LDS compatibility**: LDS expects `SVN.zip` at the bucket root — this matches exactly
- **Atomic**: A single PUT operation is simpler and more reliable than multiple uploads
- **Consistent hash**: SHA-256 of the entire zip is a single, verifiable content fingerprint
- **Reversible**: The original Mosaic package is preserved exactly as downloaded

### Why not extract contents?

- Would require multiple S3 PUT operations (complexity, partial failure risk)
- LDS does not consume individual files from S3 — it expects the zip
- Extracted metadata (cml.yaml, devices.json) is stored in MongoDB for internal use (see [ADR-025](./ADR-025-content-metadata-storage.md))
- No known consumer needs individual files from S3

### Why slugified-FQN as bucket name?

- Deterministic: same FQN always produces the same bucket name
- Human-readable: operators can identify the definition by bucket name
- S3-compliant: slugification produces valid bucket names (lowercase, hyphens, no spaces)
- Unique per definition: FQN uniqueness guarantees bucket uniqueness

## Consequences

### Positive

- Simple and reliable (single object upload per sync)
- LDS-compatible out of the box (expected `SVN.zip` at bucket root)
- Verifiable content integrity via SHA-256 hash of the archive
- No duplication — metadata in MongoDB, archive in RustFS

### Negative

- Cannot serve individual files (cml.yaml, grade.xml) directly from S3
- Re-download from S3 required if content needs re-extraction (unlikely)
- Bucket proliferation — one bucket per definition (acceptable for expected scale)

### Risks

- RustFS bucket creation rate limits (mitigated: `ensure_bucket_exists()` is idempotent)
- Package filename collision if multiple definitions share a bucket (prevented: one bucket per FQN)

## Related Documents

- [Content Synchronization Implementation Plan](../../implementation/content_synchronization.md)
- [ADR-025: Content Metadata in MongoDB](./ADR-025-content-metadata-storage.md)
