# ADR-002: Separate Resource Scheduler Service

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-01-15 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-001](./ADR-001-api-centric-state-management.md), [ADR-006](./ADR-006-resource-scheduler-ha-coordination.md) |

## Context

The placement logic for assigning LabletInstances to Workers requires evaluating constraints (license affinity, resource requirements, capacity) and making optimal decisions. We need to decide whether this logic lives in the API or a separate service.

Options considered:

1. **Embedded in API** - Scheduling logic runs within API request handlers
2. **Separate service** - Dedicated Resource Scheduler service with its own lifecycle
3. **Serverless functions** - Lambda/Cloud Functions triggered on events

## Decision

**Resource Scheduler runs as a separate microservice, not embedded in the API.**

The Resource Scheduler:

- Operates on its own reconciliation loop
- Subscribes to state changes via watchers (etcd) and periodic polling
- Calls Control Plane API to record scheduling decisions
- Can be scaled and deployed independently

## Rationale

### Benefits

- **Separation of Concerns**: Placement algorithm isolated from CRUD operations
- **Independent Scaling**: Resource Scheduler can scale based on queue depth, not API traffic
- **Easier Testing**: Scheduling logic testable in isolation
- **Upgradability**: Algorithm improvements deployed without API changes
- **Failure Isolation**: Resource Scheduler issues don't impact API availability

### Trade-offs

- Additional deployment complexity
- Network latency between Scheduler and API
- Requires coordination mechanism for HA (see ADR-006)

## Consequences

### Positive

- Clean domain boundaries
- Algorithm can be optimized/replaced independently
- Scheduler failures don't cascade to API

### Negative

- Operational overhead of additional service
- Must handle distributed system complexities

## Implementation Notes

- Scheduler subscribes to etcd watch for `LabletInstance` changes
- Redundant periodic reconciliation (30s) as fallback
- Placement decision written back via `POST /api/internal/instances/{id}/schedule`
- Metrics exposed for scheduling latency and queue depth
