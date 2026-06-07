# Bootstrap Prompt: CPA↔SE Integration — Phase 1 SE Content Sync Becomes Real

> **🔴 Status: Not started.** Phase 0 foundations are in place (see [`cpa-se-integration-phase-0.md`](cpa-se-integration-phase-0.md) — closed in commits `d5600a1`, `7d760fe`, `820dcaf`, `c081eab`). This phase makes the one remaining 🔥 Blocker — **G-01** — go from stub to real.

| Attribute | Value |
|-----------|-------|
| **Sprint** | CSI-Phase1 |
| **Plan (living doc)** | [docs/implementation/cpa-se-integration-plan.md](../cpa-se-integration-plan.md) |
| **Authority** | [ADR-044 Content-Driven Lifecycle Engine](../../architecture/adr/ADR-044-content-driven-lifecycle-engine.md) (Rev 2) |
| **Services touched** | `src/core/`, `src/scenario-engine/` only (do **not** touch `lablet-controller`, `control-plane-api`, `resource-scheduler`, `worker-controller`) |
| **Tests must pass** | `cd src/core && .venv/bin/pytest -q && .venv/bin/ruff check` + `cd src/scenario-engine && make lint && make test` |
| **Feature flag** | `SE_INTEGRATION_ENABLED` stays `false` — Phase 1 is invocation-compatible but is not yet called from anywhere in production code paths |

---

## Mode & Session

Run as **`lcm-senior-architect`** agent mode. First action:

```text
mcp_knowledge_recall_session(
  workspace_id: "lablet-cloud-manager",
  focus_hint: "Phase 1 SE SyncContentCommand S3 download PAv1 extraction PodDefinition ready supersession"
)

mcp_knowledge_set_focus(
  workspace_id: "lablet-cloud-manager",
  name: "CPA↔SE Phase 1 SE Content Sync",
  description: "Implement SyncContentCommand end-to-end: S3ContentClient, ContentExtractor.extract(), supersession of stale PodDefinitions, READY transition, CloudEvent emission (closes G-01)",
  active_plan: "docs/implementation/cpa-se-integration-plan.md",
  current_phase: "Phase 1 — G-01 SE content sync becomes real",
  priority_files: [
    "src/scenario-engine/application/commands/sync_content_command.py",
    "src/core/lcm_core/infrastructure/content_store/content_extractor.py",
    "src/core/lcm_core/infrastructure/content_store/pav1_validator.py",
    "src/core/lcm_core/infrastructure/content_store/pod_type_detector.py",
    "src/scenario-engine/integration/services/cloud_event_client.py",
    "src/scenario-engine/domain/repositories/pod_definition_repository.py",
    "src/scenario-engine/domain/entities/pod_definition.py",
    "src/scenario-engine/domain/events/pod_definition_events.py",
    "src/lablet-controller/integration/services/s3_client.py"
  ],
  priority_components: ["SyncContentCommand", "ContentExtractor", "S3ContentClient", "PodDefinitionRepository", "CloudEventCallbackService", "PAv1Validator", "PodTypeDetector"]
)
```

**Pre-existing decisions (do not re-store):** `AD-CSI-001` DSL boundary · `AD-CSI-002` Pod-type priority chain · `AD-CSI-003` Sync handoff order · `AD-CSI-004` PodDefinition typed fields · `AD-CSI-005` Mediator-only CloudEvent handlers · `AD-CSI-006` Feature-flag migration · `AD-CSI-007` Read-only CPA projection · `AD-CSI-008` Tier-A/B steps · `AD-CSI-009` Suspension via CloudEvent · `AD-CSI-010` 400/409 mapping for `confirm_pod_definition`.

---

## Objective

Land **G-01**: rewrite `SE.SyncContentCommand` from a stub into a real 10-step orchestration:

```text
1. Resolve or create PodDefinition (existing — keep)
2. Transition DEFINED → SYNCHRONIZING (existing — keep)
3. Download package from S3 source_uri to a temp dir
4. Verify SHA-256 over the downloaded bytes → content_hash
5. ContentExtractor.extract(...) → ExtractedContent
6. PAv1Validator.validate_manifest / validate_lifecycle / validate_scenario(*)
7. PodTypeDetector.detect(...) → confirm/override pod_type
8. Aggregate.mark_ready(content_hash, topology, devices, lifecycle_phases,
                        scenarios, grading_rules, reports, restore_rules)
9. Repository.expire_superseded_definitions_async(name, pod_type, content_hash)
10. CloudEventCallbackService.emit_content_synced(...)
```

