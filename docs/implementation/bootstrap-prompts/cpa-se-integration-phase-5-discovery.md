# Bootstrap Prompt: CPA↔SE Integration — Phase 5 DISCOVERY + Low-Level Design

> **🟦 Status: Discovery / LLD only. NO CODE in this session.**
> Phase 4 closed the content-driven lifecycle scaffolding. Phase 5 splits into **two tracks** that
> both ride on the AD-CSI-024 4-tier resolver and the AD-CSI-023 typed-fields projection.
> This bootstrap runs a **structured interview** with the operator to gather requirements,
> then produces a single **Low-Level Design** document that becomes the input to a later
> implementation-only bootstrap (`cpa-se-integration-phase-5-implementation.md`, written at session end).
>
> **Baseline (post-Phase 4):** lcm-core 325 ✓ · scenario-engine 116 ✓ · control-plane-api 1097 (+1 skip) ✓ · lablet-controller 581 (+27 skip / 0 fail) ✓.

| Attribute | Value |
|-----------|-------|
| **Sprint** | CSI-Phase5-Discovery |
| **Mode** | `lcm-senior-architect` running **interview-only** (no file edits to `src/`, no test runs) |
| **Authority** | [ADR-044 Content-Driven Lifecycle Engine](../../architecture/adr/ADR-044-content-driven-lifecycle-engine.md) (Rev 2) |
| **Plan (living doc)** | [docs/implementation/cpa-se-integration-plan.md](../cpa-se-integration-plan.md) |
| **Deliverable** | `docs/implementation/cpa-se-integration-phase-5-lld.md` (NEW — RFC-style LLD) |
| **Follow-up bootstrap** | `docs/implementation/bootstrap-prompts/cpa-se-integration-phase-5-implementation.md` (NEW — generated at end of session) |
| **Closes (G-IDs after impl)** | G-10 (collect-grade + score-report scenarios), G-15 (init-phase customization v2), G-16 (lifecycle execution observability), G-17 (templated reports for non-grading phases) |
| **Services touched** | LLD will scope: `src/scenario-engine/`, `src/control-plane-api/`, `src/core/`, `src/lablet-controller/`, `src/core/lcm_ui/`, `docs/architecture/content-format/PAv1.md` |

---

## Mode & Session bootstrap

Run as **`lcm-senior-architect`**. Discovery posture: **ask before designing, design before coding**.
First three tool calls (in order, parallelize 1+2):

```text
# 1. Recall context with focus hint targeted at the two tracks
mcp_knowledge_recall_session(
  workspace_id: "lablet-cloud-manager",
  focus_hint: "Phase 5 discovery grading reports collect evidence score report init phase customization content driven scenarios per lablet monitoring observability templated reports"
)

# 2. Set focus
mcp_knowledge_set_focus(
  workspace_id: "lablet-cloud-manager",
  name: "CPA↔SE Phase 5 DISCOVERY — collect/grade/report + init customization + monitoring (LLD only)",
  description: "Run a structured interview to gather requirements for Phase 5. Produce a single LLD doc at docs/implementation/cpa-se-integration-phase-5-lld.md that scopes (A) collect-evidence, grade, score-report scenarios; (B) per-lablet init phase customization with content-driven steps + scenarios; (C) operator monitoring + templated reports for non-grading phases. NO source code changes this session.",
  active_plan: "docs/implementation/cpa-se-integration-plan.md",
  current_phase: "Phase 5 Discovery (interview + LLD)",
  priority_files: [
    "docs/implementation/cpa-se-integration-plan.md",
    "docs/architecture/content-format/PAv1.md",
    "src/core/lcm_core/infrastructure/content_store/schemas/lifecycle.schema.json",
    "src/lablet-controller/application/services/pipeline_template_resolver.py",
    "src/lablet-controller/application/services/content_driven_template_loader.py",
    "src/scenario-engine/application/services/scenario_registry.py",
    "src/scenario-engine/application/services/dsl_executor.py",
    "src/scenario-engine/scenarios/lab_resolve_scenario.py"
  ],
  priority_components: ["GradingEngine", "ScoreReport", "EvidencePackage", "ContentDrivenTemplateLoader", "ContentDrivenScenarioRegistry", "LifecycleExecutionMonitor", "ReportTemplateRenderer"]
)

# 3. List existing decisions so the interview does not contradict prior commitments
mcp_knowledge_list_decisions(workspace_id: "lablet-cloud-manager", limit: 30)
```

