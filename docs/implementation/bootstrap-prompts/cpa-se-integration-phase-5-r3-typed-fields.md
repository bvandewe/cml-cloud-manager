# Bootstrap Prompt: Phase 5 — R-3 Typed-Fields Projection Contract (Parallel Track)

> **🟦 Status: Discovery + LLD-only mini-batch. NO CODE in `src/` in this session.**
> Spawned from the Phase 5 LLD review (`docs/implementation/cpa-se-integration-phase-5-lld.md`)
> to close architectural risk **R-3**: define how the **new PAv1 content surfaces**
> (`grading.yaml`, `reports.yaml`, content-shipped `scenarios/`, content-shipped
> `step_handlers/`) project into CPA's `PodDefinitionReadModel` as **typed fields**, the
> same way **AD-CSI-023** projected `lifecycle_phases` + `scenarios`.
>
> This batch runs **in parallel** with the main Phase 5 Phase B interview so that B2.1
> (operator dashboard) is not blocked waiting for read-model field shapes.

| Attribute | Value |
|-----------|-------|
| **Sprint** | CSI-Phase5-R3-TypedFields |
| **Mode** | `lcm-senior-architect` running **interview-only** (no `src/` edits, no test runs) |
| **Authority** | [AD-CSI-023 typed-fields projection](../cpa-se-integration-plan.md) + [Phase 5 LLD](../cpa-se-integration-phase-5-lld.md) |
| **Parent doc** | `docs/implementation/cpa-se-integration-phase-5-lld.md` §6.1 / §6.2 |
| **Deliverable** | An **append** to the Phase 5 LLD (§6.1 + §6.2 + a new §6.5 "Typed-fields projection contract"), AND a new decision proposal (`AD-CSI-NN — Phase 5 content-surface typed projection`) recorded via `mcp_knowledge_store_decision`. NO new top-level markdown doc. |
| **Out of scope** | Any new SE → CPA CloudEvent type. This batch reuses the existing AD-CSI-022 `pod_definition.ready.v1` (additive fields only) and possibly the AD-CSI-021 `content.synced.v1` envelope. |
| **Blocks** | LLD §6.1 (CPA read models), §6.2 (CPA ingest handlers), §6.4 (Mongo indexes), §8.1 (operator dashboard data shape), B2.1 batch |
| **Does NOT block** | Sprint 5a (A1 collect-evidence) — the new typed fields are optional/nullable and back-compat by default |

---

## Mode & Session bootstrap

Run as **`lcm-senior-architect`**. Discovery posture: **ask before designing, design before coding**.
First four tool calls (parallelize 1+2+3):

```text
# 1. Recall context targeted at typed-fields + Phase 4 history
mcp_knowledge_recall_session(
  workspace_id: "lablet-cloud-manager",
  focus_hint: "AD-CSI-023 typed fields projection PodDefinitionReadModel lifecycle_phases scenarios CloudEvent ingest additive grading.yaml reports.yaml read model"
)

# 2. Set focus
mcp_knowledge_set_focus(
  workspace_id: "lablet-cloud-manager",
  name: "Phase 5 R-3 — typed-fields projection contract for grading/reports/scenarios/step_handlers",
  description: "Decide which fields from grading.yaml + reports.yaml + content-shipped scenarios/ + step_handlers/ are projected onto PodDefinitionReadModel as first-class typed fields (analogue of AD-CSI-023). Define the additive CloudEvent payload shape, the projection handler diff, the Mongo persistence shape, and the safe-default round-trip contract. Output is an append to the Phase 5 LLD §6.1/§6.2/§6.5 and a single AD-CSI-NN decision. No src/ code in this session.",
  active_plan: "docs/implementation/cpa-se-integration-phase-5-lld.md",
  current_phase: "Phase 5 R-3 (parallel mini-batch)",
  priority_files: [
    "docs/implementation/cpa-se-integration-phase-5-lld.md",
    "docs/implementation/cpa-se-integration-plan.md",
    "src/control-plane-api/domain/read_models/pod_definition_read_model.py",
    "src/control-plane-api/integration/repositories/motor_pod_definition_read_repository.py",
    "src/control-plane-api/application/events/integration/scenario_engine_pod_definition_events.py",
    "src/control-plane-api/application/events/integration/scenario_engine_pod_definition_handler.py",
    "src/control-plane-api/application/commands/pod_definition_read/project_pod_definition_ready_command.py",
    "src/scenario-engine/integration/cloud_event_client.py",
    "docs/architecture/content-format/PAv1.md"
  ],
  priority_components: ["PodDefinitionReadModel", "ScenarioEnginePodDefinitionReadyIntegrationEventV1", "ProjectPodDefinitionReadyCommand", "MotorPodDefinitionReadRepository", "ContentDrivenTemplateLoader", "CloudEventIngestor"]
)

# 3. List existing decisions (especially AD-CSI-021/022/023/024) so this batch stays additive
mcp_knowledge_list_decisions(workspace_id: "lablet-cloud-manager", limit: 30)

# 4. Read the parent LLD §6.1 / §6.2 / §4 to ground the questions in captured Phase A content
read_file(
  filePath: ".../docs/implementation/cpa-se-integration-phase-5-lld.md",
  startLine: 196,  endLine: 360
)
```