On any failure between steps 3-7: emit `PodDefinitionSyncFailedDomainEvent` (already exists from Phase 0), persist `FAILED` status with `error_message`, and return `self.internal_server_error(...)`. Steps 1-2 errors keep current `bad_request`/`conflict` semantics.

**Closes gaps:** G-01.
**Read the full plan first:** [docs/implementation/cpa-se-integration-plan.md](../cpa-se-integration-plan.md) §3 (G-01), §5 (PAv1 spec).

---

## Implementation Steps (in order)

### Step 1 — `S3ContentClient` in `lcm_core`

**Create** `src/core/lcm_core/infrastructure/content_store/s3_content_client.py`.

- Pattern: **mirror** `src/lablet-controller/integration/services/s3_client.py` (boto3 client wrapping S3-compatible endpoint, async-wrapped via `asyncio.to_thread`). Do **not** import lablet-controller code — copy the pattern into `lcm_core` so SE depends only on `lcm_core` + boto3.
- Public surface:
  - `class S3ContentClient` with `__init__(endpoint_url, access_key, secret_key, region, secure=True)`
  - `async def download(uri: str, dest_path: pathlib.Path) -> pathlib.Path` — parses `s3://bucket/key`, downloads to `dest_path`, returns the path
  - `async def head(uri: str) -> dict[str, Any]` — returns at least `{"size": int, "etag": str}`
  - `class S3ContentClientError(Exception)` with `uri`, `bucket`, `key` attributes
  - **No** `configure()` classmethod here — SE will register it itself in its DI bootstrap (see Step 5).
- Add `boto3 = ">=1.40,<2.0"` to `src/core/pyproject.toml` `[tool.poetry.dependencies]` (lablet-controller already pins `^1.40.74`; match that floor).
- Tests: `src/core/tests/infrastructure/content_store/test_s3_content_client.py` using **moto** (`moto[s3]>=5.0,<6.0`, add as dev-dep). Cover: happy-path download, `head`, missing bucket → `S3ContentClientError`, malformed URI → `S3ContentClientError`.

**Acceptance:** `cd src/core && .venv/bin/pytest tests/infrastructure/content_store/test_s3_content_client.py -q` passes; coverage ≥ 90% on the new file.

---

### Step 2 — Finish `ContentExtractor.extract()`

**Edit** `src/core/lcm_core/infrastructure/content_store/content_extractor.py`.

- Replace the `NotImplementedError` stub with a real `async def extract(package_path: pathlib.Path, target_dir: pathlib.Path) -> ExtractedContent`.
- Behaviour:
  1. Open `package_path` as `zipfile.ZipFile`.
  2. Run `PodTypeDetector.detect(zip_file)` first (so we can fall back when manifest absent). Stash the detected `PodType`.
  3. Extract the `PAv1/` tree to `target_dir`.
  4. Load (where present, all optional unless noted):
     - `PAv1/manifest.yaml` → `manifest: dict` (REQUIRED — bail with `PAv1ValidationError` if missing; defer schema check to caller)
     - `PAv1/topology/*.yaml` → `topology: dict[str, dict]` (key = filename without extension; e.g. `cml.yaml` → `topology["cml"] = …`)
     - `PAv1/topology/devices.json` → `devices: list[dict]` (legacy fallback: also accept `PAv1/devices.json`)
     - `PAv1/lifecycle.yaml` → `lifecycle_phases: dict[str, list[dict]]` (keyed by phase name)
     - `PAv1/scenarios/*.yaml` → `scenarios: dict[str, dict]` (key = filename without `.yaml`)
     - `PAv1/grading/*.yaml` → `grading_rules: dict[str, dict]`
     - `PAv1/reports/*.yaml` → `reports: dict[str, dict]`
     - `PAv1/restore/*.yaml` → `restore_rules: dict[str, dict]`
  5. Populate and return `ExtractedContent(manifest=..., topology=..., devices=..., lifecycle_phases=..., scenarios=..., grading_rules=..., reports=..., restore_rules=..., detected_pod_type=...)` — add the `detected_pod_type` field if not already present.
- Use `yaml.safe_load`; raise `PAv1ValidationError(path=..., errors=[...])` on YAML parse errors. Do **not** double-validate against JSON Schemas here — the caller (SyncContentCommand) decides whether to validate.
- Reuse the existing Phase 0 fixtures `pav1_minimal_bytes()` and `pav1_radkit_no_manifest_bytes()` from `src/core/tests/infrastructure/content_store/fixtures.py` for tests; add a richer `pav1_full_bytes()` builder that exercises every PAv1 sub-tree (one scenario, one grading rule, one report, one restore rule). Persist no new `.zip` files — keep them in-process zip builders.