**Hard rules for this session:**

1. **No file edits to `src/`**, no test runs, no Docker stack changes. Only writes allowed: the LLD doc + the implementation-bootstrap doc at session end.
2. **One question batch per turn**, max 5 questions per batch (mix `multiSelect` + freeform). Use the `vscode_askQuestions` tool exclusively.
3. **Capture answers verbatim** in the LLD doc as soon as a section's questions are answered — do not paraphrase the operator's intent.
4. **Default-recommendation pattern**: every question MUST present a recommended option marked `recommended: true` so the operator can fast-track by accepting. Recommendations come from existing code (`_TEMPLATES` step names, ADR-044, AD-CSI-024) — cite the source.
5. **If a question reveals new architectural friction, STOP and add it to the LLD's "Open issues" section**; do not invent answers.

---

## Discovery scope — two tracks

### Track A — Grading & reports (closes G-10)

The placeholder hardcoded templates `standard-collect-evidence` (4 steps) and `standard-compute-grading`
(3 steps) live in `pipeline_template_resolver.py` (lines 155–222) but **none of the step handlers exist
yet**: `capture_configs`, `capture_screenshots`, `export_pcaps`, `package_evidence`, `load_rubric`,
`evaluate`, `record_score`. No SE scenario exists for `collect_grade@v1` or `score_report@v1`.
There is no `EvidencePackage` aggregate, no `ScoreReport` aggregate, no report template engine.

### Track B — Init phase strengthening + observability (closes G-15 / G-16 / G-17)

AD-CSI-024 4-tier resolver works for any phase name including `instantiate` / `teardown`, but:

- **Per-lablet step authoring** today is limited to operators (`extends`, `insert_after`, `insert_before`,
  `overrides`, `remove`) layered over hardcoded bases. Content authors cannot add **new** custom step
  handlers or **new** scenarios shipped inside the PAv1 zip — they can only re-arrange handlers
  registered in lablet-controller code.
- **Operator observability** of a running pipeline is currently scattered across CPA's
  `pipeline_progress` field, SE's `Job` aggregate, and `LifecyclePhaseHandler`'s in-process registry.
  No single UI surface, no per-step timeline, no SLA dashboard.
- **Templated reports** exist only as a placeholder for `compute-grading` → `score_report`. There is no
  equivalent for `instantiate` (provisioning report: ports allocated, devices started, time to ready)
  or `teardown` (de-provisioning report: artefacts archived, resources released).

---

## Deliverable — the LLD doc

Produce `docs/implementation/cpa-se-integration-phase-5-lld.md` with this fixed table of contents
(do not add or rename sections; leave empty sections marked `TBD — to be answered in next discovery turn`):

