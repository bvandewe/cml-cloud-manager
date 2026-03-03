# ADR-001: API-Centric State Management

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-01-15 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-002](./ADR-002-separate-resource-scheduler-service.md), [ADR-005](./ADR-005-state-store-architecture.md) |

## Context

The Lablet Resource Manager requires multiple services (Control Plane API, Scheduler, Resource Controller) to coordinate on shared state. We need to decide how these services interact with persistent storage.

Options considered:

1. **Direct database access** - Each service reads/writes to MongoDB directly
2. **API-centric** - Only Control Plane API accesses databases; other services use API
3. **Event sourcing** - All state changes flow through event store

## Decision

**Control Plane API is the single point for all state mutations.**

- Only the Control Plane API writes to the state store (etcd) and spec store (MongoDB)
- Scheduler and Resource Controller services read state via API or watch mechanisms
- All mutations flow through the API, enabling centralized admission control

## Rationale

### Benefits

- **Consistency**: Single writer eliminates race conditions and conflicting updates
- **Admission Control**: Centralized validation, authorization, and rate limiting
- **Audit Trail**: All mutations pass through one point for logging
- **Simplicity**: Scheduler and Controller remain stateless (easier HA)
- **Observability**: Single point for tracing all state changes

### Trade-offs

- API becomes critical path (mitigated by HA deployment with multiple replicas)
- Slightly higher latency for internal service-to-service operations
- Requires well-designed internal API endpoints for Scheduler/Controller

## Consequences

### Positive

- Clear separation of concerns
- Easier to reason about state changes
- Simplified testing (mock API instead of database)

### Negative

- Additional network hop for Scheduler/Controller operations
- API must handle internal traffic in addition to external clients

### Risks

- API availability is critical; requires robust HA deployment
- Internal API versioning must be maintained

## Implementation Notes

- Internal endpoints under `/api/internal/*` for Scheduler/Controller
- Consider gRPC for internal communication (performance optimization)
- Circuit breakers for Scheduler/Controller API calls
