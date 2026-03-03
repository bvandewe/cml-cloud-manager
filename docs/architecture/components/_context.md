# Component Architecture Context

**Version:** 1.1.0 (February 2026)

## Purpose

This directory contains the **Internal Engineering Specifications** for each microservice in the Lablet Cloud Manager platform. These documents detail **how** the components are built, including aggregate designs, reconciliation loops, and integration patterns.

## Key Contents

- **[Control Plane API](./control-plane-api/index.md)**: "The Gateway" - REST API, Bootstrap UI, Authentication, SSE, etcd State Publishing
- **[Resource Scheduler](./resource-scheduler/index.md)**: "The Scheduler" - Placement Algorithm, Timeslot Management, Leader Election
- **[Worker Controller](./worker-controller/index.md)**: "The Infrastructure" - EC2 Lifecycle, CloudWatch Metrics, CML System API
- **[Lablet Controller](./lablet-controller/index.md)**: "The Workload" - Lab Lifecycle, LDS Session Provisioning, Port Allocation

## Structure

Each component folder typically includes:

- `index.md`: Service-level architecture overview
- Domain-specific design docs (e.g., `reconciliation.md`, `placement.md`)
- Integration details (e.g., `aws-integration.md`, `cml-api.md`)

## etcd Watch Architecture

Controllers observe state changes via **etcd watches**, enabling reactive reconciliation:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       REACTIVE STATE OBSERVATION                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────────┐ │
│   │ Control Plane   │───▶│ etcd State      │───▶│ Controller Watch        │ │
│   │ API             │    │ Projector       │    │ (reactive notification) │ │
│   └─────────────────┘    └─────────────────┘    └─────────────────────────┘ │
│                                                              │               │
│                                                              ▼               │
│                                                    ┌─────────────────┐      │
│                                                    │ Reconcile Loop  │      │
│                                                    └─────────────────┘      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Controller | etcd Watch Prefix | Observed States | Actions |
|------------|-------------------|-----------------|---------|
| Worker Controller | `/lcm/workers/` | PENDING, RUNNING, STOPPING | Start/Stop EC2, License |
| Lablet Controller | `/lcm/instances/` | SCHEDULED, READY, GRADED | Import/Start/Stop/Wipe Labs, LDS Sessions |
| Resource Scheduler | `/lcm/workers/`, `/lcm/instances/` | PENDING (instances) | Placement decisions |

## Reconciliation Pattern

All controllers follow the **Kubernetes Controller Pattern**:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    SPEC     │     │   OBSERVE   │     │     ACT     │
│  (Desired)  │ ←→  │   (Actual)  │  →  │ (Reconcile) │
└─────────────┘     └─────────────┘     └─────────────┘
```

| Controller | Spec Source | Observation Target | Actions |
|------------|-------------|-------------------|---------|
| Worker Controller | CMLWorker (MongoDB) | AWS EC2 + CML System | Start/Stop EC2, Register License |
| Lablet Controller | LabletInstance (MongoDB) | CML Labs API + LDS | Import/Start/Stop/Wipe Labs, LDS Sessions |
| Resource Scheduler | LabletInstance (PENDING) | Worker Capacity | Assign Worker + Timeslot |

## Dual Observation Pattern

Controllers use **reactive (etcd watch) + optional polling** for reliability:

1. **Primary**: etcd watch for immediate state change notifications
2. **Secondary**: Optional API polling for convergence assurance (catch missed events)

This pattern ensures eventual consistency even if etcd watch events are lost.

## Related Contexts

- **[System Architecture](../index.md)**: How these components fit together
- **[Domain Models](../../domain/)**: Aggregate and entity specifications
- **[Development Guide](../../development/ai-agent-guide.md)**: Working with the codebase
- **[ADR-018: LDS Integration](../decisions/ADR-018-lab-delivery-system-integration.md)**: Lab Delivery System integration