```
# Phase 5 Low-Level Design — Grading, Reports, Init Customization, Observability

0. Document control (status, authority, related ADRs/AD-CSI codes, contributors)
1. Executive summary (≤ 200 words)
2. Scope tracks
   2.1 Track A — Collect / Grade / Score Report
   2.2 Track B — Init customization v2 + monitoring + templated non-grading reports
3. Domain model (per track)
   3.1 Aggregates (EvidencePackage, ScoreReport, ReportTemplate, ScenarioRegistration)
   3.2 Value objects + invariants
   3.3 Domain events
   3.4 Repository contracts
4. Content format (PAv1) extensions
   4.1 lifecycle.yaml — already shipped; deltas if any
   4.2 grading.yaml — rubric schema (NEW)
   4.3 reports.yaml — report template manifest (NEW)
   4.4 scenarios/ folder — content-shipped jq scenarios (NEW; supersedes Q-04)
   4.5 step_handlers/ folder — content-shipped Python step handlers (NEW; sandbox policy?)
   4.6 JSON Schema files vendored under lcm_core/infrastructure/content_store/schemas/
5. Scenario Engine deltas
   5.1 New built-in scenarios (collect_grade@v1, score_report@v1)
   5.2 ScenarioRegistry: content-driven registration alongside @scenario decorator
   5.3 GradingEngine integration (jq DSL extension? new adapter?)
   5.4 ReportRenderer adapter (Jinja2? markdown-it? PDF backend?)
6. Control-Plane API deltas
   6.1 New aggregates / read models (EvidencePackageReadModel, ScoreReportReadModel, ReportArtefactReadModel)
   6.2 New CloudEvent integration events + handlers (additive to AD-CSI-021 ingest pipeline)
   6.3 New REST endpoints (grading rubric query, report download, pipeline execution timeline)
   6.4 Mongo collections + indexes
7. Lablet Controller deltas
   7.1 New Tier-B step handlers (collect_grade_step, score_report_step, render_report_step)
   7.2 New Tier-A step handlers (per Track B deltas)
   7.3 ContentDrivenScenarioRegistry (Track B — loads scenarios from PAv1 zip into SE at sync time)
   7.4 Lifecycle execution monitor service (Track B — periodic dashboard refresh)
8. UI deltas (lcm-ui in lcm-core)
   8.1 Pipeline execution timeline view
   8.2 Score report viewer
   8.3 Report template manager / preview
   8.4 SSE event stream extensions
9. Security & permissions
   9.1 Content-shipped step handler sandbox (Track B-1.5 — Python execution risk)
   9.2 Report PII scrubbing
   9.3 Grading rubric integrity (signed manifests?)
10. Operability
   10.1 Metrics (Prometheus) — per scenario, per step, per report template
   10.2 Logs (structured) — correlation IDs across CPA / SE / lablet-controller
   10.3 Tracing (OTEL) — span hierarchy
   10.4 Operator runbook entries
11. Migration & rollout
   11.1 Feature flags
   11.2 Backward-compat with existing _TEMPLATES["standard-collect-evidence"] + ["standard-compute-grading"]
   11.3 Seed migration plan (deferred to Mosaic per Step 12 Phase 4)
12. Open issues (parked questions that surfaced during interview)
13. New decision codes proposed (AD-CSI-026 → AD-CSI-0NN)
14. New open questions (Q-15 → Q-NN)
15. Implementation phasing
   15.1 Sprint plan (which sub-track ships first, why)
   15.2 Test plan (unit / integration / E2E)
   15.3 Definition of Done per sub-track
16. Appendix A — Glossary (rubric, score report, evidence package, report template, scenario registration)
17. Appendix B — Worked example: full PAv1 zip for an exam-style lablet (lifecycle.yaml + grading.yaml + reports.yaml + scenarios/*.yaml)
```

---

## Interview script — sequencing & question batches

Run interview phases **strictly in order**. Each phase consists of one or more question batches.
After each batch, **immediately** write the answers into the corresponding LLD section and confirm
the captured text with the operator before moving to the next batch.

### Interview Phase A1 — Evidence collection (LLD §3.1, §4 partial, §5.1, §7.1)

**Batch A1.1 — Evidence shape**

1. **What artefacts must a `collect-evidence` run produce?** Multi-select.
   - `device-running-config` (text dump) — recommended (from hardcoded step `capture_configs`)
   - `device-startup-config`
   - `vnc-screenshots` (PNG per node) — recommended (from `capture_screenshots`)
   - `pcap` files per bridge — recommended (from `export_pcaps`)
   - `interface-counters` snapshot (JSON)
   - `routing-table` snapshot (JSON)
   - `cli-transcript` (interactive session log)
   - Other (freeform)
2. **Per-artefact retention policy:** single TTL for the whole package, or per-artefact? Recommended: **single TTL on the `EvidencePackage` aggregate**, default 90 days, configurable per LabletDefinition.
3. **Storage backend:** RustFS (existing content-store), S3 directly, or a new dedicated bucket? Recommended: **RustFS under `evidence/{session_id}/{run_id}/`** to reuse `ContentSyncService` patterns.
4. **Package format:** single zip vs tar.gz vs uncompressed prefix? Recommended: **zip** (matches PAv1 tooling).
5. **PII / sensitive data**: do device configs contain credentials that need scrubbing before packaging?

