# ADR-031: Checkpoint-Based Instantiation Pipeline

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-02 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-004](./ADR-004-port-allocation-per-worker.md) (Port Allocation), [ADR-017](./ADR-017-lab-operations-via-lablet-controller.md) (Lab Operations via Lablet-Controller), [ADR-020](./ADR-020-session-entity-model.md) (Session Entity Model), [ADR-029](./ADR-029-port-template-extraction-from-cml-yaml.md) (Port Template Extraction), [ADR-030](./ADR-030-resource-observation-learn-from-live.md) (Resource Observation), [ADR-032](./ADR-032-port-allocation-labrecord-topology.md) (Port Allocation on LabRecord), [ADR-033](./ADR-033-cml-node-tag-sync.md) (CML Node Tag Sync) |
| **Implementation** | [Instantiation Pipeline Plan](../../implementation/instantiation-pipeline.md) |

## Context

When a `LabletSession` transitions from `SCHEDULED` → `INSTANTIATING`, the lablet-controller executes a multi-step provisioning sequence: verify content, resolve/import the CML lab, allocate ports, sync CML node tags, bind the lab to the session, start the lab, provision LDS access, and mark the session ready.

The current implementation handles this as a **monolithic waterfall** inside `_handle_instantiating()` on the lablet-controller's reconciler. This approach has critical limitations:

1. **No recovery**: If the reconciler crashes mid-sequence (e.g., after port allocation but before lab start), the entire sequence restarts from scratch on the next reconciliation cycle — potentially leaking previously allocated ports or creating duplicate resources.
2. **No visibility**: Operators have no way to see which step the instantiation is on, what failed, or how long each step took.
3. **No per-step retry**: A transient failure in one step (e.g., CML API timeout during lab start) forces the entire sequence to restart, including steps that already completed successfully.
4. **No step-level metrics**: There is no data on per-step durations, failure rates, or bottlenecks — essential for capacity planning and troubleshooting.

The drain-loop fix (AD-DRAIN-001) resolved a prerequisite issue where the `WatchTriggeredHostedService` could skip events due to a race condition. With that fixed, the reconciler can now reliably re-enter `_handle_instantiating()` on each cycle — making a checkpoint-based approach viable.

## Decision

### 1. DAG-Based Pipeline with Persistent Checkpoints

Replace the monolithic `_handle_instantiating()` with a **Directed Acyclic Graph (DAG)** of 9 named steps. Each step declares its prerequisites; `next_executable_step()` resolves which step to execute next based on dependency completion.

**Pipeline steps (DAG order):**

```
content_sync ──────────┐
                       ├──→ lab_resolve ──→ ports_alloc ──→ tags_sync ──→ lab_binding ──→ lab_start ──→ lds_provision ──→ mark_ready
variables (skip) ──────┘
```

| Step | Requires | Service | Description |
|------|----------|---------|-------------|
| `content_sync` | — | lablet-controller | Verify LabletDefinition content is synced and available |
| `variables` | — | lablet-controller | Variable substitution (placeholder — skipped for now) |
| `lab_resolve` | `content_sync` | lablet-controller → CML SPI | Resolve or import lab topology on the target CML worker |
| `ports_alloc` | `lab_resolve` | lablet-controller → CPA | Allocate ports from worker range, write to `LabRecord.allocated_ports` |
| `tags_sync` | `ports_alloc` | lablet-controller → CML SPI | Write allocated ports as CML node tags via PATCH API |
| `lab_binding` | `tags_sync` | lablet-controller → CPA | Bind LabRecord to session, create LabRunRecord, denormalize ports |
| `lab_start` | `lab_binding` | lablet-controller → CML SPI | Start CML lab, poll until BOOTED |
| `lds_provision` | `lab_start` | lablet-controller → LDS SPI | Create LDS UserSession, set devices with port mappings |
| `mark_ready` | `lds_provision` | lablet-controller → CPA | Transition session INSTANTIATING → READY |

### 2. InstantiationProgress Value Object