**Tests:** `src/core/tests/infrastructure/content_store/test_content_extractor.py` covering:

- `pav1_minimal` round-trip → `manifest` present, other sub-trees `None`/`{}`
- `pav1_full` round-trip → every field populated as expected
- Missing `PAv1/manifest.yaml` → `PAv1ValidationError`
- Corrupt YAML in any sub-tree → `PAv1ValidationError`
- `pav1_radkit_no_manifest` → `detected_pod_type == PodType.ROC_RADKIT` (still raises `PAv1ValidationError` for missing manifest — exception carries the detected pod_type as a hint via `errors[0]`)

**Acceptance:** `cd src/core && .venv/bin/pytest tests/infrastructure/content_store/ -q` passes; coverage on `content_extractor.py` ≥ 90%.

---

### Step 3 — Repository: `expire_superseded_definitions_async()`

**Edit** `src/scenario-engine/domain/repositories/pod_definition_repository.py`:

- Add abstract method:

  ```python
  async def expire_superseded_definitions_async(
      self,
      name: str,
      pod_type: PodType,
      current_definition_id: str,
      current_content_hash: str,
  ) -> list[str]:
      """Return ids of PodDefinitions transitioned to SUPERSEDED."""
  ```

**Edit** `src/scenario-engine/integration/repositories/pod_definition_repository.py` (Mongo impl):

- Implement by querying `{name, pod_type, status: READY, content_hash: {$ne: current_content_hash}, _id: {$ne: current_definition_id}}`.
- For each match, load the aggregate, call `pd.supersede(superseded_by=current_definition_id)` (verify this method exists on `PodDefinition`; if not — add it on the aggregate in this step, paired with a `PodDefinitionSupersededDomainEvent` if not already present).
- `update_async` each one. Return the list of superseded ids.
- Keep this idempotent: re-running with the same `(name, pod_type, current_content_hash, current_definition_id)` returns `[]`.

**Tests:** add to `src/scenario-engine/tests/integration/repositories/test_pod_definition_repository.py` (or create) — covers happy path, no-op when no stale defs exist, ignores defs of other pod_types or names.

**Acceptance:** SE test suite green.

---

### Step 4 — Rewrite `SyncContentCommand`

**Edit** `src/scenario-engine/application/commands/sync_content_command.py`. Keep the existing dataclass shape but rewrite the handler body to perform the full 10-step flow above.

- Inject: `PodDefinitionRepository`, `S3ContentClient`, `ContentExtractor`, `PAv1Validator`, `PodTypeDetector`, `CloudEventCallbackService`, `Settings`.
- Use `RequestHandler` helper methods (`self.bad_request`, `self.conflict`, `self.accepted`, `self.internal_server_error`). **Never** import `OperationResult` for construction.
- Wrap steps 3-7 in `try/except`. On exception:
  - Call `pod_def.mark_failed(reason, error_detail)` (verify exists; otherwise add the aggregate method + dispatch handler that consumes `PodDefinitionSyncFailedDomainEvent`).
  - `await self._repository.update_async(pod_def)`.
  - Emit `PodDefinitionSyncFailedDomainEvent` via the same CloudEvent client if appropriate (out-of-process listeners need it; Phase 2 will route it to CPA).
  - Return `self.internal_server_error(f"Content sync failed: {exc}")`.
- On the **force re-sync** path (existing `force=True` branch): always run supersession at the end so an old hash with same id is replaced.
- Temp files: use `tempfile.TemporaryDirectory()` context for download + extraction targets. Clean up on both success and failure.
- Logging: one INFO per step transition; one ERROR with traceback on the failure path.

**Acceptance:** see Step 6 tests.

---

### Step 5 — `CloudEventCallbackService.emit_content_synced(...)`

**Edit** `src/scenario-engine/integration/services/cloud_event_client.py`:

- Add CloudEvent type constant: `EVENT_POD_DEFINITION_READY = "scenario_engine.pod_definition.ready.v1"` (mirror the dot-versioned style already used by `EVENT_STARTED`).
- Add CloudEvent type constant: `EVENT_POD_DEFINITION_SYNC_FAILED = "scenario_engine.pod_definition.sync_failed.v1"` (matches the `@cloudevent(...)` decorator on the domain event added in Phase 0).
- Add `async def emit_content_synced(self, *, pod_definition_id, name, version, pod_type, content_hash, callback_url=None) -> None` that wraps `_emit(...)` with `data = {"pod_definition_id": ..., "name": ..., "version": ..., "pod_type": pod_type.value, "content_hash": ...}`.
- Add `async def emit_sync_failed(self, *, pod_definition_id, reason, error_detail=None, callback_url=None) -> None` symmetrically.
- Callback URL resolution: reuse existing `_resolve_target_url(callback_url)`. If neither per-call nor `settings.cloud_event_sink` is set → log a warning and skip (existing behaviour).

