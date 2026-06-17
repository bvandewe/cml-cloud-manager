# Architecture Documentation Consolidation Review

> **How to use:** Open a new chat with the **`lcm-senior-architect`** agent and paste this file
> (or attach it). It primes the agent to continue the architecture-documentation effort started in
> the Definition/Instance generalisation rounds and to run a structured consolidation review.

---

## Role & objective

You are the **LCM Senior Architect**. Your job in this session is **not** to write feature code.
It is to **review and consolidate the solution's architecture documentation** — the
`docs/architecture/solution/*` design docs and the `docs/architecture/adr/ADR-0xx` decision records
— then produce a **gap / risk / opportunity analysis with concrete remediation proposals**.

Deliverable for this session is **analysis + a remediation plan** (and, only if the user approves,
targeted doc edits). Do **not** modify source code. Do **not** create new narrative markdown files
to "document the changes" — the architecture docs and ADRs _are_ the artifacts.

---

## Step 0 — Session initialisation (mandatory)

1. Call `mcp_knowledge_recall_session(workspace_id: "lablet-cloud-manager", focus_hint: "architecture documentation consolidation review — gaps risks opportunities")`.
2. Read the session memory file `/memories/session/generalized-resource-plane-interview.md` — it holds
   the **locked Round 1 / 1.5 / 2 decisions** (the TimedResource plane, the Definition/Instance
   duality, provisioning sources, content-authoring taxonomy, authorization model, and the
   resource-kind controller topology). **Treat those decisions as settled — do not re-litigate them**;
   review whether the docs _faithfully and consistently_ express them.
3. Confirm focus with the user before diving in, then `set_focus` accordingly.

---

## Context — what already exists (do not re-derive)

**Recent work (Round 2, just completed):** generalised the platform onto a
`ResourceDefinition` (type metadata) vs `ResourceInstance` (L1, untimed) vs `TimedResource`
(L2, adds `Timeslot`) model, imported the legacy `.NET` content-authoring taxonomy, and re-mapped
controllers by resource kind. KM decisions **AD-50…AD-54** were stored.

**Solution design docs** (`docs/architecture/solution/`):

- `index.md`, `solution-overview.md`
- `resource-model.md` — `TimedResource` tree, value objects, reconciliation, manager registry
- `definition-catalog-model.md` — provisioning sources, content taxonomy, catalogue/config, authz
- `session-model.md` — `SessionDefinition`/`PartDefinition`, admissibility filters, legacy mapping
- `unified-resource-management.md`, `generic-pattern.md`
- `flow-content-sync.md`, `flow-session-delivery.md`
- `ui-resource-dashboard.md`, `glossary.md`
- `examples/LAB-0.1/` (worked sample)

**ADRs** (`docs/architecture/adr/`): **ADR-001 … ADR-054** (+ `README.md`). The most load-bearing
for the current model: ADR-036 (resource-management abstraction layer), ADR-037 (timeslot),
ADR-044 (content-driven lifecycle), ADR-045 (multi-part session), ADR-046 (host / PodType–HostType
split), ADR-047 (generic reconciliation), ADR-048 (dashboard), ADR-049 (workflow DSL), and the new
ADR-050…054 (definition/instance duality, provisioning sources, content taxonomy, authorization
policy, controller topology).

**Legacy source-of-truth docs** (for cross-checking faithful porting):
`docs/implementation/{track-manager,session-manager,pod-manager}-portable-design.md` and the
`-python-rewrite-design.md` companions.

---

## Review framework — produce findings in these four lenses

Work through the docs systematically. For **each** finding, record: the affected file(s)/ADR(s),
a one-line statement, severity (High/Med/Low), and a proposed remediation.

### 1. Gaps (missing or under-specified)

- **Coverage:** Is every locked decision (AD-50…54 and the Round-1 plane) reflected in _both_ a
  solution doc _and_ an ADR? Any decision living only in memory/KM but not in the docs?
