# ADR-046: Host Abstraction and PodType / HostType Split

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-06-12 |
| **Deciders** | Architecture Team |
| **Extends** | [ADR-036](./ADR-036-resource-management-abstraction-layer.md) (Resource Management Abstraction) |
| **Related ADRs** | [ADR-015](./ADR-015-control-plane-api-no-ec2.md) (CPA no EC2), [ADR-016](./ADR-016-license-operations-via-worker-controller.md), [ADR-019](./ADR-019-labrecord-independent-aggregate.md) (LabRecord), [ADR-037](./ADR-037-timeslot-management.md) (Timeslot), [ADR-045](./ADR-045-multi-part-session-part-model.md) |

---

## 1. Context

Today the only host is a `CmlWorker` (an EC2 instance running CML), and `PodType` conflates
**what a pod is** with **where it runs**. The platform must support more environments:

| Environment | Workload | Where it runs |
|---|---|---|
| CML on AWS | CML lab | EC2 instance (hypervisor-style) |
| VMware | VMs | vSphere host |
| Proxmox | VMs/containers | Proxmox node |
| ROC / RADkit _(device access, not a host)_ | command bulks on reachable devices | _no host provisioned_ — external fabric |
| CCIE hardware | physical appliances | a **hardware rack** (no hypervisor) |
| AWS-native | managed services | AWS account directly (no host VM) |

A single `PodType` enum cannot express these cleanly: `hybrid_hardware` and `native_aws` are
**platforms**, not workloads, and the same workload (e.g. CML) could in principle run on more
than one platform. There is also no generic infrastructure layer — `CmlWorker` is hardcoded.

## 2. Decision

### 2.1 Two orthogonal axes

Split the single conflated enum into two:

| Axis | Enum | Answers | Examples |
|---|---|---|---|
| **Workload** | `PodType` | _what is the pod?_ | `cml_on_aws`, `proxmox`, `vmware` |
| **Platform** | `HostType` | _where does it run?_ | `cml_on_aws`, `vmware`, `proxmox`, `native_aws`, `hybrid_hardware` |

> `roc_radkit` is intentionally **absent** from `PodType`: it is **not a workload LCM
> provisions**. ROC / RADkit is a **device-access / collection transport** used by SE's _Collect_
> step against **pre-existing** devices (any device with a text interface). A device-based part
> therefore has **no** `PodInstance` and binds to **no** `Host` — it is reached via ROC/RADkit.

A `PodDefinition` declares both `pod_type` and target `host_type`. A `PodInstance` of a given
`PodType` **binds** to a `Host` of a given `HostType`.

### 2.2 Generic `Host` / `Worker` TimedResource + adapters

Introduce a generic `Host` (a.k.a. `Worker`) Layer-3 `TimedResource` with a **per-platform
adapter**. `CmlWorker` becomes the `cml_on_aws` `Host` variant; other adapters implement the
same host interface for VMware, Proxmox, native AWS, and hardware racks.

```
Host (TimedResource)
  ├─ cml_on_aws adapter   → EC2 + CML  (current CmlWorker)
  ├─ vmware adapter       → vSphere
  ├─ proxmox adapter      → Proxmox API
  ├─ native_aws adapter   → AWS-managed services (no host VM)
  └─ hybrid_hardware adapter → physical rack reservation
```

The host adapter contract is: **observe** (status/capacity), **provision**, **bind/unbind a
pod**, **teardown**. Pod managers request a host of the required `HostType` from the
resource-scheduler, which is now `HostType`-aware for capacity.

### 2.3 Provisioning strategy from `Timeslot.lead_time`

JIT vs eager is **derived**, not a new field:

- **JIT** (short `lead_time`): `cml_on_aws` pods provisioned shortly before `start`.
- **Eager** (large `lead_time` / pre-booked): `hybrid_hardware` pods carry a long lead so
  `provision_at` precedes the part's active window — enabling early/overlapping provisioning
  (ADR-045 §2.3).

No `provisioning_strategy` field and no separate pre-booking resource are introduced; the
`Timeslot` already carries enough information.

## 3. Consequences

**Positive**

- New platforms are added by writing a host adapter — no change to the resource tree or
  reconciliation framework.
- Workload and platform vary independently; `hybrid_hardware` and `native_aws` are expressible.
- Scheduler capacity is reasoned per `HostType`.

**Negative / trade-offs**

- `CMLWorker` is re-expressed as the `cml_on_aws` `Host` variant (clean cut, no compat shim).
- `PodType` consumers must be updated to also consider `HostType` where the two diverge.

**Neutral**

- `LabRecord` remains the `cml_on_aws` `PodInstance` (ADR-019 unaffected in substance).

## 4. Related

- [resource-model.md](../solution/resource-model.md) — value objects and the host layer.
- [session-model.md](../solution/session-model.md) — `PodDefinition` and the two axes.
