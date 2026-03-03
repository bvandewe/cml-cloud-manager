# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records (ADRs) for the Lablet Cloud Manager's Lablet Resource Manager expansion.

## ADR Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [ADR-001](./ADR-001-api-centric-state-management.md) | API-Centric State Management | Accepted | 2026-01-15 |
| [ADR-002](./ADR-002-separate-resource-scheduler-service.md) | Separate Resource Scheduler Service | Accepted | 2026-01-15 |
| [ADR-003](./ADR-003-cloudevents-for-integration.md) | CloudEvents for External Integration | Accepted | 2026-01-15 |
| [ADR-004](./ADR-004-port-allocation-per-worker.md) | Port Allocation per Worker | Accepted | 2026-01-15 |
| [ADR-005](./ADR-005-state-store-architecture.md) | Dual State Store Architecture (etcd + MongoDB) | Accepted | 2026-01-16 |
| [ADR-006](./ADR-006-resource-scheduler-ha-coordination.md) | Resource Scheduler High Availability Coordination | Accepted | 2026-01-16 |
| [ADR-007](./ADR-007-worker-template-seeding.md) | Worker Template Seeding and Management | Accepted | 2026-01-15 |
| [ADR-008](./ADR-008-worker-draining-state.md) | Worker Draining State for Scale-Down | Accepted | 2026-01-16 |
| [ADR-009](./ADR-009-shared-core-package.md) | Shared Core Package Architecture | Accepted | 2026-01-16 |
| [ADR-010](./ADR-010-service-unification-neuroglia.md) | Service Unification on Neuroglia Framework | Accepted | 2026-01-17 |
| [ADR-011](./ADR-011-apscheduler-removal.md) | APScheduler Removal and Controller Migration | Accepted | 2026-01-19 |
| [ADR-012](./ADR-012-dynamic-region-configuration.md) | Dynamic Region Configuration | Accepted | 2026-01-19 |
| [ADR-013](./ADR-013-sse-protocol-improvements.md) | SSE Protocol Improvements | Accepted | 2026-01-19 |
| [ADR-014](./ADR-014-worker-orphan-detection.md) | Worker Orphan Detection and Garbage Collection | Accepted | 2026-02-06 |
| [ADR-015](./ADR-015-control-plane-api-no-ec2.md) | Control Plane API Must Not Call AWS EC2 | Accepted | 2026-02-06 |
| [ADR-016](./ADR-016-license-operations-via-worker-controller.md) | License Operations via Worker-Controller | Accepted | 2026-02-06 |
| [ADR-017](./ADR-017-lab-operations-via-lablet-controller.md) | Lab Operations via Lablet-Controller | Accepted | 2026-02-06 |
| [ADR-018](./ADR-018-lds-integration.md) | Lab Delivery System (LDS) Integration | Accepted | 2025-02-10 |
| [ADR-019](./ADR-019-labrecord-independent-aggregate.md) | LabRecord as Independent AggregateRoot | Accepted (Partially Superseded) | 2026-02-10 |
| [ADR-020](./ADR-020-session-entity-model.md) | Session Entity Model Redesign | Accepted | 2026-02-18 |
| [ADR-021](./ADR-021-child-entity-architecture.md) | Child Entity Architecture for Session Tracking | Accepted | 2026-02-18 |
| [ADR-022](./ADR-022-cloudevent-ingestion-lablet-controller.md) | CloudEvent Ingestion via Lablet-Controller | Accepted | 2026-02-18 |
| [ADR-023](./ADR-023-content-sync-trigger.md) | Content Sync Trigger via Reactive etcd Watch | Accepted | 2026-02-25 |
| [ADR-024](./ADR-024-content-package-storage.md) | Content Package Storage in RustFS | Accepted | 2026-02-25 |
| [ADR-025](./ADR-025-content-metadata-storage.md) | Content Metadata Storage in MongoDB | Accepted | 2026-02-25 |
| [ADR-026](./ADR-026-upstream-notifier-pattern.md) | Extensible Upstream Notifier Pattern (Deferred) | Accepted | 2026-02-25 |
| [ADR-027](./ADR-027-content-version-auto-increment.md) | Version Auto-Increment on Content Change | Accepted | 2026-02-25 |
| [ADR-028](./ADR-028-definition-initial-status.md) | LabletDefinition Initial Status (PENDING_SYNC) | Accepted | 2026-02-25 |
| [ADR-029](./ADR-029-port-template-extraction-from-cml-yaml.md) | Port Template Extraction from CML YAML | Accepted | 2026-02-25 |
| [ADR-030](./ADR-030-resource-observation-learn-from-live.md) | Resource & Port Observation — "Learn from Live" | Accepted | 2026-02-28 |
| [ADR-031](./ADR-031-checkpoint-instantiation-pipeline.md) | Checkpoint-Based Instantiation Pipeline | Accepted | 2026-03-02 |
| [ADR-032](./ADR-032-port-allocation-labrecord-topology.md) | Port Allocation as LabRecord Topology Concern | Accepted | 2026-03-02 |
| [ADR-033](./ADR-033-cml-node-tag-sync.md) | CML Node Tag Sync with Allocated Ports | Accepted | 2026-03-02 |

## Status Definitions

| Status | Meaning |
|--------|---------|
| **Proposed** | Under discussion, not yet approved |
| **Accepted** | Decision made and should be followed |
| **Superseded** | Replaced by another ADR |
| **Deprecated** | No longer relevant |