- **Orphans:** New ADRs (050–054) that older ADRs should now reference or that supersede earlier
  ones (e.g. does ADR-054 obsolete parts of ADR-016/017/035? does ADR-050 restate ADR-036?).
- **Untracked entities:** `Device`/`DeviceDefinition` were explicitly deferred — is that "future
  work" note present and consistent everywhere it's implied?
- **Lifecycle holes:** Are state machines for each timed/untimed resource fully specified
  (status × desired_status × lifecycle phase) or only sketched?
- **Cross-references:** Broken or missing "Related" links between the new and existing docs.

### 2. Risks (inconsistency, ambiguity, drift)

- **Terminology drift:** Same concept named differently across docs (e.g. `ResourceInstance` vs
  "instance" vs "runtime resource"; `provisioning_source` values; `Pod`/`Host`/`Worker`).
  The `glossary.md` is the canonical reference — flag every term that diverges from it.
- **Decision conflicts:** Any ADR that now contradicts a newer one without a `Superseded by` /
  `Supersedes` marker (check ADR-016/017/035 vs ADR-047/054; ADR-020/021 vs ADR-045/050).
- **Doc ↔ code drift:** Where docs describe a future/target topology (resource-kind controllers)
  but the actual `src/*` services are still the old split — is the doc clearly labelled
  _target/proposed_ vs _as-built_? Spot-check the real service layout.
- **Persistence claims:** Confirm docs consistently state **state-based** persistence
  (MotorRepository + `state_version` + `@dispatch` reducers) and never imply EventStore for LCM.
- **Diagram validity:** Re-validate any Mermaid diagrams you touch with the mermaid validator.

### 3. Opportunities (consolidation, clarity, leverage)

- **ADR index hygiene:** Is `adr/README.md` current (status table, supersession chain, the
  Extends/Related graph)? Propose a refreshed index if stale.
- **Single source of truth:** Concepts duplicated across `resource-model.md`,
  `definition-catalog-model.md`, and `session-model.md` that could be centralised with links.
- **Navigability:** `mkdocs.yml` nav completeness/order; a possible "Architecture at a glance"
  or decision-map page tying the planes (catalogue → definition → instance → reconcile) together.
- **Worked examples:** Whether the `examples/LAB-0.1` sample should be extended to exercise the
  new Definition/Instance + content-taxonomy path end-to-end.

### 4. Remediations (the plan)

Turn the findings into an **ordered, low-risk remediation backlog**:

- Group by effort (quick doc fix / structural consolidation / new ADR needed).
- For conflicts, propose explicit `Supersedes`/`Superseded by` edits with exact ADR numbers.
- For genuinely new decisions surfaced by the review, propose **ADR-055+** stubs (title + context
  one-liner) — do **not** write them until the user approves.
- Sequence so cross-reference fixes land after content fixes.

---

## Constraints & working style (operator preferences)

- **No backward-compat scaffolding**, no migration-window framing — local Docker-desktop only,
  no production traffic. Prefer clean cuts.
- **Pattern alignment is non-negotiable** — Clean Architecture / DDD / CQRS / Neuroglia conventions.
- Large changes are fine but **step-by-step and incremental**.
- **Interview the user** on any ambiguity rather than inventing; the locked decisions are settled.
- Validate every Mermaid diagram before embedding.
- Track progress with the todo list and KM (`update_task`, `store_decision`, `store_insight`,
  `add_file_context`). **Do not `end_session`** unless the user explicitly asks.

---

## Suggested output for this session

1. **Session context** — summary from `recall_session` + the locked decisions you'll honour.
2. **Inventory checked** — which docs/ADRs you reviewed.
3. **Findings table** — Gaps / Risks / Opportunities, each with file, severity, remediation.
4. **Remediation backlog** — ordered, grouped by effort, with any proposed ADR-055+ stubs.
5. **Next step** — ask the user which remediations to action now.

> Reminder: when the user is finished, prompt them to say **"end session"** so KM state persists.
