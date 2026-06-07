# Bootstrap Prompt: CPA↔SE Integration — Phase 0 Foundations

> **🟢 Status: COMPLETE** — closed 2026-06-07 in commits `d5600a1` (G-04/G-08), `7d760fe` (G-03), `820dcaf` (G-07), `c081eab` (docs). All 4 gaps marked closed in the [master plan §3](../cpa-se-integration-plan.md#3-gap-catalog). New decision AD-CSI-010 stored. **Next phase**: see `cpa-se-integration-phase-1.md`.

| Attribute | Value |
|-----------|-------|
| **Sprint** | CSI-Phase0 |
| **Created** | 2026-06-07 |
| **Plan (living doc)** | [docs/implementation/cpa-se-integration-plan.md](../cpa-se-integration-plan.md) |
| **Authority** | [ADR-044 Content-Driven Lifecycle Engine](../../architecture/adr/ADR-044-content-driven-lifecycle-engine.md) |
| **Services touched** | `src/core/`, `src/scenario-engine/`, `src/control-plane-api/` |
| **Tests must pass** | `make lint && make test` in each touched service |

---

## Mode & Session

Run as **`lcm-senior-architect`** agent mode.

**First action — recall + focus:**

```text
mcp_knowledge_recall_session(
  workspace_id: "lablet-cloud-manager",
  focus_hint: "CPA SE integration Phase 0 foundations PAv1 PodDefinition PodTypeDetector"
)

mcp_knowledge_set_focus(
  workspace_id: "lablet-cloud-manager",
  name: "CPA↔SE Phase 0 Foundations",
  description: "Implement PAv1/ format spec, expand PodDefinition fields, PodTypeDetector, RecordContentSyncResultCommand pod_type acceptance",
  active_plan: "docs/implementation/cpa-se-integration-plan.md",
  current_phase: "Phase 0 — Foundations (no behaviour change)",
  priority_files: [
    "src/scenario-engine/domain/entities/pod_definition.py",
    "src/scenario-engine/domain/events/pod_definition_events.py",
    "src/core/lcm_core/infrastructure/content_store/__init__.py",
    "src/control-plane-api/application/commands/lablet_definition/record_content_sync_result_command.py",
    "docs/architecture/content-format/PAv1.md"
  ],
  priority_components: ["PodDefinition", "PodTypeDetector", "PAv1Validator", "RecordContentSyncResultCommand"]
)
```

**Pre-existing decisions** (already in Knowledge Manager — do not re-store):
`AD-CSI-001` DSL boundary · `AD-CSI-002` Pod-type priority · `AD-CSI-003` Sync handoff order · `AD-CSI-004` PodDefinition typed fields · `AD-CSI-005` Mediator-only CloudEvent handlers · `AD-CSI-006` Tier-A/B steps · `AD-CSI-007` Read-only CPA projection

---

## Objective

Land the **foundations** required by all later phases. Phase 0 ships **zero behaviour change** — only new types, new fields with safe defaults, new validators, and a new optional field on one command. Everything must be feature-flag-compatible with `SE_INTEGRATION_ENABLED=false`.

**Closes gaps:** G-03, G-04, G-07, G-08
**Read the full plan first:** [docs/implementation/cpa-se-integration-plan.md](../cpa-se-integration-plan.md) §3 (G-03/G-04/G-07/G-08), §5 (PAv1/ spec), §6 (Phase 0).

---

## Implementation Steps (in order)

### Step 1 — PAv1/ format spec doc + JSON schemas  (G-08)

**Create**

- `docs/architecture/content-format/PAv1.md` — narrative spec
  - Cover `manifest.yaml`, `topology/`, `lifecycle.yaml`, `scenarios/`, `grading/`, `reports/`, `restore/` per plan §5.2
  - Reference AD-CSI-001 (DSL boundary) and AD-CSI-002 (pod-type priority)
  - Include the canonical zip layout tree
  - Include `format_version: PAv1` requirement
- `docs/architecture/content-format/schemas/manifest.schema.json` — JSON Schema (draft-2020-12) for `manifest.yaml`
  - Required: `format_version`, `name`, `version`, `pod_type` (optional but recommended), `content_id`
  - Optional: `scenarios_used`, `lifecycle_ref`, `description`, `authors`
- `docs/architecture/content-format/schemas/lifecycle.schema.json` — phases as object keyed by phase name; each phase is a DAG of steps with `name`, `handler`, `depends_on`, `skip_when`, `retry`, `timeout`
- `docs/architecture/content-format/schemas/scenario.schema.json` — wraps the existing SE DSL (`call`/`do`/`set`/`try`); pull task-type definitions from `src/scenario-engine/application/services/dsl_executor.py` for parity

**Acceptance:** Schemas validate against `jsonschema` library; spec doc cross-links to ADR-044 and the integration plan.

---

### Step 2 — `lcm_core.infrastructure.content_store` package  (G-04, G-08)

**Create** package skeleton:

- `src/core/lcm_core/infrastructure/content_store/__init__.py` — re-exports
- `src/core/lcm_core/infrastructure/content_store/pav1_validator.py`
  - `PAv1Validator` class with `validate_manifest(data: dict) -> None` / `validate_lifecycle` / `validate_scenario`
  - Loads schemas via `importlib.resources` from the doc directory **OR** vendors them under `lcm_core/infrastructure/content_store/schemas/` (preferred — keeps runtime deps self-contained; doc copies are illustrative)
  - Raises `PAv1ValidationError(path, errors)` — define in `pav1_errors.py`
- `src/core/lcm_core/infrastructure/content_store/pod_type_detector.py`
  - `PodTypeDetector.detect(package_path: pathlib.Path) -> tuple[PodType, list[str]]`
  - Implements priority chain from plan §5.1 / AD-CSI-002
  - Works on extracted directories AND on `zipfile.ZipFile` instances (accept `Path | ZipFile`)
  - Raises `PodTypeIndeterminate(signals: list[str])` when no signal matches
- `src/core/lcm_core/infrastructure/content_store/content_extractor.py` (skeleton only — full impl in Phase 1)
  - `ContentExtractor.extract(package_path, target_dir) -> ExtractedContent` placeholder dataclass with `manifest`, `topology`, `devices`, `lifecycle_phases`, `scenarios`, `grading_rules`, `reports`, `restore_rules` fields, all defaulting to `None`/`{}`
  - Phase 0 only needs the dataclass shape; `extract()` may raise `NotImplementedError` until Phase 1

**Tests** in `src/core/tests/infrastructure/content_store/`:

- `test_pod_type_detector.py` — table-driven: explicit manifest wins; cml.yaml fallback; radkit topology beats cml.yaml; ambiguous raises with signals list
- `test_pav1_validator.py` — valid minimal manifest passes; missing `format_version` fails; wrong `pod_type` enum value fails
- `tests/fixtures/pav1_minimal.zip` — minimal valid PAv1 package: `PAv1/manifest.yaml`, `PAv1/topology/cml.yaml` (stub), `PAv1/lifecycle.yaml` (one phase with one step)
- `tests/fixtures/pav1_radkit_topology_no_manifest.zip` — tests priority chain step 2

**Module discipline:** All imports at top of file. No inline imports except `TYPE_CHECKING`. See copilot-instructions.md §Import Guidelines.

**Acceptance:** `cd src/core && .venv/bin/pytest -q` passes; both detector and validator have ≥90% line coverage.

---

### Step 3 — Expand `PodDefinitionState`  (G-03 / AD-CSI-004)

**Edit** `src/scenario-engine/domain/entities/pod_definition.py`:

Add to `PodDefinitionState` (with safe defaults so existing MongoDB rows deserialise cleanly — Neuroglia bypasses `__init__` on rehydration):

```python
content_hash: str | None
topology: dict[str, Any] | None
devices: list[dict[str, Any]] | None
lifecycle_phases: dict[str, Any] | None
scenarios: dict[str, dict[str, Any]] | None
grading_rules: dict[str, Any] | None
reports: dict[str, Any] | None
restore_rules: dict[str, Any] | None
```

Initialise all in `__init__` as `None` / empty.

**Edit** `src/scenario-engine/domain/events/pod_definition_events.py`:

- Extend `PodDefinitionReadyDomainEvent` to carry the same fields (all optional)
- Add `PodDefinitionSyncFailedDomainEvent(reason: str, error_detail: str | None)` — needed by Phase 1; ship the event class now to avoid a future migration

**Edit** `@dispatch(PodDefinitionReadyDomainEvent)` handler in `PodDefinitionState` to populate the new fields from event payload.

**Edit** `src/scenario-engine/integration/repositories/pod_definition_repository.py` if any explicit field projection exists (most likely it uses model_dump — verify). Add a defensive `getattr(state, field, default)` only if necessary.

**Tests:**

- `src/scenario-engine/tests/domain/entities/test_pod_definition.py` — round-trip: create → ready event with full payload → state populated; create → ready with empty payload → fields remain None/empty
- `src/scenario-engine/tests/integration/repositories/test_pod_definition_repository.py` — persist + reload preserves all new fields

**Acceptance:** `cd src/scenario-engine && make lint && make test` passes.

---

### Step 4 — `RecordContentSyncResultCommand` accepts `pod_type` + `pod_definition_id`  (G-07)

**Edit** `src/control-plane-api/application/dtos/record_content_sync_result_dto.py`:

- Add optional fields `pod_type: str | None = None`, `pod_definition_id: str | None = None`
- Keep all existing fields unchanged (backward-compatible)

**Edit** `src/control-plane-api/application/commands/lablet_definition/record_content_sync_result_command.py`:

- Accept the two new fields on the command
- On success branch (where `with_sync_confirmation(hash)` is currently called), also call a new aggregate method `confirm_pod_definition(pod_definition_id, pod_type, content_hash)`:
  - If `state.pod_definition_ref is None` → build a new `PodDefinitionRef(definition_id=pod_definition_id, version=state.version, pod_type=PodType(pod_type), content_hash=content_hash)` and emit `LabletDefinitionPodDefinitionConfirmedDomainEvent(pod_definition_id, pod_type, content_hash)`
  - If `state.pod_definition_ref` exists → update `content_hash` via `with_sync_confirmation`; validate `pod_type` matches (raise `DomainConsistencyError` if mismatch — author this if it doesn't exist; otherwise reuse the closest existing exception)
- If `pod_type` is supplied but invalid (not a `PodType` member) → return `self.bad_request(f"Unknown pod_type: {pod_type}")`

**Edit** `src/control-plane-api/domain/entities/lablet_definition.py`:

- Add `def confirm_pod_definition(self, pod_definition_id, pod_type, content_hash) -> None:` aggregate method (per pattern of other domain methods — see `request_sync`)
- Add `LabletDefinitionPodDefinitionConfirmedDomainEvent` to `src/control-plane-api/domain/events/lablet_definition_events.py`
- Add `@dispatch` handler on `LabletDefinitionState` to set/refresh `pod_definition_ref`

**Tests:**

- `src/control-plane-api/tests/application/commands/lablet_definition/test_record_content_sync_result_command.py`
  - Definition seeded WITHOUT `pod_type` + sync result includes `pod_type=cml_on_aws` → `pod_definition_ref` is populated
  - Definition seeded WITH `pod_type=cml_on_aws` + sync result `pod_type=cml_on_aws` → `content_hash` updated, ref id unchanged
  - Definition seeded WITH `pod_type=cml_on_aws` + sync result `pod_type=roc_radkit` → returns conflict / domain error
  - Backward-compat: sync result without `pod_type` / `pod_definition_id` → existing behaviour preserved

**Acceptance:** `cd src/control-plane-api && .venv/bin/pytest tests/ -k record_content_sync -q` passes; `make lint` clean.

---

### Step 5 — Final verification

Run, in this order:

```bash
cd src/core            && .venv/bin/pytest -q && .venv/bin/ruff check
cd src/scenario-engine && make lint && make test
cd src/control-plane-api && make lint && make test
```

All three must be green. **Do not** run end-to-end or Docker stack tests — Phase 0 is library-level only.

---

## Out of scope for Phase 0 (do NOT implement here)

- ❌ SE `SyncContentCommand` full S3 download / extraction logic (Phase 1, G-01)
- ❌ `lablet-controller` calling SE (Phase 2, G-02)
- ❌ `ScenarioEngineStep` base class / Tier-B steps (Phase 3, G-05)
- ❌ Implementing the 5 `events_controller` CloudEvent handlers (Phase 3, G-06)
- ❌ `ContentDrivenTemplateLoader` (Phase 4, G-09)
- ❌ Grading / report scenarios (Phase 5, G-10)
- ❌ Scheduler `pod_type` filter (Phase 6, G-11)
- ❌ `PodDefinitionProjector` HostedService in CPA (Phase 2, G-12)

If you find yourself touching files outside the **Implementation Steps** list above, **stop** and update the plan (§3) with a new gap or open question first.

---

## Knowledge Manager hygiene during the session

After completing each step, call:

```text
mcp_knowledge_update_task(
  workspace_id: "lablet-cloud-manager",
  title: "Phase 0 Foundations: PAv1/ spec + PodDefinition fields + PodTypeDetector",
  status: "in_progress"  // or "completed" when ALL steps done
)
```

For each new file of architectural significance:

```text
mcp_knowledge_add_file_context(workspace_id: "lablet-cloud-manager", path: "...", purpose: "...", patterns_used: [...])
```

If you make a **new** architectural decision (not already in AD-CSI-001..007), store it as `AD-CSI-008+` and append to `docs/implementation/cpa-se-integration-plan.md` §7.

If you discover a previously-undocumented gotcha, store it as a `gotcha` insight.

---

## Definition of Done — Phase 0

- [x] PAv1/ spec doc + 3 JSON schemas published under `docs/architecture/content-format/`
- [x] `lcm_core.infrastructure.content_store` package with `PAv1Validator`, `PodTypeDetector`, `ContentExtractor` skeleton (schemas vendored under `lcm_core/infrastructure/content_store/schemas/`)
- [x] `PodDefinitionState` carries all 8 new fields with safe defaults
- [x] `PodDefinitionReadyDomainEvent` extended; `PodDefinitionSyncFailedDomainEvent` added
- [x] `RecordContentSyncResultCommand` + `LabletDefinition.confirm_pod_definition` shipped (DTO change rolled into the command dataclass — see commit `820dcaf` notes; no separate `record_content_sync_result_dto.py` existed)
- [x] Two test fixtures (`pav1_minimal`, `pav1_radkit_topology_no_manifest`) committed as in-process zip builders under `src/core/tests/infrastructure/content_store/fixtures.py`
- [x] All three services pass `make lint && make test` — core 293 ✓ · scenario-engine 99 ✓ · control-plane-api 1078 ✓ (content_store coverage 97%)
- [x] `docs/implementation/cpa-se-integration-plan.md` updated: G-03/G-04/G-07/G-08 🟢 Closed with commit refs; §2 inventory annotated; Phase 0 marked complete
- [x] Task `Phase 0 Foundations` marked `completed` in Knowledge Manager
- [x] Commits use `feat:` / `docs:` prefixes; each commit signed off (`-s`); changes split atomically (4 commits, one per step)
- [x] New decision **AD-CSI-010** (400/409 status mapping for `confirm_pod_definition`) recorded in §7

### Deviations from the original plan

- **No separate `record_content_sync_result_dto.py`**: the existing DTO `LabletDefinitionSyncResultDto` (in `application/dtos/lablet_definition_dto.py`) already covers the response shape; new request fields landed directly on the `RecordContentSyncResultCommand` dataclass.
- **`PodDefinitionSyncFailedDomainEvent` is event-only in Phase 0**: the aggregate method that emits it lands with Phase 1's `SyncContentCommand` rewrite (G-01). Avoids an unused-import lint failure today.
- **Schemas vendored** under `src/core/lcm_core/infrastructure/content_store/schemas/` (in addition to the doc copies at `docs/architecture/content-format/schemas/`) so the package has no runtime dependency on the docs tree. README in the schemas dir notes the dual-copy invariant.

---

## Commit message template

```text
feat(content-store): add PodTypeDetector and PAv1Validator (closes G-04, G-08)

- Implement priority chain per AD-CSI-002
- Add JSON schemas for manifest, lifecycle, scenario
- Add fixture pav1_minimal.zip for downstream tests
- Update cpa-se-integration-plan.md: G-04/G-08 → Closed

Refs: ADR-044, AD-CSI-002, AD-CSI-008 (if new)
```

---

## When to ask vs proceed

- If the existing `LabletDefinition.request_sync()` / `with_sync_confirmation()` pattern is unclear → **read the file**, do not ask.
- If a JSON schema field is debatable (e.g. should `manifest.scenarios_used` be required?) → **proceed with the most conservative choice** (optional with a clear `description`) and note it in §8 (open questions).
- If a test fixture format is ambiguous → **proceed** and document the choice in the PAv1.md spec.
- If you discover the file structure differs materially from §2 inventory in the plan → **stop, update §2, then continue** (the plan is the source of truth and must not drift).