**Batch A1.2 — Collection mechanics**

1. **Source for device configs**: CML REST API `GET /labs/{id}/nodes/{node_id}/config`, NETCONF, or per-device CLI? Recommended: **CML REST first; fall back to RADkit CLI adapter** (consistent with AD-CSI-008 Tier-B).
2. **Concurrency**: collect all device configs in parallel or sequential? Recommended: **parallel up to `Settings.collect_evidence_max_parallel` (default 8)** to bound CML API load.
3. **Failure semantics**: partial collection (some devices unreachable) → succeed with degraded package, or fail the whole step?
4. **Idempotency**: re-running `collect-evidence` on a session — overwrite, version, or fail-if-exists?
5. **Trigger**: explicit operator action only, or also automatic on transitions (e.g. on grade, on terminate)?

### Interview Phase A2 — Grading (LLD §3.1, §4.2, §5.1, §5.3, §7.1)

**Batch A2.1 — Rubric format**

1. **Rubric authoring format**: keep existing `grade.xml` (today's seed), or introduce **`PAv1/grading.yaml`** with explicit JSON Schema? Recommended: **YAML + schema** for consistency with `lifecycle.yaml` (AD-CSI-025).
2. **Rubric primitive checks**: which check types must v1 support? Multi-select.
   - `device-config-regex` (string match in running-config) — recommended
   - `device-config-jq` (jq expression over parsed structured config)
   - `interface-state` (up/down, counters > threshold)
   - `connectivity` (ping/traceroute between named devices)
   - `routing-presence` (specific route in table)
   - `pcap-flow` (packet match in captured pcap)
   - `script-result` (arbitrary Python predicate — security implications)
   - Other (freeform)
3. **Weighting model**: flat sum / weighted sum / categorical (pass-fail per category) / rubric-defined custom function?
4. **Partial credit**: per-check granularity (0.0–1.0), or strict pass-fail per check?
5. **Pass threshold**: per-rubric or platform-wide default?

**Batch A2.2 — Grading engine**

1. **Execution location**: SE scenario `score_report@v1` (recommended, AD-CSI-008 Tier-B fit) or in-process lablet-controller step?
2. **Determinism**: hard-block on LLM/non-deterministic dependencies, or allow with an explicit `non_deterministic: true` rubric flag?
3. **Re-grading**: when content author publishes a new rubric version, do existing graded sessions auto-re-grade, queue for manual trigger, or stay frozen?
4. **Adapter strategy**: extend the `cml` adapter with new check primitives, or introduce a dedicated `grading` adapter? Recommended: **new `grading` adapter** to keep CML adapter focused on device ops.
5. **Output**: `ScoreReport` aggregate carries (score, max_score, per-check breakdown, rubric version, evidence package ref, graded_at, grader_identity). Anything missing?

### Interview Phase A3 — Score reports (LLD §3.1, §4.3, §5.4, §6.3, §8.2)

**Batch A3.1 — Report output**

1. **Output formats**: which must ship in v1? Multi-select.
   - `JSON` (machine-readable) — recommended
   - `PDF` (printable)
   - `HTML` (interactive)
   - `Markdown` (operator-friendly)
2. **Templating engine**: Jinja2 (recommended — Python-native, well-known), Handlebars (JS, would require Node sidecar), or custom?
3. **Template authoring location**: shipped per-LabletDefinition in PAv1 zip (`reports/score-report.html.j2`), or platform-shared with `report_template_id` reference? Recommended: **per-LabletDefinition in PAv1**, with a fallback to platform default.
4. **PDF backend** (if PDF selected): WeasyPrint (Python, recommended), wkhtmltopdf, or headless Chromium?
5. **Distribution**: where do reports land? Multi-select.
   - Stored in RustFS for download — recommended
   - Emailed to a configured recipient (SMTP integration TBD)
   - POSTed to a webhook
   - Surfaced in UI only

**Batch A3.2 — Report content & access**

1. **Sections in a default score report**: candidate / lablet name / score / per-check breakdown / evidence links / start/end timestamps / grader identity / rubric version. Anything to add/remove?
2. **PII visibility**: full transcript visible to candidate, or redacted view by default with full view for admin only?
3. **Versioning**: multiple report renders per session (e.g. preview during exam vs final) or single canonical?
4. **Access control**: which Keycloak role(s) can read a `ScoreReport`?
5. **Audit trail**: log every report-render event with operator identity?

### Interview Phase B1 — Init phase customization v2 (LLD §3.4, §4.4, §4.5, §5.2, §7.3)

**Batch B1.1 — Content-shipped scenarios**

1. **Should PAv1 zips be able to ship custom SE scenarios** (e.g. `PAv1/scenarios/custom-radkit-bootstrap.v1.yaml`)? Recommended: **YES** — closes Q-04 (additive to Python @scenario registry, content wins on name+version collision with warning log).
2. **Scenario format**: jq DSL only (today's SE format), or also pure-Python with sandboxing? Recommended: **jq DSL only in v1** (sandboxing Python is high-risk; defer to v2).
3. **Registration mechanism**: SE pulls scenarios at content-sync time (recommended — extends `SyncContentCommand`), or lablet-controller pushes scenarios into SE at PipelineContext build time?
4. **Versioning**: content scenario `name@version` immutable once READY, superseded on content_hash bump? Recommended: **same supersession rules as PodDefinition** (AD-CSI-011).
5. **Conflict resolution**: when content scenario `lab_resolve@v1` collides with built-in `lab_resolve@v1` — content wins (recommended, with warning log) or refuse to load?

**Batch B1.2 — Content-shipped step handlers (Track B-1.5 — HIGH RISK)**

1. **Should PAv1 zips be able to ship custom Python step handlers**? Recommended: **NO in v1** — the security surface (arbitrary Python execution inside lablet-controller) is too large for a first cut. Force-fit custom logic into content-shipped SE scenarios (jq DSL) instead.
2. **If deferred**: document in §9.1 as "future work behind hardened sandbox (PyOdide / RestrictedPython / separate worker process)".

**Batch B1.3 — Per-lablet init steps via operators**

1. **Common init customizations operators want today**: insert a pre-`lab_resolve` step (custom CML license check), insert a post-`mark_ready` step (notification webhook), override `tags_sync` retry policy. Multi-select + freeform.
2. **Are the existing operators (`insert_after`, `insert_before`, `overrides`, `remove`, `extends`) sufficient**, or do we need new ones like `replace_steps_between(a, b)` or `wrap_step(name, before, after)`?
3. **Validation**: should the resolver dry-run the assembled pipeline at content-sync time and reject content that produces a cyclic or unreachable DAG? Recommended: **YES** (catches authoring errors before runtime).

### Interview Phase B2 — Operator monitoring & observability (LLD §8.1, §10)

**Batch B2.1 — Operator UX**

1. **Primary monitoring surface**: extend existing CPA `/api/sessions/{id}` UI page with a per-step timeline, or build a dedicated `/api/lifecycle-runs` dashboard? Recommended: **dedicated dashboard** (timeline ≠ session detail; reusable across phases).
2. **Per-step display**: status badges (pending/running/suspended/done/failed), elapsed time, last-progress timestamp, retry count, external_job_id link to SE. Anything missing?
3. **Failure UX**: on step failure, surface raw error / stack trace / both in UI? Recommended: **error message + collapsible stack trace** (audit-friendly).
4. **Refresh model**: SSE push (recommended — already used by `application/services/sse_event_relay.py`), polling, or both?
5. **Filtering / search**: by lablet name, by phase, by status, by date range, by grader? Multi-select.

**Batch B2.2 — Metrics & alerts**

1. **Metric inventory**: per-scenario duration histogram, per-step retry counter, per-phase success rate, suspended-step age gauge, content-driven-template-loader hit ratio (insight from AD-CSI-024). Anything to add?
2. **SLOs**: target p95 for `instantiate` end-to-end? Target success rate for `collect-evidence`?
3. **Alerts**: should the watchdog (AD-CSI-018) emit Prometheus alerts when a step is killed for timeout, or just log?
4. **OTEL tracing**: extend existing CQRS instrumentation (`cqrs_instrumentation.py`) to span SE Job lifecycle — keep within lablet-controller's trace tree, or pass `traceparent` to SE and stitch?

### Interview Phase B3 — Templated reports for non-grading phases (LLD §3.1, §4.3, §5.4)

**Batch B3.1 — Init/teardown reports**

1. **Should `instantiate` phase emit an "Instantiation Report"** (ports allocated, devices booted, time to ready, warnings)? Recommended: **YES** — operators currently dig through logs to reconstruct.
2. **Should `teardown` phase emit a "Teardown Report"** (artefacts archived, resources released, costs accrued)? Recommended: **YES**.
3. **Common template engine across all reports**: reuse the Track A `ReportRenderer` (Jinja2 + PDF backend)? Recommended: **YES** — one abstraction.
4. **Template authoring location**: shipped in PAv1 zip (`reports/instantiate-report.html.j2` / `reports/teardown-report.html.j2`), with platform fallback. Same model as Track A.
5. **Automatic vs on-demand**: render init report automatically when phase reaches `ready`, render teardown report automatically when phase reaches `archived`? Recommended: **automatic, with explicit suppression flag** in `LabletDefinition.report_config`.

### Interview Phase C — Cross-cutting (LLD §11)

**Batch C.1 — Migration & flags**

1. **Feature flag strategy**: one mega-flag `PHASE_5_ENABLED`, or per-sub-track (`COLLECT_EVIDENCE_ENABLED`, `GRADING_ENABLED`, `REPORTS_ENABLED`, `CONTENT_SCENARIOS_ENABLED`)? Recommended: **per-sub-track** (Phase 4 lesson: one flag = all-or-nothing rollback risk).
2. **Backward compat with `standard-collect-evidence` + `standard-compute-grading` hardcoded templates**: keep as Tier 4 fallback (like Phase 4 did for instantiate/teardown), or delete now? Recommended: **keep as fallback** until canonical-seed migration completes externally (mirrors Step 12 deferral).
3. **Existing data**: any production sessions with `grade.xml` rubrics that need migration to `grading.yaml`? Operator confirmed in Phase 4 Q-12 that local Docker is the only deployment — likely **no migration needed**.

**Batch C.2 — Sequencing & sprint plan**

1. **Which sub-track ships first?** Recommended order:
   - **Sprint 5a** — Track A1 (collect-evidence) + Track A3 (report scaffolding without grading) — gives operators an evidence package they can download.
   - **Sprint 5b** — Track A2 (grading) — depends on 5a.
   - **Sprint 5c** — Track B3 (init/teardown reports) — reuses 5a's renderer.
   - **Sprint 5d** — Track B1 (content-shipped scenarios) — independent, can parallelize with any of 5a/5b/5c.
   - **Sprint 5e** — Track B2 (monitoring dashboard) — last, benefits from 5a-d producing realistic data.
2. **Hard external dependencies** that gate any sub-track (e.g. RustFS storage capacity, Keycloak role provisioning)?

---

## Session execution rules

1. **Open the LLD doc skeleton on the first turn** with the full TOC and all 17 sections marked `TBD`. Use the markdown skeleton above verbatim. Save to `docs/implementation/cpa-se-integration-phase-5-lld.md`.
2. **For each interview phase**: ask the batch, write captured answers under the right LLD section, then proceed.
3. **After every batch is captured**, run a sanity check: read the just-written LLD section back to the operator in one sentence ("Captured: ‹summary›. OK to proceed?"). If the operator corrects, edit in place before moving on.
4. **Park ambiguities** in LLD §12 ("Open issues") with a numbered marker (`OI-1`, `OI-2`, …). Do not block the interview to resolve.
5. **At the end of Phase C**: synthesize the LLD §13 (new AD-CSI codes proposed, ≥ AD-CSI-026), §14 (new Q-IDs proposed, ≥ Q-15), §15 (implementation phasing) without re-interviewing — these are syntheses of prior answers.
6. **Final deliverable** — write `docs/implementation/bootstrap-prompts/cpa-se-integration-phase-5-implementation.md` referencing the now-complete LLD as authority, with steps mirroring the Phase 4 bootstrap structure (one step per LLD section / sub-track). This file is the **next session's** input.
7. **KM updates at session end**: `store_decision` for any ADs that became unambiguous mid-interview (do not preemptively store — wait until §13 synthesis); `store_insight` for any operator preference that's not a decision (e.g. "operator prefers per-sub-track flags"); `update_task` for the 5 sub-track sprint plan from C.2; `add_file_context` for the LLD doc + implementation bootstrap doc. Do NOT call `end_session` — wait for operator.

---

## Anti-patterns to avoid in this session

- ❌ **Don't write any code in `src/`** — even tiny scaffolds. This is discovery only.
- ❌ **Don't pre-commit to an AD-CSI code in the LLD before §13 synthesis** — codes get assigned at synthesis time to avoid the Phase 4 numbering collision (insight stored 2026-06-09).
- ❌ **Don't skip questions because "the recommendation is obvious"** — every recommendation is a hypothesis; the operator's confirmation is the requirement.
- ❌ **Don't merge tracks A and B in the LLD** — keep §3 / §5 / §6 / §7 / §10 split by track so the implementation bootstrap can sequence them independently.
- ❌ **Don't propose new aggregates without checking existing AD-CSI-007** — CPA owns the read model; SE owns the business aggregate. New aggregates must declare which side owns the write.

---

## Definition of Done — Discovery session

- [ ] `docs/implementation/cpa-se-integration-phase-5-lld.md` exists with all 17 sections filled (or explicitly marked `TBD — operator deferred decision to Sprint Nn`).
- [ ] All 5 interview phases (A1, A2, A3, B1, B2, B3, C) completed; every batch's answers captured verbatim.
- [ ] §12 "Open issues" lists every `OI-N` parked during interview with proposed resolution path.
- [ ] §13 lists proposed AD-CSI codes (no collisions with plan §7 — verified by `grep AD-CSI- docs/implementation/cpa-se-integration-plan.md | sort -u`).
- [ ] §14 lists proposed Q-N codes (no collisions with plan §8).
- [ ] §15 sprint plan sequences 5a → 5e with explicit dependencies.
- [ ] `docs/implementation/bootstrap-prompts/cpa-se-integration-phase-5-implementation.md` exists, ready to feed the next session.
- [ ] KM updated: focus refreshed, ≥ 1 insight stored, ≥ 1 file context for the LLD, ≥ 5 tasks for the sub-track sprint plan. NO premature decision storage.
- [ ] CHANGELOG `Unreleased` has a one-line "Discovery: Phase 5 LLD published" entry under a new `## Documentation` block.
- [ ] Operator says "ready for Phase 5 implementation".

---

## Notes for the agent running this session

- **Phase 4 reuse**: the AD-CSI-024 4-tier chain already supports any phase name in `_TEMPLATES`. Track A's `collect-evidence` / `compute-grading` get content-driven authoring **for free** — no resolver change needed, only new step handlers + scenarios. Highlight this in the LLD §2.1 to scope correctly.
- **AD-CSI-023 typed projection** already plumbs `lifecycle_phases` + `scenarios` end-to-end. Track B1 (content-shipped scenarios) extends the **same** pipeline by adding a `scenarios` registration step inside `SyncContentCommandHandler` that pushes them into `ScenarioRegistry` at sync time. The LLD §5.2 should call this out.
- **Existing placeholder step names** in `_TEMPLATES["standard-collect-evidence"]` and `["standard-compute-grading"]` (lines 155–222 of `pipeline_template_resolver.py`) are the **default recommendations** for the interview — they encode the prior architectural intent.
- **Bootstrap chaining**: the implementation bootstrap you produce at session end MUST follow the same shape as `cpa-se-integration-phase-4.md`: numbered steps (`## Step 1` … `## Step N`), each with Definition of Done bullets, each touching specific files. The LLD §15 sprint plan maps 1:1 to step ranges (Sprint 5a = Steps 1–5, Sprint 5b = Steps 6–9, etc.).
- **If the operator asks "what would you decide?"**: answer concretely with the recommendation + rationale, then ask them to confirm or reject. Do not refuse to opine — they are explicitly delegating that call.

---

**Ready to start?** First turn: run the 3 KM bootstrap calls in parallel, then open the LLD skeleton, then ask Batch A1.1.