**DI registration:** confirm `CloudEventCallbackService`, `S3ContentClient`,
`ContentExtractor`, `PAv1Validator`, `PodTypeDetector` are all registered in
SE's DI container (look at `src/scenario-engine/main.py` and
`src/scenario-engine/application/services/...`). Register any that are missing
as singletons. `S3ContentClient` should pick up its config from `Settings` —
add `s3_endpoint_url`, `s3_access_key`, `s3_secret_key`, `s3_region`,
`s3_secure` fields on `Settings` if absent (defaults: `http://aix-rustfs:9000`,
`minioadmin`, `minioadmin`, `us-east-1`, `False` — match lablet-controller's
defaults).

**Acceptance:** SE boots clean; new emitters callable via DI.

---

### Step 6 — Tests

Create / extend (use `pytest-asyncio` already in dev deps):

- `src/scenario-engine/tests/application/commands/test_sync_content_command.py`
  - **Happy path**: stub `S3ContentClient` to return the `pav1_minimal_bytes()` zip → handler returns `accepted` with `definition_id`, status `READY`, hash equals SHA-256 of the bytes; full PAv1 fields populated.
  - **Force re-sync**: pre-seed an existing READY PodDefinition with same `(name, pod_type)` but a different `content_hash` → after sync, old one is `SUPERSEDED`, new one is `READY`.
  - **Failure path**: stub `S3ContentClient.download` to raise → PodDefinition transitions to `FAILED`, `error_message` populated, returns `internal_server_error`.
  - **CloudEvent emission**: spy on `CloudEventCallbackService.emit_content_synced` → asserts called once with the right kwargs on the happy path; asserts `emit_sync_failed` called once on the failure path.
  - **PAv1 validation failure**: stub the validator to raise `PAv1ValidationError` → PodDefinition transitions to `FAILED`, error_detail carries the schema errors.
  - **Pod-type override**: source_uri returns a zip whose detected pod_type differs from the seeded one (and `force=True`) → asserts the new pod_type is recorded, supersession runs scoped to the _new_ pod_type.

- `src/scenario-engine/tests/integration/repositories/test_pod_definition_repository_supersede.py` — see Step 3.

- `src/core/tests/infrastructure/content_store/test_content_extractor.py` and `test_s3_content_client.py` — see Steps 1 & 2.

**Acceptance:** `cd src/scenario-engine && make test` green; `cd src/core && .venv/bin/pytest -q` green.

---

### Step 7 — Final verification

```bash
cd src/core            && .venv/bin/pytest -q && .venv/bin/ruff check
cd src/scenario-engine && make lint && make test
```

Both must be green. **Do not** touch CPA or run the Docker stack — Phase 1 changes are SE-internal + `lcm_core`.

---

## Out of scope for Phase 1 (do NOT implement here)

- ❌ `lablet-controller` calling SE (Phase 2, G-02 — needs `ScenarioEngineClient.sync_content` call site)
- ❌ `PodDefinitionProjector` HostedService in CPA (Phase 2, G-12)
- ❌ `ScenarioEngineStep` base class / Tier-B steps (Phase 3, G-05)
- ❌ The 5 `events_controller` CloudEvent handlers in CPA (Phase 3, G-06)
- ❌ `ContentDrivenTemplateLoader` (Phase 4, G-09)
- ❌ Grading / report scenarios (Phase 5, G-10)
- ❌ Scheduler `pod_type` filter (Phase 6, G-11)

If you find yourself touching files outside the **Implementation Steps** list above (notably anything in `src/control-plane-api/`, `src/lablet-controller/`, `src/resource-scheduler/`, `src/worker-controller/`), **stop** and update the plan §3 with a new gap or open question first.

---

## Open questions to resolve before / during the work

- **Q-03 (Plan §8)** — How does SE learn the per-PodDefinition callback URL? Phase 1 proposal: accept an optional `callback_url` on `SyncContentCommand`; if absent, use `settings.cloud_event_sink` (existing). Document in §8 once chosen.
- **Q-06 (Plan §8)** — Should `content_hash` algorithm be configurable? Phase 1 ships SHA-256 hardcoded; expose `settings.content_hash_algo` only if Phase 2 needs it.
- **New / Phase 1** — `ExtractedContent.detected_pod_type`: should it be `PodType | None` or `PodType` (always set, default to `UNKNOWN` enum value)? Recommended: `PodType | None`; only the SyncContentCommand decides whether `None` is fatal.