## ADR Template

When creating new ADRs, use this template:

```markdown
# ADR-NNN: Title

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | YYYY-MM-DD |
| **Deciders** | Team/Person |
| **Related ADRs** | Links to related ADRs |

## Context

What is the issue that we're seeing that is motivating this decision or change?

## Decision

What is the change that we're proposing and/or doing?

## Rationale

Why is this decision being made? What alternatives were considered?

## Consequences

### Positive
- What becomes easier or possible?

### Negative
- What becomes harder or impossible?

### Risks
- What could go wrong?

## Implementation Notes

Technical details, code examples, configuration.
```

## Dependency Graph

```
ADR-001 (API-Centric)
    ├── ADR-002 (Scheduler) ─────┐
    │       └── ADR-006 (HA) ◄───┤
    │                            │
    ├── ADR-005 (State Store) ◄──┘
    │       └── ADR-006 (HA)
    │
    └── ADR-013 (SSE Improvements)
            └── no controller-direct Redis

ADR-003 (CloudEvents)
    └── ADR-004 (Ports)

ADR-007 (Templates) ← standalone

ADR-008 (Draining)
    └── ADR-002 (Scheduler)

ADR-009 (Shared Core)
    └── ADR-010 (Neuroglia Unification)

ADR-010 (Neuroglia Unification)
    ├── ADR-011 (APScheduler Removal)
    └── ADR-012 (Dynamic Region Config)

ADR-011 (APScheduler Removal)
    └── controller-based execution replaces jobs

ADR-012 (Dynamic Region Config)
    └── SystemSettings + WorkerReconciler._run_discovery_loop()

ADR-013 (SSE Improvements)
    └── batching, filtering, extended events

ADR-018 (LDS Integration)
    ├── ADR-017 (Lab Operations via Lablet-Controller)
    ├── ADR-020 (Session Entity Model) ← amends terminology
    └── ADR-022 (CloudEvent Ingestion) ← amends routing

ADR-019 (LabRecord)
    └── ADR-020 (Session Entity Model) ← supersedes binding model

ADR-020 (Session Entity Model)
    ├── ADR-018 (LDS Integration)
    ├── ADR-019 (LabRecord) ← partially supersedes
    └── ADR-021 (Child Entities)

ADR-021 (Child Entity Architecture)
    ├── ADR-020 (Session Entity Model)
    └── ADR-022 (CloudEvent Ingestion)

ADR-022 (CloudEvent Ingestion)
    ├── ADR-003 (CloudEvents)
    ├── ADR-015 (Control Plane API No External Calls)
    └── ADR-018 (LDS Integration) ← amends §7

# Content Synchronization cluster (ADR-023–028)
ADR-023 (Content Sync Trigger)
    ├── ADR-005 (Dual State Store) ← extends etcd key namespace
    ├── ADR-015 (CPA No External Calls)
    ├── ADR-017 (Lab Operations) ← extends reconciliation pattern
    ├── ADR-024 (Package Storage)
    ├── ADR-025 (Content Metadata)
    └── ADR-026 (Upstream Notifier)

ADR-024 (Package Storage in RustFS)
    └── ADR-025 (Content Metadata) ← complementary

ADR-025 (Content Metadata in MongoDB)
    ├── ADR-005 (Dual State Store)
    └── ADR-024 (Package Storage) ← complementary

ADR-026 (Upstream Notifier Pattern)
    └── ADR-018 (LDS Integration)

ADR-027 (Version Auto-Increment)
    ├── ADR-023 (Content Sync Trigger)
    └── ADR-028 (Definition Initial Status)

ADR-028 (Definition Initial Status)
    ├── ADR-023 (Content Sync Trigger)
    └── ADR-027 (Version Auto-Increment)

ADR-029 (Port Template Extraction)
    ├── ADR-025 (Content Metadata Storage)
    └── ADR-028 (Definition Initial Status)

ADR-030 (Resource & Port Observation — Learn from Live)
    ├── ADR-004 (Port Allocation per Worker)
    ├── ADR-017 (Lab Operations via Lablet-Controller)
    ├── ADR-020 (Session Entity Model)
    └── ADR-029 (Port Template Extraction)

# Instantiation Pipeline cluster (ADR-031–033)
ADR-031 (Checkpoint Pipeline)
    ├── ADR-004 (Port Allocation per Worker)
    ├── ADR-017 (Lab Operations via Lablet-Controller)
    ├── ADR-020 (Session Entity Model)
    ├── ADR-029 (Port Template Extraction)
    ├── ADR-030 (Resource Observation)
    ├── ADR-032 (Port Allocation on LabRecord)
    └── ADR-033 (CML Node Tag Sync)

ADR-032 (Port Allocation as LabRecord Topology)
    ├── ADR-004 (Port Allocation per Worker)
    ├── ADR-019 (LabRecord as AggregateRoot)
    ├── ADR-020 (Session Entity Model)
    ├── ADR-029 (Port Template Extraction)
    ├── ADR-031 (Checkpoint Pipeline)
    └── ADR-033 (CML Node Tag Sync)

ADR-033 (CML Node Tag Sync)
    ├── ADR-004 (Port Allocation per Worker)
    ├── ADR-017 (Lab Operations via Lablet-Controller)
    ├── ADR-029 (Port Template Extraction)
    ├── ADR-031 (Checkpoint Pipeline)
    └── ADR-032 (Port Allocation on LabRecord)
```
