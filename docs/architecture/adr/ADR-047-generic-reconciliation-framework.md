# ADR-047: Generic Reconciliation Framework with Per-Type Managers

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-06-12 |
| **Deciders** | Architecture Team |
| **Extends** | [ADR-036](./ADR-036-resource-management-abstraction-layer.md), [ADR-038](./ADR-038-step-handler-registry-and-reconciler-decomposition.md) (Step Handler Registry / Reconciler Decomposition) |
| **Related ADRs** | [ADR-001](./ADR-001-api-centric-state-management.md), [ADR-005](./ADR-005-state-store-architecture.md), [ADR-043](./ADR-043-startup-state-reconciliation.md) (Startup Reconciliation), [ADR-045](./ADR-045-multi-part-session-part-model.md), [ADR-046](./ADR-046-host-abstraction-and-pod-host-type-split.md) |

---

## 1. Context

ADR-038 decomposed the lablet-controller reconciler into per-step handler modules, but the
reconcile _loop_ is still bespoke to `LabletSession`. With the generalized tree (ADR-036 §2.6),
we now reconcile **four** resource kinds (`Session`, `SessionPart`, `PodInstance`, `Host`) across
**three** services (CPA, controllers, worker-controller). Re-implementing observe/diff/act/record
per kind would duplicate logic and drift in behaviour (retry, failure escalation, history,
status propagation).

We want **one** control-loop implementation and a small, well-defined extension point per kind —
the Kubernetes controller-runtime model.

## 2. Decision

### 2.1 One generic loop, per-type managers

Define a generic reconcile loop in `lcm_core`:

```
observe → diff(desired_status, status) → act → record → (cascade)
```

Each resource kind registers a **per-type manager** implementing a narrow interface:

```python
class ResourceManager(Protocol):
    resource_type: str
    async def observe(self, resource_id: str) -> ResourceView: ...
    async def reconcile(self, view: ResourceView) -> ReconcileResult: ...
```

The loop owns: scheduling ticks, loading the resource (+ children), invoking the manager,
persisting `StateTransition`s, bounded-retry accounting, and failure escalation. The manager
owns only the **kind-specific** decision of _what action converges this resource_.

```mermaid
sequenceDiagram
    autonumber
    participant Op as Operator / Scheduler
    participant Loop as Generic Reconcile Loop
    participant Mgr as Per-Type Manager
    participant Store as Resource Store
    participant Infra as Adapter / SE

    Op->>Store: set desired_status (intent)
    loop every reconcile tick
        Loop->>Store: observe (load resource + children)
        Loop->>Mgr: reconcile(resource)
        Mgr->>Mgr: diff(desired_status, status)
        alt converged
            Mgr-->>Loop: no-op
        else action needed
            Mgr->>Infra: act (provision / phase step / teardown)
            Infra-->>Mgr: result
            Mgr->>Store: record StateTransition + update status
            Mgr->>Store: cascade desired_status to children
        end
    end
    Store-->>Op: status bubbles up (SSE)
```

### 2.2 Manager registry and ownership

| Manager | Resource kind | Home service |
|---|---|---|
| Session manager | `Session` | CPA |
| Part manager | `SessionPart` | CPA |
| Pod manager | `PodInstance` | controllers |
| Host manager | `Host` / `Worker` | worker-controller |

The Session and Part managers also drive **content automation** by transitioning `workflow`
phases (submit an SE job, await the result CloudEvent — ADR-044).

### 2.3 Intent cascade (top-down) / status (bottom-up)

`desired_status` flows down the tree, observed `status` flows up:

- operator/scheduler sets `Session.desired_status`;
- Session manager sets each `SessionPart.desired_status` (respecting order + gating);
- Part manager sets each `PodInstance.desired_status`;
- Pod/Host managers reconcile and report `status` upward (and via SSE to the dashboard).

### 2.4 Triggers

A reconcile tick for a resource can be raised by any of:

| Trigger | Source |
|---|---|
| Schedule / timeslot | `provision_at` / `end` reached |
| Operator (UI / API) | set desired, force reconcile, retry phase |
| External event | student submit, webhook (CloudEvent) |
| Inter-resource | child Ready / sibling part complete |

### 2.5 Failure handling

On a failed action the loop applies a **bounded retry** policy (per manager configuration). On
exhaustion the resource is marked `Failed` and the failure is **escalated to its parent**, which
decides abort-subtree vs continue. A resource may never outlive `Timeslot.cleanup_deadline`.

## 3. Consequences

**Positive**

- One audited, testable control loop; behaviour (retry, history, escalation, cascade) is uniform.
- New resource kinds need only a manager + state class, not a new loop.
- Reuses ADR-038's per-step handlers as the actions a manager invokes.

**Negative / trade-offs**

- Requires extracting the loop from the `LabletSession`-specific reconciler into `lcm_core`.
- Cross-service cascade (CPA → controllers) relies on the existing etcd/CloudEvents transport
  (ADR-001/003), so cascade is eventually-consistent, not transactional.

**Neutral**

- Startup reconciliation (ADR-043) becomes "observe all → enqueue ticks" under the same loop.

## 4. Related

- [resource-model.md](../solution/resource-model.md) — reconciliation framework section.
- [unified-resource-management.md](../solution/unified-resource-management.md) — the LCM/SE seam.