Progress is tracked via an `InstantiationProgress` value object persisted on the `LabletSession` aggregate:

```python
@dataclass(frozen=True)
class StepResult:
    step: str                           # Step name (e.g., "content_sync")
    status: str                         # "pending" | "running" | "completed" | "failed" | "skipped"
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    attempt_count: int                  # Number of attempts (for retry tracking)
    requires: tuple[str, ...]           # Prerequisites (step names)
    output: dict | None                 # Step-specific output data

@dataclass(frozen=True)
class InstantiationProgress:
    steps: tuple[StepResult, ...]
    pipeline_started_at: datetime | None
    pipeline_completed_at: datetime | None

    def next_executable_step(self) -> StepResult | None:
        """Return the next step whose prerequisites are all completed."""
        completed = {s.step for s in self.steps if s.status == "completed"}
        for step in self.steps:
            if step.status in ("pending", "failed"):
                if all(req in completed for req in step.requires):
                    return step
        return None
```

### 3. One Step per Reconciliation Cycle

Each reconciliation cycle executes **at most one step**, then persists the updated progress to the CPA and requeues. This ensures:

- **Crash safety**: Progress is checkpointed between steps — a crash never loses more than one step's work
- **Fair scheduling**: Other sessions get reconciliation cycles between steps
- **Observable progress**: Each step update triggers a domain event and SSE broadcast

### 4. Step Dispatch in Reconciler

Steps are implemented as methods on the reconciler class (Option A: inline). The dispatcher maps step names to handler methods:

```python
async def _handle_instantiating(self, instance):
    progress = instance.instantiation_progress or self._build_default_progress(instance)

    next_step = progress.next_executable_step()
    if not next_step:
        return ReconciliationResult.success()

    handler = {
        "content_sync": self._step_content_sync,
        "variables": self._step_variables,
        "lab_resolve": self._step_lab_resolve,
        "ports_alloc": self._step_ports_alloc,
        "tags_sync": self._step_tags_sync,
        "lab_binding": self._step_lab_binding,
        "lab_start": self._step_lab_start,
        "lds_provision": self._step_lds_provision,
        "mark_ready": self._step_mark_ready,
    }.get(next_step.step)

    result = await handler(instance, progress)
    await self._api.update_instantiation_progress(instance.id, result)

    if result.status == "failed":
        return ReconciliationResult.requeue(f"Step {result.step} failed")
    return ReconciliationResult.requeue(f"Step {result.step} {result.status}")
```

### 5. Early Timeslot Expiry Check

Before executing any pipeline step, the reconciler checks whether the session's timeslot has expired. If expired, the session is transitioned directly to `EXPIRED` without completing remaining pipeline steps. This prevents wasted work on sessions that will immediately be torn down.

### 6. Default Pipeline Factory

For sessions that don't have custom pipeline configuration, a default factory generates the standard 9-step DAG:

```python
def default_pipeline() -> InstantiationProgress:
    return InstantiationProgress(steps=(
        StepResult(step="content_sync", requires=(), ...),
        StepResult(step="variables", requires=(), ...),
        StepResult(step="lab_resolve", requires=("content_sync",), ...),
        StepResult(step="ports_alloc", requires=("lab_resolve",), ...),
        StepResult(step="tags_sync", requires=("ports_alloc",), ...),
        StepResult(step="lab_binding", requires=("tags_sync",), ...),
        StepResult(step="lab_start", requires=("lab_binding",), ...),
        StepResult(step="lds_provision", requires=("lab_start",), ...),
        StepResult(step="mark_ready", requires=("lds_provision",), ...),
    ))
```

## Rationale

### Why a DAG (not linear ordering)?

Steps have genuine data dependencies: `tags_sync` needs the output of `ports_alloc`; `lab_binding` needs tags written; `lab_start` needs binding. However, `content_sync` and `variables` are independent DAG roots that could execute in parallel. A DAG is the natural representation of these dependencies and enables future parallelism for independent steps.

### Why one step per cycle (not run-to-completion)?

