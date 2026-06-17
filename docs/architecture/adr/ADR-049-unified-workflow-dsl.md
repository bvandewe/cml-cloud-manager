# ADR-049: Unified Workflow DSL for Lifecycle / Step / Task Definitions

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-06-12 |
| **Deciders** | Architecture Team |
| **Extends** | [ADR-044](./ADR-044-content-driven-lifecycle-engine.md) (Content-Driven Lifecycle Engine), [ADR-034](./ADR-034-pipeline-executor-lifecycle-handlers.md) (Pipeline Executor) |
| **Related ADRs** | [ADR-023](./ADR-023-content-sync-trigger.md) (Content Sync), [ADR-036](./ADR-036-resource-management-abstraction-layer.md) §2.5 (Pipeline/Workflow coexistence), [ADR-047](./ADR-047-generic-reconciliation-framework.md), [ADR-022](./ADR-022-cloudevent-ingestion-lablet-controller.md) |
| **Superseded (in part)** | [ADR-057](./ADR-057-content-driven-lifecycle-dsl.md) supersedes the inline `tasks:` body shape of §2.1 with the `JobDefinition` step DAG, and supplies the closed `scenarioFunction` primitive set. [ADR-058](./ADR-058-lifecycle-data-flow-and-variable-scopes.md) supplies the data-flow scopes. |

---

## 1. Context

Two consumers read the same content package (`PAv1/`) at different abstraction levels
(ADR-044 §1.2):

- **LCM (CPA / controllers)** reads **top-level orchestration** — which lifecycle phases exist,
  in what order, with which engine (`pipeline` vs `workflow`), and gating.
- **SE** reads **low-level task definitions** — the adapter calls a job actually performs
  (Collect → Evaluate → Report).

Today these are described by **different shapes** in different files (pipeline YAML with `steps`,
workflow refs, scenario/grading YAML). The same concept — "a unit of work bound to a phase" — is
expressed inconsistently, which makes content authoring error-prone and prevents a single
validator. As the resource tree generalizes (ADR-036 §2.6), **every** resource level
(`Session`, `SessionPart`, `PodInstance`, `Host`) can carry lifecycle phases, so the DSL must be
uniform across levels and across both consumers.

## 2. Decision

### 2.1 One DSL, three nested concepts

Define a single declarative DSL with a consistent shape at three levels:

| Concept | Owned/ordered by | Bound to |
|---|---|---|
| **Lifecycle** | the resource (LCM) | a `TimedResource` kind / profile |
| **Step** (phase) | LCM (ordering, gating, engine selection) | a `LifecyclePhase` |
| **Task** | SE (when `engine = workflow`) | the job's Collect/Evaluate/Report units |

```yaml
lifecycle:
  phases:
    - name: instantiate
      engine: pipeline          # native LCM steps
      steps: [worker_lab_resolve, pod_locator, ports_alloc, lds_register, mark_ready]
    - name: grade
      engine: workflow          # delegated to SE
      trigger_on_status: submitted
      workflow: { name: grade-lab, version: "0.1.0" }
      tasks:                    # read by SE, ignored by LCM
        - collect: { scenario: collect-evidence }
        - evaluate: { ruleset: rubric }
        - report: { kind: score_report }
    - name: teardown
      engine: pipeline
      steps: [archive, release_host]
```

> **Superseded body shape.** The inline `tasks:` triad above is **superseded by**
> [ADR-057](./ADR-057-content-driven-lifecycle-dsl.md): a phase's `workflow` job now references a
> **`JobDefinition`** file (`definition: name@version` → `jobs/<name>.yaml`) whose body is an
> ordered DAG of **steps**, each calling a versioned `scenarioFunction` from the closed primitive
> set. This ADR's §2.1–§2.2 framing (one document, two readers; native steps vs SE jobs) stands.

### 2.2 Layered consumption (one document, two readers)

The **same document** is ingested by both consumers on **content sync** (ADR-023):

- **LCM** reads `lifecycle.phases[].{name, engine, order, gates_next, trigger_on_status,
  steps, workflow}` to build a resource's `ManagedLifecycle` and drive reconciliation
  (ADR-047). It **ignores** `tasks`.
- **SE** reads `phases[].tasks` (and the referenced scenario/ruleset/report definitions) to
  execute a job. It **ignores** native `steps`.

Neither consumer needs the other's section; the DSL is a superset both can parse without
coupling.

### 2.3 Validation and versioning

- A **shared schema** (published from `lcm_core`) validates the DSL at sync time; an invalid
  document fails the sync (no partial ingestion). The concrete schema **location and shape** are
  defined in [ADR-057 §2.7](./ADR-057-content-driven-lifecycle-dsl.md) —
  `src/core/lcm_core/schemas/` (`lifecycle.schema.json`, `job-definition.schema.json`,
  `connector-model.schema.json`, `evaluation-ruleset.schema.json`, `process-report-spec.schema.json`),
  plus a `scenario-functions.catalog.json` generated from the SE `@scenario` registry so `uses:`
  references are validated against primitives that actually exist.
- Phases, workflows, and tasks are **versioned** (`name@version`) so content changes are
  explicit and reproducible (aligns with ADR-027 auto-increment).

### 2.4 Applies at every resource level

Because the DSL is attached to a `ManagedLifecycle`, the same shape describes a `Session`'s
phases, a `SessionPart`'s phases, and a `PodInstance`'s phases — no per-level DSL.

## 3. Consequences

**Positive**

- One authoring shape, one validator, one mental model across LCM and SE and across all
  resource levels.
- `pipeline` steps and `workflow` jobs are described uniformly (resolves ADR-036 §2.5's
  three-way lookup ambiguity into one declarative form).
- Content sync can reject malformed lifecycles before they reach runtime.

**Negative / trade-offs**

- Requires a shared schema package and a one-time conversion of existing pipeline/workflow YAML
  to the unified shape (clean cut; no dual-format support — authors supply the new shape).
- The DSL is a superset; each consumer must clearly document which keys it honours.

**Neutral**

- Existing `PipelineExecutor` (ADR-034) and SE job execution (ADR-044) are unchanged in
  mechanics — only the **ingested definition shape** is unified.

## 4. Related

- [unified-resource-management.md](../solution/unified-resource-management.md) — the LCM/SE seam.
- [generic-pattern.md](../solution/generic-pattern.md) — Collect → Evaluate → Report tasks.
- [flow-content-sync.md](../solution/flow-content-sync.md) — sync fan-out to LCM + SE.