**Hard rules for this session:**

1. **No file edits to `src/`**, no test runs, no Docker stack changes. Only writes allowed:
   - **append** edits to `docs/implementation/cpa-se-integration-phase-5-lld.md` (§6.1, §6.2,
     **NEW §6.5**, and §13 to register the new AD-CSI code);
   - one `mcp_knowledge_store_decision` call;
   - up to three `mcp_knowledge_store_insight` calls.
2. **One question batch per turn**, max 5 questions per batch (mix `multiSelect` + freeform).
   Use the `vscode_askQuestions` tool exclusively.
3. **Every question presents a recommended default** marked `recommended: true`,
   grounded in **AD-CSI-023's existing implementation** (`lifecycle_phases`, `scenarios`).
   Cite the file + line from the priority_files list.
4. **Capture answers verbatim** into the LLD as soon as a batch is answered.
5. **Additive-only contract:** every new CloudEvent field MUST be optional with safe defaults
   (back-compat with legacy SE builds). Reuse the AD-CSI-021 `getattr(event, X, None)` pattern
   in the projection handler — `CloudEventIngestor` bypasses `__init__`, so dataclass defaults
   are not applied.

---

## Background — what AD-CSI-023 did (and what this batch extends)

**AD-CSI-023** added two typed fields to the read model:

| File | Change |
|---|---|
| `src/control-plane-api/domain/read_models/pod_definition_read_model.py` | `lifecycle_phases: dict[str, Any] \| None = None` + `scenarios: dict[str, Any] \| None = None` |
| `src/control-plane-api/integration/repositories/motor_pod_definition_read_repository.py` | round-trip the two fields through Mongo doc |
| `src/control-plane-api/application/events/integration/scenario_engine_pod_definition_events.py` | extend `ScenarioEnginePodDefinitionReadyIntegrationEventV1` with the two optional fields |
| `src/control-plane-api/application/events/integration/scenario_engine_pod_definition_handler.py` | forward via `getattr(event, "lifecycle_phases", None)` |
| `src/control-plane-api/application/commands/pod_definition_read/project_pod_definition_ready_command.py` | accept the two optional fields |
| `src/scenario-engine/integration/cloud_event_client.py::emit_content_synced(...)` | forward `lifecycle_phases=pod_def.lifecycle_phases, scenarios=pod_def.scenarios` |

Tests pinned all of this:

- `tests/integration/test_motor_pod_definition_read_repository.py::test_round_trip_preserves_lifecycle_phases_and_scenarios`
- `tests/application/test_project_pod_definition_read.py::test_ready_persists_lifecycle_phases_and_scenarios_when_provided`
- `tests/application/test_scenario_engine_pod_definition_handler.py::test_ready_handler_forwards_lifecycle_phases_and_scenarios`

**R-3 extends this by adding 2–4 more typed fields** — exact count is the first interview decision.

---

## Why this matters

Without an explicit typed-fields projection contract for the new PAv1 surfaces, three downstream
features stall:

