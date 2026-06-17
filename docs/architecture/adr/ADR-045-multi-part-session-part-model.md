# ADR-045: Multi-part Session / Part Model with Selector-Resolved Content

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-06-12 |
| **Deciders** | Architecture Team |
| **Extends** | [ADR-036](./ADR-036-resource-management-abstraction-layer.md) (Resource Management Abstraction), [ADR-020](./ADR-020-session-entity-model.md) (Session Entity Model) |
| **Supersedes** | [ADR-020](./ADR-020-session-entity-model.md) (session state machine → part level), [ADR-021](./ADR-021-child-entity-architecture.md) (child entities → first-class `SessionPart`) |
| **Related ADRs** | [ADR-046](./ADR-046-host-abstraction-and-pod-host-type-split.md), [ADR-047](./ADR-047-generic-reconciliation-framework.md), [ADR-049](./ADR-049-unified-workflow-dsl.md), [ADR-018](./ADR-018-lds-integration.md) (LDS multi-part) |

---

## 1. Context

The current `LabletSession` models a **single** delivery part with one pod. Real expert
deliveries are **multi-part**:

- A **Design Expert** exam may have 3 × `COR` parts and 1 x `AoE` part.
- A **CCIE** exam runs DES (design, web-only, no pod) → DOO (deploy/operate, one pod) →
  AI-DOO (one pod, likely `cml_on_aws`).

These parts have **independent timeslots and lifecycles**, may use **different pod types**, and
must run in a **gated sequence**. The downstream LDS already supports multiple
`session_parts` (`LdsSessionInfo.session_parts: list[SessionPartInfo]`), but LCM currently
creates only one — so multi-part is blocked at the LCM model, not downstream.

We also need parts to be **reusable** across exams: the same DES or COR part definition should
be referenced by many `SessionDefinition`s without copy-paste.

## 2. Decision

### 2.1 `SessionPart` is a first-class `TimedResource`

Promote `SessionPart` to a Layer-3 `TimedResource` (ADR-036 §2.6). A `Session` owns
`0..N` `SessionPart`s, each with its own `Timeslot`, `ManagedLifecycle`, and `0..N`
`PodInstance`s. A single-part `LabletSession` is the degenerate case (one part, one pod).

```
Session ─┬─ SessionPart[order=0, gates_next=true]  ─ PodInstance?
         ├─ SessionPart[order=1, gates_next=true]  ─ PodInstance
         └─ SessionPart[order=2]                    ─ PodInstance
```

### 2.2 `SessionDefinition` declares parts; selectors resolve content

A `SessionDefinition` (the umbrella catalog entry) is identified by a **`session_type`** (a
stable definition key), **not** universally by a form-qualified name:

- **Single-part** types (`lablet`, `practicelab`) _are_ the form — addressed by the one part's
  **FQN**.
- **Multi-part** types (`expertlab`, `expertdesign`) are addressed by their **`session_type`**;
  each part selects a **separate** form by **pattern + requirements**.

It declares `session_parts: list[PartDefinition]` and a **session lifecycle**. Each
`PartDefinition`:

- carries a **selector pattern** over **form-qualified names** plus optional **`requirements`**
  (declarative filters the resolved form must satisfy), resolved **at schedule time**;
- references **0 or 1** `PodDefinition` (none for web-only / device-based parts);
- declares its own **part lifecycle** phases (`pipeline` and/or `workflow` engines);
- may **gate** the next part (`gates_next`).

| Selector pattern | Resolves to |
|---|---|
| `"Exam ** LAB"` | any exam's LAB part |
| `"Exam CCIE * * DES*"` | CCIE design part, any track/version |
| `"* CCDE * COR"` | CCDE core part |

Selector resolution happens once, at schedule time, pinning each part to a concrete
(`form_qualified_name`, version) so a session is deterministic after scheduling.

The `SessionDefinition` selectors define the compatible parts, but the scheduling may assign explicitly (e.g. Lablet session is requested for a given FQN) or may select from a pool (e.g. PracticeLab and ExpertExams) with its own constraints (e.g. minimize exposure, ensure compatibility, etc).

### 2.3 Sequencing and gating

Parts are **sequential and gated** by `order` + `gates_next`. The Session manager only sets the
next part's `desired_status` once the gating part has completed. **Eager** pods may provision
early (large `Timeslot.lead_time`) even while an earlier part is active — provisioning overlap
is allowed; _activation_ is not.

### 2.4 Content packaging and definition sources

The `SessionDefinition` — including the **session lifecycle** — lives in the **seed definition
file** (and may **inherit** the lifecycle from its `session_type`). Each part's **content and its
richer part lifecycle** live in the **PAv1 content package**, referenced and resolved per part.
There is no single monolithic bundle per session — parts are independently versioned and reusable.

### 2.5 Two lifecycle layers (asymmetric)

Both `Session` and `SessionPart` are `TimedResource`s, but their lifecycles are deliberately
asymmetric:

| Layer | Phases | Defined in | Driven by |
|---|---|---|---|
| **Session** | `pending → active → inactive` | seed definition / `session_type` | its own `Timeslot` |
| **SessionPart** | `pending → instantiating → waiting → monitoring → collecting → grading → reviewing → submitting → archiving` | PAv1 package | content-driven engine ([ADR-044](./ADR-044-content-driven-lifecycle-engine.md)) |

The session lifecycle is a **trivial timeslot projection**; the real orchestration logic lives
**between parts** and **between a part and its optional pod's phases** (e.g. a part may enter
`submitting` only once its score report is `reviewed`). A session is **consistent** only while
**≥ 1** part is in a consistent state (`status == desired_status`, not `Failed`); if all parts
fail, the session is inconsistent and escalates ([ADR-047](./ADR-047-generic-reconciliation-framework.md)).

### 2.6 Timeslot inheritance and containment

Parts **inherit** the session `Timeslot` as default bounds and are constrained by it:

- **Containment** — `part.timeslot ⊆ session.timeslot`.
- **Cumulative compatibility** — `Σ part.timeslot ≤ session.timeslot`; sequential, gated parts
  cannot collectively overrun the session window.

Both are validated at **schedule time**, before any part is provisioned.

## 3. Consequences

**Positive**

- Multi-part exams become first-class; LDS multi-part support is finally usable.
- Parts are reusable across `SessionDefinition`s via selectors.
- The single-part Lablet is unchanged behaviourally (one part, one pod).

**Negative / trade-offs**

- Scheduling gains a **selector-resolution** step (pattern → concrete content).
- The dashboard and APIs must expose a nested Session → Part → Pod tree.
- Gating logic now lives in the Session manager (ADR-047), not in a flat state machine.

**Neutral**

- No backward-compatibility layer is introduced; `LabletSession` is re-expressed as a
  single-part `Session` profile (local-only deployment, no migration window required).

## 4. Related

- [session-model.md](../solution/session-model.md) — definitions, selectors, profiles.
- [flow-session-delivery.md](../solution/flow-session-delivery.md) — multi-part delivery flow.
