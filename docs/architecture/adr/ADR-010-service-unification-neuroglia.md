# ADR-010: Service Unification on Neuroglia Framework

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-01-16 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-001](./ADR-001-api-centric-state-management.md), [ADR-002](./ADR-002-separate-resource-scheduler-service.md), [ADR-009](./ADR-009-shared-core-package.md) |

## Context

The Lablet Cloud Manager system consists of multiple microservices with divergent implementation patterns:

| Service | Current State | Pattern |
|---------|---------------|---------|
| **control-plane-api** | Production | Neuroglia + FastAPI, Full DI, CQRS, REST API |
| **resource-scheduler** | In Development | Plain asyncio, Manual wiring, No API |
| **worker-controller** | Scaffold | Plain asyncio, Manual wiring, No API |
| **lablet-controller** | Scaffold | Plain asyncio, Manual wiring, No API |

The current approach creates divergence:

- Different DI patterns across services
- Inconsistent error handling and logging
- No standard health/metrics/info endpoints
- No Swagger documentation for admin/ops
- No RBAC/security patterns
- Different testing approaches

Options considered:

1. **Keep services separate** - Each service uses its own patterns
2. **Merge all into control-plane-api** - Single monolithic service
3. **Unify on Neuroglia framework** - All services use common patterns

## Decision

**Unify all services on the Neuroglia framework**, using `lcm-core` (ADR-009) as an interim location for shared infrastructure that will later migrate to the framework.

### Core Principles

1. **Consistency**: All services use WebApplicationBuilder, HostedService, DI, Mediator patterns
2. **Observability**: Standard `/health`, `/ready`, `/metrics`, `/info` endpoints on all services
3. **Security**: RBAC via Keycloak integration, internal API keys for service-to-service
4. **Extensibility**: Resource-oriented patterns (reconciliation loops) as HostedService extensions
5. **Testability**: Shared testing utilities, consistent mocking patterns

## Rationale

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           neuroglia-python                                  │
│  (Core framework: DI, Mediator, HostedService, ControllerBase, Serializer)  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ▲
                                      │ extends
┌─────────────────────────────────────┼─────────────────────────────────────┐
│                                lcm-core                                     │
├─────────────────────────────────────┴─────────────────────────────────────┤
│  INFRASTRUCTURE (interim - will move to neuroglia)                          │
│  ├── ReconciliationHostedService    # Base for resource-oriented services   │
│  ├── LeaderElectedHostedService     # Leader election + reconciliation      │
│  ├── StandardEndpointsMixin         # /health, /ready, /metrics, /info      │
│  └── ServiceAuthMiddleware          # API key + RBAC validation             │
├─────────────────────────────────────────────────────────────────────────────┤
│  DOMAIN (shared read models)                                                │
│  ├── CMLWorkerReadModel, LabletInstanceReadModel, LabletDefinitionReadModel │
│  └── WorkerCapacityDto, SchedulingDecisionDto, etc.                         │
├─────────────────────────────────────────────────────────────────────────────┤
│  INTEGRATION (shared clients)                                               │
│  ├── ControlPlaneApiClient          # HTTP client for Control Plane API     │
│  └── EtcdClient                     # etcd client for leader election       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ▲
          ┌───────────────────────────┼────────────────────────────┐
          │                           │                            │
┌─────────┴─────────┐   ┌─────────────┴─────────────┐   ┌─────────┴─────────┐
│ control-plane-api │   │    resource-scheduler     │   │ worker-controller │
├───────────────────┤   ├───────────────────────────┤   ├───────────────────┤
│ Neuroglia WebHost │   │ Neuroglia WebHost         │   │ Neuroglia WebHost │
│ Full REST API     │   │ Minimal REST (admin only) │   │ Minimal REST      │
│ CQRS Commands     │   │ SchedulerHostedService    │   │ WorkerReconciler  │
│ Event Sourcing    │   │ PlacementEngine           │   │ AWS EC2 SPI       │
│ MongoDB (SOT)     │   │ No persistence needed     │   │ CloudWatch SPI    │
│ BFF for UI        │   │ etcd for leader election  │   │ CML System SPI    │
└───────────────────┘   └───────────────────────────┘   └───────────────────┘
```

### Service Responsibilities

| Service | Domain Layer | Persistence | State Source |
|---------|--------------|-------------|--------------|
| **control-plane-api** | All aggregates (SOT) | MongoDB | Creates/mutates all entities |
| **resource-scheduler** | Read-only views | None (stateless) | Reads from Control Plane API |
| **worker-controller** | Worker lifecycle | None (stateless) | Reads from Control Plane + AWS |
| **lablet-controller** | Instance lifecycle | None (stateless) | Reads from Control Plane + CML |

### Standard API Endpoints

All services expose:

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/health` | GET | Liveness probe | None |
| `/ready` | GET | Readiness probe | None |
| `/metrics` | GET | Prometheus metrics | Internal |
| `/info` | GET | Service info (version, leader status) | Internal |
| `/docs` | GET | Swagger UI | Admin RBAC |

Controller-specific admin endpoints:

```
# resource-scheduler
POST /admin/trigger-reconcile   # Force reconciliation cycle
GET  /admin/leader-status       # Who is leader

# worker-controller
POST /admin/trigger-refresh/{worker_id}   # Force worker refresh
GET  /admin/reconciliation-status         # Current reconciliation state

# lablet-controller
POST /admin/trigger-instantiate/{instance_id}  # Force instantiation
GET  /admin/pending-instantiations             # Queue status
```

## Consequences

### Positive

- **Consistency**: Single way to build services, test, deploy
- **Maintainability**: Shared code in lcm-core, less duplication
- **Operability**: Standard endpoints for monitoring/debugging
- **Security**: Unified RBAC, consistent auth patterns
- **Extensibility**: New services follow established patterns

### Negative

- **Initial Effort**: Refactoring existing code takes time
- **Learning Curve**: Team must understand Neuroglia patterns
- **Framework Lock-in**: Tied to Neuroglia for core patterns

### Neutral

- **lcm-core as Interim**: Code will eventually migrate to neuroglia-python
- **Minimal REST for Controllers**: Not full CRUD, just admin/observability

## Implementation

See: [Service Unification Implementation Plan](../../implementation/service-unification-plan.md)

## References

- [Neuroglia Framework](https://github.com/neuroglia-io/python-framework)
- [Kubernetes Controller Pattern](https://kubernetes.io/docs/concepts/architecture/controller/)
- [12-Factor App](https://12factor.net/)