1. **B2.1 operator dashboard** needs to render "pipeline N · 3 scenarios · 12 checks · 2 report
   templates" cards. The dashboard reads `PodDefinitionReadModel` — if the data isn't projected
   onto a typed field, the UI either fetches the raw PAv1 zip (slow, defeats AD-CSI-023's
   intent) or denormalises grading metadata into the dashboard service (DRY violation).
2. **A3 score-report viewer** needs the `reports.yaml` manifest at render-request time to know
   `interactive_html: true|false` and `formats: [...]`. Re-parsing PAv1 per render = 5+ network
   hops to RustFS — unacceptable for the iframe-embed UX.
3. **B1.1 ScenarioRegistration** needs to know which content-shipped scenarios are registered
   on a given LabletDefinition. If `scenarios` (already projected by AD-CSI-023) only carries
   the **inline jq scenarios** from `lifecycle.yaml`, the new `scenarios/` folder content needs
   a separate projection field — or `scenarios` needs to be unified across both sources with a
   `source: "lifecycle.yaml" | "scenarios/"` discriminator.

---

## Interview script — sequencing & question batches

Run interview phases **strictly in order**. After each batch, **immediately** append the
captured text into the LLD §6.5 (new), §6.1 (existing), §6.2 (existing) and confirm with the
operator before moving to the next batch.

### Interview Phase R3-1 — Projection field inventory (LLD §6.5)

**Batch R3-1.1 — Which content surfaces become typed fields?**

1. **Project `grading.yaml` onto a typed field?** Multi-select; for each chosen, the field
   becomes part of `PodDefinitionReadModel`.
   - `grading_rubric: dict[str, Any] | None` — full parsed grading.yaml (mirrors `lifecycle_phases` approach) — **recommended** (matches AD-CSI-023 precedent).
   - `grading_rubric_summary: { rubric_version, pass_threshold, parts_count, categories_count, checks_count } | None` — small denorm for dashboard cards (extra round-trip avoided).
   - Both (full payload + summary cache).
   - Neither — fetch from PAv1 on demand. **NOT recommended** (forces dashboard to download zip).
2. **Project `reports.yaml` onto a typed field?** Multi-select.
   - `report_manifest: dict[str, Any] | None` — full parsed reports.yaml — **recommended**.
   - `report_kinds: list[str] | None` (e.g. `["score_report", "init_report"]`) for quick UI filtering.
   - Both.
   - Neither.
3. **Project content-shipped `scenarios/` folder onto a typed field?** Multi-select.
   - **Unify with the existing `scenarios` field** (AD-CSI-023) by adding a `source` discriminator inside each entry: `{ name, body, source: "lifecycle.yaml" | "scenarios/" }` — **recommended** (no new field; preserves Phase 4 contract).
   - Add a separate `content_shipped_scenarios: dict[str, Any] | None` field — keeps the existing `scenarios` semantics untouched but adds a parallel field.
   - Track content-shipped scenarios elsewhere (e.g. `ScenarioRegistrationReadModel` only — §6.1).
4. **Project content-shipped `step_handlers/` folder onto a typed field?**
   - `content_shipped_step_handlers: list[str] | None` — names only (handler IDs) — **recommended** (full Python source belongs in the PAv1 blob, not the read model).
   - Full source bodies in the read model (NOT recommended — security review fallout + Mongo doc bloat).
   - Defer until Phase B1.2 sandbox decision is made (current LLD recommendation: defer to v2).
5. **PII consideration freeform:** does `grading.yaml` ever carry candidate PII (names, IDs, …)
   that would need scrubbing before projection into the read model? Default assumption: **no**
   (rubric is content, not session data) — confirm or correct.

**Batch R3-1.2 — Wire-format additivity**

1. **Add to existing `pod_definition.ready.v1` (AD-CSI-022) or emit a new `pod_definition.grading_ready.v1`?**
   - **Extend `pod_definition.ready.v1` additively** (matches AD-CSI-023 pattern, single ingest path) — **recommended**.
   - New event type — keeps grading payload separate; but doubles handler maintenance and ordering risk.
