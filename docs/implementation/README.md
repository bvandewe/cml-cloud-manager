# Implementation Guide

| Attribute | Value |
|-----------|-------|
| **Document Version** | 2.0.0 |
| **Status** | Current |
| **Created** | 2026-01-16 |
| **Last Updated** | 2026-02-09 |
| **Author** | LCM Architecture Team |

---

## Overview

This directory contains the implementation documentation for Lablet Cloud Manager (LCM), a microservices-based system for managing AWS EC2-based Cisco Modeling Lab (CML) workers with monitoring, metrics collection, and lab orchestration.

## Authoritative Documents

| Document | Purpose |
|----------|---------|
| **[MVP Implementation Plan](./mvp-implementation-plan.md)** | **Single source of truth** for implementation phases, tasks, and acceptance criteria |
| [Codebase Discovery Audit](./codebase-discovery-audit.md) | Analysis of current codebase state vs. requirements |
| [Implementation Status](./IMPLEMENTATION_STATUS.md) | Tracking matrix for requirement implementation across all services |
| [Testing Strategy](./testing-strategy.md) | Testing approach and coverage requirements |
| [Risk Register](./risk-register.md) | Risk analysis and mitigation strategies |

## Quick Links

### Requirements

- [Requirements Specification](../specs/lablet-resource-manager-requirements.md) - Functional and non-functional requirements

### Architecture

- [Architecture Overview](../architecture/lablet-resource-manager-architecture.md) - System design
- [ADRs](../architecture/adr/README.md) - Architectural decision records

### Services

| Service | Purpose |
|---------|---------|
| [control-plane-api](../../src/control-plane-api/) | Central API, domain aggregates, CQRS commands/queries, UI |
| [resource-scheduler](../../src/resource-scheduler/) | Lablet placement decisions, capacity-aware scheduling |
| [worker-controller](../../src/worker-controller/) | EC2 lifecycle, metrics, auto-scaling |
| [lablet-controller](../../src/lablet-controller/) | CML lab lifecycle, LDS integration |
| [lcm-core](../../src/core/) | Shared library (read models, SPI clients, domain types) |

## Implementation Phases

See [MVP Implementation Plan](./mvp-implementation-plan.md) for detailed phase breakdown.

| Phase | Focus | Status | Bootstrap |
|-------|-------|--------|-----------|
| Phase 0 | Domain Prerequisites | ✅ Complete (2026-02-08) | [PHASE_0_BOOTSTRAP.md](./PHASE_0_BOOTSTRAP.md) |
| Phase 1 | Worker Foundation | ✅ Complete (2026-02-09) | [PHASE_1_BOOTSTRAP.md](./PHASE_1_BOOTSTRAP.md) |
| Phase 2 | Resource Scheduling | ✅ Complete (2026-02-10) | [PHASE_2_BOOTSTRAP.md](./PHASE_2_BOOTSTRAP.md) |
| Phase 3 | Auto-Scaling | ✅ Complete (2026-02-08) | [PHASE_3_BOOTSTRAP.md](./PHASE_3_BOOTSTRAP.md) |
| Phase 4 | LDS Integration | 🔄 ~90% Complete (2026-02-09) | [PHASE_4_BOOTSTRAP.md](./PHASE_4_BOOTSTRAP.md) |
| Phase 5 | Grading Integration | ⬜ Not Started | — |

### Test Counts by Phase

| Phase | Tests Added | Cumulative |
|-------|-------------|------------|
| Phase 0 | 21 (domain) | 210 |
| Phase 1 | 26 (capacity) | 387 |
| Phase 2 | 41 (scheduling) | 77 RS |
| Phase 3 | 44 (scaling) | 14 CPA + 17 RS + 13 WC |
| Phase 4 | 57 (LDS) | 44 LC + 5 CPA + 8 CPA |

## Getting Started

1. Read the [MVP Implementation Plan](./mvp-implementation-plan.md)
2. Review the [Codebase Discovery Audit](./codebase-discovery-audit.md) for current state
3. Check [Requirements Specification](../specs/lablet-resource-manager-requirements.md) for context
4. Follow phase tasks in order (dependencies are documented)
5. Use the relevant [Bootstrap Document](./PHASE_4_BOOTSTRAP.md) when starting a new phase

## Key Architectural Decisions (MVP)

| Decision | Phase | Summary |
|----------|-------|---------|
| AD-P4-01 | 4 | Atomic mark-ready command (INSTANTIATING→READY with all LDS fields) |
| AD-P4-02 | 4 | Device mapping via static helper for testability |
| AD-P4-03 | 4 | Multi-instance session matching for session.started events |
| AD-21 | 3 | Discovery state sync bugfix (full EC2 state sync in bulk import) |

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 2.0.0 | 2026-02-09 | LCM Architecture Team | Major rewrite: updated phase statuses (P0-P3 complete, P4 ~90%), added bootstrap links, test counts, architectural decisions, service descriptions. Removed stale "Not Started" statuses. |
| 1.0.0 | 2026-02-08 | LCM Architecture Team | Complete rewrite; single authoritative plan structure |
| 0.3.0 | 2026-02-08 | Architecture Team | Added rebuild warning |
| 0.1.0 | 2026-01-16 | Architecture Team | Initial draft |
