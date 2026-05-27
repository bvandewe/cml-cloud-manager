# Sprint Implementation Plan

> **Created:** 2026-05-11
> **Status:** Active
> **Context:** Post ADR-036 Phase 2.5 Batch G, Post Phase 7 Session Migration

## Overview

Prioritized implementation plan covering all outstanding tasks across services.
Organized into 8 sprints ordered by dependency chain, user impact, and risk.

**Current State:**

- Phases 0–4, 6, 7: ✅ Complete
- Phase 5 (Grading): ⬜ Unblocked, awaiting start
- ADR-036 Batches A–G: ✅ Complete, Batch I pending
- Sprint H (TimeslotManager): ✅ Complete
- Test count: ~1,642 across all services

## Sprint Index

| Sprint | Focus | Effort | Status |
|--------|-------|--------|--------|
| [Sprint 1](sprint-plan-s1-ux-fixes.md) | Critical UX Fixes | 1–2 sessions | ⬜ |
| [Sprint 2](sprint-plan-s2-delete-dispose.md) | Delete & Dispose Commands | 2 sessions | ⬜ |
| [Sprint 3](sprint-plan-s3-adr036-batch-i.md) | ADR-036 Batch I — LabletDefinition → TimedResourceState | 1–2 sessions | ⬜ |
| [Sprint 4](sprint-plan-s4-timeslot-scheduling.md) | Timeslot & Scheduling Fixes | 1–2 sessions | ⬜ |
| [Sprint 5](sprint-plan-s5-grading.md) | Phase 5 — Grading Integration | 3–4 sessions | ⬜ |
| [Sprint 6](sprint-plan-s6-refactor-unify.md) | Reconciler Refactor & Frontend Unification | 2–3 sessions | ⬜ |
| [Sprint 7](sprint-plan-s7-hardening.md) | Operational Hardening | 2 sessions | ⬜ |
| [Sprint 8](sprint-plan-s8-security-deploy.md) | Security, Access Control & Deployment | 2–3 sessions | ⬜ |

## Dependency Graph

```
Sprint 1 (UX Fixes) ───────────────────────────────┐
Sprint 2 (Delete/Dispose) ─────────────────────────┐│
Sprint 3 (ADR-036 Batch I) ──┬── Sprint 5 (Grading) ──┬── Sprint 6 (Refactor) ── Sprint 7 (Hardening) ── Sprint 8 (Security)
Sprint 4 (Timeslot Fixes) ───┘                         │
                                                        └── Sprint 7
```

- Sprints 1, 2, 3, 4 can overlap (touch different areas)
- Sprint 5 is the **critical path** to MVP completion
- Sprint 6 should wait until all pipelines are finalized
- Sprints 7 and 8 are post-MVP hardening

## Deferred / Future (Not Scheduled)

| Task | Reason |
|------|--------|
| Preemption support (resource-scheduler) | Requires capacity forecasting first |
| Capacity forecasting | Complex ML/heuristic — post-MVP |
| Manage Lablet Definitions from Mosaic → MinIO/S3 | External integration, needs design |
| Manage user access to labs (CML user sync) | Needs design work |
| Restart/Reset LabletSession use cases | Needs UX design for confirmation flows |

## Conventions

- Each sprint file is self-contained with acceptance criteria
- Tasks use `- [ ]` / `- [x]` for tracking
- Files touched are listed per task for easy code review
- Test expectations are stated per task