2. **Field defaults & `getattr()` pattern:** confirm every new field is `Optional[dict|list|str]` with default `None` so legacy SE builds + cached events stay valid.
   - Yes — apply the AD-CSI-021 `getattr(event, X, None)` pattern in the handler — **recommended**.
   - Use dataclass `field(default_factory=...)` — **rejected** (CloudEventIngestor bypasses `__init__`).
3. **Payload size cap freeform:** existing `lifecycle_phases` payload averages ~5–20 KB. New fields combined are estimated 10–50 KB more. Should we set an explicit max CloudEvent payload size and gate at SE emit time? Recommended default: `Settings.cloudevent_max_payload_bytes` = **256 KB** with WARN log when exceeded.
4. **Versioning hint:** when the SE side adds a future field, do we bump the CloudEvent `type`
   from `v1` to `v2`?
   - No — keep `v1` and rely on additive-optional contract — **recommended** (matches existing pattern).
   - Yes — version per breaking shape change only; new optional fields stay on `v1`.
5. **Content-hash inclusion freeform:** should each projected typed field carry a parallel
   `*_content_hash` (e.g. `grading_rubric_content_hash: str | None`) so the dashboard can show
   "rubric v1.0.0 (sha 3f7a…)" and detect drift? Default: **yes** — cheap field, big audit
   value.

### Interview Phase R3-2 — Mongo persistence + indexes (LLD §6.1 + §6.4)

**Batch R3-2.1 — Persistence shape & indexes**

1. **Store new fields as nested BSON documents on `PodDefinitionReadModel.doc`, or in
   sub-collections?** Recommended: **nested on the same doc** (matches AD-CSI-023; supports
   `findOne` with single round-trip).
2. **New indexes required for B2.1 dashboard queries?** Multi-select.
   - `(grading_rubric.rubric_version, content_hash)` — for "which pods use rubric vN" cross-tenant queries — **recommended**.
   - `report_manifest.reports.kind` — for "find all pods with init_report templates" — recommended.
   - None — rely on existing `_id` + `content_hash` indexes.
3. **Read-side query DTO:** does `GetPodDefinitionQuery` return the new fields by default, or
   gate them via a `include=grading,reports` query param? Recommended: **return by default**
   (matches existing `lifecycle_phases` behaviour); add explicit `?fields=` projection later if
   payload bloat becomes a problem.
4. **Projection failure mode freeform:** if `grading.yaml` is present but malformed, does the
   pod-definition projection fail (rejecting the whole content sync) or succeed with
   `grading_rubric=None` + a `grading_parse_error: str` field? Recommended: **fail-fast at SE
   sync time** (validated against vendored JSON Schema in §4.6 of the LLD), so the CPA
   projection never sees a malformed payload.
