# Future Roadmap & Unaddressed Requirements

| Attribute | Value |
|-----------|-------|
| **Last Updated** | 2026-02-10 |
| **Purpose** | Track requirements and features not yet implemented |

---

## Overview

This document tracks requirements from the [LRM Requirements Specification](../specs/lablet-resource-manager-requirements.md) that are planned for future phases, along with architectural capabilities that have been designed but not yet implemented.

!!! note "Living Document"
    This document is updated as features move from planned → in-progress → completed.

---

## Priority Classification

| Priority | Meaning | Target Phase |
|----------|---------|--------------|
| **P0** | Critical for MVP | Phase 1 (Current) |
| **P1** | Required for production | Phase 2 |
| **P2** | Deferred/Enhancement | Phase 3+ |

---

## Deferred Requirements (P2)

### Warm Pool (Pre-Provisioning) - FR-2.7.x

**Status**: 🔴 Not Started

| Requirement ID | Description |
|----------------|-------------|
| FR-2.7.1a | Maintain warm pool per LabletDefinition (if configured) |
| FR-2.7.1b | Warm pool = labs imported and stopped (not started) |
| FR-2.7.1c | Start warm lab instead of importing new |
| FR-2.7.1d | Replenish warm pool after consumption |

**Rationale for Deferral**: Warm pool adds operational complexity and cost (idle labs consume resources). Initial focus is on on-demand provisioning with acceptable startup times.

**Dependencies**:

- LabletDefinition `warm_pool_depth` attribute (schema defined)
- Lab import/stop automation (exists in lablet-controller)
- Pool replenishment background job

**Estimated Effort**: 2-3 sprints

---

### Feature Flags - NFR-3.6.3

**Status**: 🔴 Not Started

| Requirement ID | Description |
|----------------|-------------|
| NFR-3.6.3 | Feature flags for gradual rollout |

**Rationale for Deferral**: Not required for initial deployment; can be added when multi-tenant or staged rollouts become necessary.

**Recommended Approach**:

- Use environment variables initially
- Consider LaunchDarkly or custom etcd-based flags later

---

## Out of Scope (Future Versions)

### Multi-Cloud Provider Support

**Status**: 🔵 Designed (SPI Ready)

The CloudProviderSPI abstraction is in place to support future cloud providers:

- AWS (implemented)
- Azure (planned)
- GCP (planned)
- On-premises VMware (planned)

**Blocking Items**:

- CML licensing model variations per cloud
- Region/zone mapping abstractions

---

### Cross-Region Failover

**Status**: 🔴 Not Started

Per constraint A-5: "Region isolation acceptable (no cross-region failover)"

**Future Considerations**:

- MongoDB multi-region replication
- etcd cluster spanning regions
- DNS-based failover

---

### Real-Time Collaborative Lab Sessions

**Status**: 🔴 Not Started

Multiple users interacting with the same lab simultaneously.

**Blocking Items**:

- CML API limitations
- Conflict resolution for concurrent edits
- Session multiplexing

---

### Custom Node Definition Management

**Status**: 🔴 Not Started

User-defined CML node types and images.

**Blocking Items**:

- Image validation and security scanning
- Storage and distribution of custom images
- Licensing implications

---

## Implementation Readiness

### SPI Abstractions (Ready for Extension)

| SPI | Status | Implementations | ADR |
|-----|--------|-----------------|-----|
| `CloudProviderSPI` | ✅ Defined | AWS only | - |
| `CMLSystemSPI` | ✅ Defined | CML REST API | - |
| `CMLLabsSPI` | ✅ Defined | CML REST API | - |
| `LabDeliverySPI` | ✅ Required | LDS REST API | [ADR-018](adr/ADR-018-lds-integration.md) |
| `GradingSPI` | 🟡 Planned | Grading Engine integration | - |

!!! info "LabDeliverySPI Promoted"
    As of ADR-018, LabDeliverySPI moved from "Planned" to "Required" for LabletInstance provisioning.
    See [FR-2.2.5 LabSession Provisioning](../specs/lablet-resource-manager-requirements.md#fr-225-labsession-provisioning).

---

## Tracking

| Feature | Requirement | Status | Target Phase | ADR |
|---------|-------------|--------|--------------|-----|
| **LDS Integration** | FR-2.2.5 | ✅ Designed | Phase 1 | [ADR-018](adr/ADR-018-lds-integration.md) |
| Warm Pool | FR-2.7.x | 🔴 Not Started | Phase 3 | - |
| Feature Flags | NFR-3.6.3 | 🔴 Not Started | Phase 3 | - |
| Multi-Cloud | C-5 | 🔵 Designed | Phase 4+ | - |
| Cross-Region | A-5 | 🔴 Not Started | Phase 4+ | - |
| Collaborative Labs | - | 🔴 Not Started | TBD | - |
| Custom Nodes | - | 🔴 Not Started | TBD | - |

---

## Related Documents

- [LRM Requirements Specification](../specs/lablet-resource-manager-requirements.md)
- [Architecture Overview](index.md)
- [ADR Index](adr/README.md)
