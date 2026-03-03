# ADR-019: LabRecord as Independent AggregateRoot

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted (Partially Superseded) |
| **Date** | 2026-02-10 (Amended 2026-02-18) |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-017](./ADR-017-lab-operations-via-lablet-controller.md), [ADR-018](./ADR-018-lds-integration.md), [ADR-020](./ADR-020-session-entity-model.md) |
| **Partially Superseded by** | [ADR-020](./ADR-020-session-entity-model.md) (binding model) |
| **Reference** | [LabRecord Architecture](../lab-record-architecture.md) |

## Context

LabRecord currently exists as a passive snapshot synced from CML labs every 30 minutes. This limits reuse, blocks multi-lab topologies, and conflates lab lifecycle with LabletInstance scheduling and grading.

## Decision

LabRecord SHALL be promoted to an **independent AggregateRoot** with its own lifecycle state machine, runtime abstraction, and repository.

!!! warning "Binding Model Superseded by ADR-020"
    The original design proposed a `LabletLabBinding` join entity for many-to-many associations.
    Per ADR-020, the binding model is simplified to a **direct 1:1 field** (`lab_record_id`) on
    `LabletSession`. The `LabletLabBinding` entity and `lablet_lab_bindings` collection are eliminated.
    Multiple LabletSessions may reference the same LabRecord over time (reuse via wipe-for-reuse),
    but the relationship at any point in time is 1:1.

The relationship between LabRecord and LabletSession (formerly LabletInstance) is a direct `lab_record_id` field on LabletSession, enabling lab reuse across time and multi-lab sessions.

## Rationale

- **Reuse & performance**: Wipe+restart is significantly faster than cold import for repeated labs.
- **Multi-lab topologies**: A single session may require multiple interconnected labs.
- **Runtime abstraction**: Enables CML today and K8s/Pod runtimes later.
- **DDD boundary clarity**: Prevents foreign key coupling between aggregates.

## Consequences

### Positive

- Lab lifecycle decoupled from timeslot lifecycle
- Enables lab reuse, versioning, and discovery
- Supports multi-lab sessions and cross-runtime scaling

### Negative

- Additional aggregate and repository complexity
- ~~Requires migration from `cml_lab_id` to binding entity~~ (Superseded: direct `lab_record_id` field on LabletSession per ADR-020)

### Risks

- Inconsistent state if discovery and reconciliation are not coordinated
- Requires careful SSE/event semantics to avoid UI confusion

## Implementation Notes

See [LabRecord Architecture](../lab-record-architecture.md) for the full design, including:

- `LabRecordStatus` lifecycle
- RuntimeBinding value object
- ~~LabletLabBinding join entity~~ (Eliminated per ADR-020 — replaced by direct `lab_record_id` on LabletSession)
- Discovery + reuse flow
- API surface and UI updates