5. **TTL / lifecycle policy:** does any of the new fields need a separate TTL (independent of
   the PodDefinition's content_hash immutability)? Recommended: **no** — fields are content-
   addressable + immutable; rely on PodDefinition's own retention.

### Interview Phase R3-3 — Handler diff + test plan (LLD §6.2)

**Batch R3-3.1 — Wire-up diff catalog**

1. **Confirm the list of files to be edited in the upcoming implementation sprint** (read-only
   confirmation; no edits in this session):
   - `pod_definition_read_model.py` — add typed fields + content-hash siblings — **recommended**.
   - `motor_pod_definition_read_repository.py` — round-trip the new fields in `_to_doc` / `_from_doc`.
   - `scenario_engine_pod_definition_events.py` — extend the dataclass additively.
   - `scenario_engine_pod_definition_handler.py` — `getattr(event, NEW_FIELD, None)` forwarding.
   - `project_pod_definition_ready_command.py` — accept new optional fields.
   - `src/scenario-engine/integration/cloud_event_client.py::emit_content_synced` — forward new fields.
2. **Mandatory test fixtures to add (read-only confirmation):**
   - `test_motor_pod_definition_read_repository.py::test_round_trip_preserves_grading_and_reports` — **recommended**.
   - `test_ready_handler_forwards_grading_and_reports` — **recommended**.
   - `test_ready_persists_grading_and_reports_when_provided` — recommended.
   - Negative-path: `test_ready_persists_no_grading_when_absent` — keeps back-compat green.
3. **Telemetry freeform:** should the projection handler emit a structured log when a new
   typed field is missing on an event payload (i.e. legacy SE build)? Default: **debug-level
   log only** (avoids noise during transition; ERROR is reserved for malformed payloads).

### Interview Phase R3-4 — Decision capture

**Batch R3-4.1 — Decision text confirmation**

1. **AD-CSI-NN proposed text — operator review:** the agent presents a one-screen markdown
   block with:
   - **Title:** "Phase 5 content-surface typed projection (additive AD-CSI-023 extension)"
   - **Decision:** project `<final field list from R3-1.1>` onto `PodDefinitionReadModel`,
     forward through `pod_definition.ready.v1`, back-compat via `getattr()`.
   - **Rationale:** dashboard latency + DRY + AD-CSI-023 precedent.
   - **Related:** AD-CSI-021, AD-CSI-022, AD-CSI-023, AD-CSI-024.
   - **Impacts:** §6.1, §6.2, §6.4 of LLD; B2.1 batch unblocked.
   - **Risks:** Mongo doc size growth; mitigated by `Settings.cloudevent_max_payload_bytes`.
   - Operator approves verbatim, edits inline, or rejects (loop back to R3-1.1).

Once approved, call:

```text
mcp_knowledge_store_decision(
  workspace_id: "lablet-cloud-manager",
  code: "AD-CSI-NN",  # NN = next available (verify via grep on cpa-se-integration-plan.md)
  title: "Phase 5 content-surface typed projection (additive AD-CSI-023 extension)",
  decision: "<verbatim from approved block>",
  rationale: "<verbatim>",
  related_components: ["PodDefinitionReadModel", "ScenarioEnginePodDefinitionReadyIntegrationEventV1", "ProjectPodDefinitionReadyCommand", "MotorPodDefinitionReadRepository"],
  related_files: ["docs/implementation/cpa-se-integration-phase-5-lld.md"]
)
```

---

## Session-end deliverables

Before calling `mcp_knowledge_end_session`, the agent MUST have:

1. ✅ Appended captured content to LLD §6.1, §6.2, **NEW §6.5 "Typed-fields projection contract"**.
2. ✅ Registered the new AD-CSI-NN code in LLD §13 (one-line entry pointing to §6.5).
3. ✅ Resolved R-3 in the parent LLD's risk register (add `🟢 RESOLVED (R3 mini-batch, <date>)`
   next to R-3 wherever it appears).
4. ✅ Stored exactly one `mcp_knowledge_store_decision` (AD-CSI-NN).
5. ✅ Stored 1–3 `mcp_knowledge_store_insight` entries (e.g. "additive optional-field pattern
   for CloudEvent ingest", "Mongo BSON doc-size budget for PodDefinition projection").
6. ✅ CHANGELOG entry under "Unreleased" summarising the projection contract decision.
7. ❌ NO `src/` edits, NO test runs, NO Docker changes.

When the operator says "end session", call `mcp_knowledge_end_session` with summary:

> "Phase 5 R-3 closed. Defined N typed projection fields for grading/reports/scenarios/
> step_handlers as additive extensions to `pod_definition.ready.v1` (AD-CSI-NN). Implementation
> queued for Sprint 5a (parallel-safe with collect-evidence work)."

---

## Cross-reference quick table

| Concept | Location |
|---|---|
| AD-CSI-023 typed-fields implementation | `src/control-plane-api/domain/read_models/pod_definition_read_model.py` (line ~65) |
| AD-CSI-023 round-trip test | `tests/integration/test_motor_pod_definition_read_repository.py::test_round_trip_preserves_lifecycle_phases_and_scenarios` |
| AD-CSI-021 ingest-bypass-init gotcha | `bootstrap-prompts/cpa-se-integration-phase-4.md` line 262 (`getattr` pattern) |
| Phase 5 LLD parent | `docs/implementation/cpa-se-integration-phase-5-lld.md` |
| Risk R-3 source | LLD review session, 2026-06-09, recorded in conversation summary |