Decide and record any answers as `AD-CSI-011+` in `cpa-se-integration-plan.md §7`.

---

## Knowledge Manager hygiene during the session

After completing each Step, call:

```text
mcp_knowledge_update_task(
  workspace_id: "lablet-cloud-manager",
  title: "Phase 1: SE Content Sync (G-01)",
  status: "in_progress"  // or "completed" when ALL steps done
)
```

For each new file of architectural significance (e.g. `s3_content_client.py`, full `content_extractor.py`, refactored `sync_content_command.py`):

```text
mcp_knowledge_add_file_context(
  workspace_id: "lablet-cloud-manager",
  path: "...",
  purpose: "...",
  key_exports: [...],
  patterns_used: ["Async wrapper around boto3", "Self-contained CQRS handler", ...]
)
```

If you make a **new** architectural decision (not in AD-CSI-001..010), store it as `AD-CSI-011+` and append to `cpa-se-integration-plan.md` §7.

---

## Definition of Done — Phase 1

- [ ] `lcm_core.infrastructure.content_store.S3ContentClient` shipped + `moto`-backed tests
- [ ] `ContentExtractor.extract()` parses the full `PAv1/` tree into `ExtractedContent` (no `NotImplementedError`)
- [ ] `ExtractedContent.detected_pod_type` field added (`PodType | None`)
- [ ] `PodDefinitionRepository.expire_superseded_definitions_async()` shipped on interface + Mongo impl
- [ ] `PodDefinition.supersede(...)` and `PodDefinition.mark_failed(...)` aggregate methods present (verified existing or newly added with @dispatch handlers + events)
- [ ] `SyncContentCommand` rewritten end-to-end (DEFINED → SYNCHRONIZING → download → SHA → extract → validate → READY → supersede stale → emit CloudEvent)
- [ ] `CloudEventCallbackService.emit_content_synced()` + `emit_sync_failed()` shipped
- [ ] New SE Settings fields for S3 + DI registrations for S3ContentClient / ContentExtractor / PAv1Validator / PodTypeDetector
- [ ] 4 test suites pass: end-to-end sync, supersession, failure path, CloudEvent emission spy
- [ ] `cd src/scenario-engine && make lint && make test` green
- [ ] `cd src/core && make lint && make test` green
- [ ] `docs/implementation/cpa-se-integration-plan.md` §3 G-01 banner flipped 🔴 → 🟢 with `**Closed:** <SHA>` line
- [ ] Plan §1 exec summary row for "Content extraction → SE" updated to reflect G-01 closed (G-02 still 🔴 Open)
- [ ] Plan §6 Phase 1 bullets ticked
- [ ] Task `Phase 1: SE Content Sync (G-01)` marked `completed` in Knowledge Manager
- [ ] Commits atomic with `-s`, prefixed `feat:` / `test:` / `docs:`
- [ ] Any new architectural decisions stored as `AD-CSI-011+` (both in KM and plan §7)

---

## Suggested commit slicing

1. `feat(content-store): add S3ContentClient and full ContentExtractor for PAv1 (closes part of G-01)`
2. `feat(scenario-engine): PodDefinitionRepository.expire_superseded_definitions_async()`
3. `feat(scenario-engine): SyncContentCommand end-to-end download / extract / READY / supersede / emit (closes G-01)`
4. `docs(integration-plan): mark G-01 closed (Phase 1)`

Each `git commit -s`; expect pre-commit hooks (`ruff-format`, `ruff`, `prettier`, `markdownlint`) to auto-modify files — `git add` the touched paths and retry.

---

## When to ask vs proceed

- **Existing aggregate methods exist** (`supersede`, `mark_failed`) — **read the file**, don't ask.
- **CloudEvent payload shape is debatable** (e.g. include `manifest` blob? include `topology`?) — proceed with the **minimal** payload spec'd above (ids + version + hash + pod_type); fuller payloads belong to the Phase 2 projector consumer.
- **Callback URL routing is ambiguous** — proceed with the conservative default (per-call → settings → noop log); document in §8.
- **`content_extractor` discovers a sub-tree shape not covered by Phase 0 schemas** — proceed but file a follow-up gap (e.g. G-13) in plan §3 rather than silently extending the schemas.
- **You find the plan §2 inventory drifts from reality** — **stop, update §2, then continue**. The plan is the source of truth.