- **Crash safety**: The worst case is re-executing one step after a crash. Run-to-completion could lose work across multiple steps.
- **Fairness**: In a multi-session environment, running all 9 steps in one cycle starves other sessions. One-step-per-cycle ensures round-robin fairness.
- **Observability**: Progress updates are persisted and broadcast after each step, giving operators real-time visibility.

### Why inline methods (not a pipeline engine)?

- 9 steps is below the complexity threshold where a dedicated pipeline engine adds value.
- Inline methods keep the code discoverable — all provisioning logic lives in one class.
- If pipeline logic grows (custom per-definition pipelines, parallel execution), extraction to a dedicated `InstantiationPipeline` class is straightforward.
- Avoids introducing another framework dependency (e.g., Temporal, Prefect) for what is fundamentally a finite, bounded workflow.

### Why not a Saga pattern?

Steps don't have meaningful compensating actions. You can't "un-import" a lab or "un-allocate" ports in a way that restores the system to a clean state. The checkpoint approach acknowledges that some steps are idempotent (can be safely retried) and others require manual intervention on failure.

## Consequences

### Positive

- **Crash recovery**: Pipeline resumes from the last completed checkpoint — no wasted work or resource leaks
- **Per-step visibility**: Operators can see exactly which step failed, when, and after how many attempts
- **Retry capability**: Failed steps can be retried individually without restarting the entire pipeline
- **Metrics**: Step-level duration and failure rates enable bottleneck identification and capacity planning
- **Extensibility**: New steps can be added to the DAG by declaring prerequisites — no change to the executor logic
- **Fair scheduling**: One-step-per-cycle ensures all sessions make progress in a multi-tenant environment

### Negative

- **More reconciliation cycles**: A 9-step pipeline requires at least 9 reconciliation cycles (vs. 1 for monolithic). Each cycle incurs etcd watch → HTTP POST → MongoDB write overhead.
- **Increased complexity**: The reconciler grows with 9 step methods and DAG resolution logic. Mitigated by keeping steps as simple single-responsibility methods.
- **State size**: `InstantiationProgress` adds ~2-3KB per session to the MongoDB document. Negligible at expected scale.

### Risks

- **Stale progress**: If the CPA is unreachable when the reconciler tries to persist progress, the step result is lost and must be re-executed. Mitigated: steps are designed to be idempotent.
- **DAG cycle detection**: A misconfigured prerequisite could create a cycle, causing the pipeline to stall. Mitigated: `next_executable_step()` returns `None` if no step is executable (deadlock detection).

## Implementation Notes

### Cross-Service Changes

| Service | Changes |
|---------|---------|
| **control-plane-api** | `InstantiationProgress` VO, `UpdateInstantiationProgressCommand`, `LabletSessionInstantiationProgressUpdatedDomainEvent`, new internal API endpoints |
| **lcm-core** | `instantiation_progress` field on `LabletSessionReadModel`, `update_instantiation_progress()` on `ControlPlaneApiClient` |
| **lablet-controller** | DAG-based `_handle_instantiating()`, 9 step methods, early timeslot expiry check, default pipeline factory |
| **resource-scheduler** | Scheduler passes `allocated_ports={}` (port allocation moved to pipeline) |

### Migration

- Existing sessions with `instantiation_progress = None` are handled gracefully: sessions past `INSTANTIATING` get all-completed progress; sessions currently `INSTANTIATING` get a fresh default pipeline.
- No breaking API changes — new endpoints are additive.

## Related Documents

- [Instantiation Pipeline Implementation Plan](../../implementation/instantiation-pipeline.md)
- [ADR-032: Port Allocation as LabRecord Topology Concern](./ADR-032-port-allocation-labrecord-topology.md)
- [ADR-033: CML Node Tag Sync with Allocated Ports](./ADR-033-cml-node-tag-sync.md)
- `domain/value_objects/instantiation_progress.py` — InstantiationProgress VO (to be created)
- `domain/entities/lablet_session.py` — LabletSession aggregate
