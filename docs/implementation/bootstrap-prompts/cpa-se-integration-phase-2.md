# Bootstrap Prompt: CPA↔SE Integration — Phase 2 lablet-controller calls SE + CPA projection

> **🔴 Status: Not started.** Phase 1 closed in commits `0624a6a`, `184398d`, `172d161`, `08563ac` — SE's `SyncContentCommand`
> is now a real 10-step orchestrator and emits `pod_definition.ready.v1` / `pod_definition.sync_failed.v1` with
> `superseded_ids[]` carried inside the `ready.v1` payload. The integration is end-to-end **inside** SE, but no caller
> invokes it yet. This phase closes that loop by (a) wiring `lablet-controller`'s `ContentSyncService` to notify SE and
> (b) building CPA's read-only projection of SE state.

| Attribute | Value |
|-----------|-------|
| **Sprint** | CSI-Phase2 |
| **Plan (living doc)** | [docs/implementation/cpa-se-integration-plan.md](../cpa-se-integration-plan.md) |
| **Authority** | [ADR-044 Content-Driven Lifecycle Engine](../../architecture/adr/ADR-044-content-driven-lifecycle-engine.md) (Rev 2) |
| **Closes** | G-02 (🔥 Blocker), G-12 (🟡) |
| **Resolves open questions** | Q-02 (SE-unreachable strategy), Q-05 (projection shape) |
| **Services touched** | `src/core/`, `src/lablet-controller/`, `src/control-plane-api/` (do **not** touch `scenario-engine` — its API is the contract) |
| **Tests must pass** | `cd src/core && pytest -q` · `cd src/lablet-controller && make lint && make test` · `cd src/control-plane-api && make lint && make test` |
| **Feature flag** | `SE_INTEGRATION_ENABLED` (new, lablet-controller `Settings`, default **`false`**) — the SE call is opt-in for Phase 2; Phase 4 will flip the default |

---

## Mode & Session

Run as **`lcm-senior-architect`** agent mode. First action:

```text
mcp_knowledge_recall_session(
  workspace_id: "lablet-cloud-manager",
  focus_hint: "Phase 2 lablet-controller ScenarioEngineClient sync_content ContentSyncService CPA PodDefinitionProjector CloudEvent"
)

mcp_knowledge_set_focus(
  workspace_id: "lablet-cloud-manager",
  name: "CPA↔SE Phase 2 SE notification + CPA projection",
  description: "Add ScenarioEngineClient.sync_content + wire into ContentSyncService (G-02); add CPA events_controller + PodDefinitionProjector + read repository (G-12); guard with SE_INTEGRATION_ENABLED feature flag",
  active_plan: "docs/implementation/cpa-se-integration-plan.md",
  current_phase: "Phase 2 — lablet-controller calls SE + CPA projection",
  priority_files: [
    "src/lablet-controller/integration/services/scenario_engine_client.py",
    "src/lablet-controller/application/hosted_services/content_sync_service.py",
    "src/lablet-controller/application/settings.py",
    "src/lablet-controller/main.py",
    "src/core/lcm_core/integration/clients/control_plane_api_client.py",
    "src/control-plane-api/api/controllers/events_controller.py",
    "src/control-plane-api/application/commands/pod_definition_read/project_pod_definition_ready_command.py",
    "src/control-plane-api/application/commands/pod_definition_read/project_pod_definition_sync_failed_command.py",
    "src/control-plane-api/application/queries/pod_definition_read/get_pod_definition_query.py",
    "src/control-plane-api/domain/read_models/pod_definition_read_model.py",
    "src/control-plane-api/integration/repositories/pod_definition_read_repository.py",
    "src/control-plane-api/main.py"
  ],
  priority_components: ["ScenarioEngineClient", "ContentSyncService", "PodDefinitionProjector", "EventsController", "PodDefinitionReadRepository"]
)
```

**Pre-existing decisions (do not re-store):**

- `AD-CSI-001` DSL boundary · `AD-CSI-002` Pod-type priority · `AD-CSI-003` Sync handoff order
- `AD-CSI-004` PodDefinition typed fields · `AD-CSI-005` Mediator-only CloudEvent handlers
- `AD-CSI-006` Feature-flag migration · `AD-CSI-007` Read-only CPA projection · `AD-CSI-008` Tier-A/B steps
- `AD-CSI-009` Suspension via CloudEvent · `AD-CSI-010` 400/409 mapping for `confirm_pod_definition`
- `AD-CSI-011` PodDefinition FAILED state · `AD-CSI-012` Extractor optional `detected_pod_type`
- `AD-CSI-013` Per-request CloudEvent callback URL.

**New decisions you will record this phase (AD-CSI-014+):**

- Q-02 → resolution of "SE unreachable during lablet-controller sync"
- Q-05 → "projection is last-write-wins from event payload"
- Whatever else surfaces

---

## Objective

Close the integration loop:

```text
                                   ┌───────────────────────────────┐
   Mosaic ──┐                       │  scenario-engine              │
            ▼                       │   SyncContentCommand (Phase 1)│
   lablet-controller                │   ↓                            │
   ContentSyncService               │   PodDefinition READY          │
   ├─ download + SHA-256            │   ↓                            │
   ├─ extract metadata              │   CloudEvent: pod_definition.  │
   ├─ PodTypeDetector.detect()*new* │     ready.v1 (+ superseded_ids)│
   ├─ S3 upload to RustFS           │       │                        │
   ├─ scenario_engine.sync_content()│◀──────┤                        │
   │  *new — G-02*                  │       │                        │
   ├─ record_content_sync_result    │       │                        │
   │  (now incl. pod_definition_id, │       │                        │
   │   pod_type)                    │       ▼                        │
   └─ to CPA                        │  control-plane-api             │
                                    │   events_controller   *new*    │
                                    │   PodDefinitionProjector *new* │
                                    │   PodDefinitionReadRepository  │
                                    │     (read-only collection)     │
                                    └───────────────────────────────┘
```

After Phase 2, a single sync request produces:

1. A `LabletDefinition` in CPA with `pod_definition_ref.content_hash` populated (existing).
2. A `PodDefinition(status=READY)` in SE's MongoDB (Phase 1).
3. A row in CPA's `pod_definitions_read` collection mirroring SE state (new — G-12).
4. Any prior `(name, pod_type)` rows flipped to `SUPERSEDED` in the read collection (new).

The feature flag stays `false` by default; integration tests turn it on.

---

## Implementation Steps (in order)

### Step 1 — `ScenarioEngineClient.sync_content(...)` (G-02 part 1)

**Edit** `src/lablet-controller/integration/services/scenario_engine_client.py`:

- Add dataclass alongside the existing ones:

  ```python
  @dataclass
  class ContentSyncResult:
      pod_definition_id: str
      version: str
      status: str           # "ready" | "synchronizing" | "failed"
      content_hash: str
      message: str | None = None
  ```

- Add method:

  ```python
  async def sync_content(
      self,
      *,
      source_uri: str,
      content_hash: str,
      name: str,
      version: str,
      pod_type: str,                # serialised PodType.value
      force: bool = False,
      callback_url: str | None = None,
      timeout: float = 60.0,
  ) -> ContentSyncResult:
      """POST /api/v1/content/sync to the Scenario Engine.

      The SE handler is synchronous-from-HTTP-perspective: it downloads,
      extracts, validates, persists, and supersedes inside the request,
      then returns 202 Accepted with the new PodDefinition id.
      """
  ```

  Wire it to `POST {base_url}/api/v1/content/sync` with payload
  `{source_uri, content_hash, name, version, pod_type, force, callback_url?}`.
  Use a longer per-call timeout (SE downloads + unzips a real package).
  Raise `ScenarioEngineError` on non-2xx, exposing the SE-side
  `OperationResult.error_message` when available.

**Tests** in `src/lablet-controller/tests/integration/services/test_scenario_engine_client_sync_content.py`:

- Happy path (200/202 → `ContentSyncResult`)
- 409 conflict → `ScenarioEngineError(status_code=409)`
- 500 → `ScenarioEngineError(status_code=500)`
- `httpx.ConnectError` → `ScenarioEngineError` (no status_code)
- Use `respx` (existing dep) or `httpx.MockTransport`.

**Acceptance:** new tests pass; client compiles; `make lint` clean.

---

### Step 2 — Settings + DI in lablet-controller (G-02 part 2)

**Edit** `src/lablet-controller/application/settings.py`:

- Add field:

  ```python
  scenario_engine_integration_enabled: bool = Field(
      default=False, alias="SE_INTEGRATION_ENABLED",
      description="If true, ContentSyncService notifies SE after S3 upload."
  )
  ```

  (`scenario_engine_url` and `scenario_engine_callback_url` already exist — verify and reuse.)

**Edit** `src/lablet-controller/main.py`:

- Confirm `ScenarioEngineClient` is registered as a singleton (it is — line ~159). No change unless DI shape needs adjusting.

**Edit** the `ContentSyncService` constructor to inject `scenario_engine_client: ScenarioEngineClient` and `settings: Settings` (the latter likely already injected; verify). Also inject `PodTypeDetector` (from `lcm_core.infrastructure.content_store`) so the controller can compute `pod_type` defensively before the SE call.

**Acceptance:** lablet-controller boots clean; `make test` still green.

---

### Step 3 — Wire SE call into `ContentSyncService._process_sync_request` (G-02 part 3)

**Edit** `src/lablet-controller/application/hosted_services/content_sync_service.py`.

Locate `_process_sync_request` (around line 336). Insert a **new Step 6.5** between the existing Step 6 (RustFS upload) and Step 7 (notify upstream services):

```python
# Step 6.5: Notify Scenario Engine (G-02, AD-CSI-003)
pod_definition_id: str | None = None
detected_pod_type: PodType | None = None

if self._settings.scenario_engine_integration_enabled:
    se_logs: list[str] = []
    try:
        # Defensive pod-type detection on the bytes we just hashed.
        # SE will detect again on its own copy (AD-CSI-002 defence-in-depth).
        detected_pod_type, signals = self._pod_type_detector.detect_from_bytes(package_bytes)
        se_logs.append(f"PodType detected: {detected_pod_type.value} (signals={signals})")

        s3_uri = f"s3://{bucket_name}/{package_name}"
        se_logs.append(f"Notifying SE: source_uri={s3_uri}, hash={content_package_hash[:12]}…")

        sync_result_se = await self._scenario_engine.sync_content(
            source_uri=s3_uri,
            content_hash=content_package_hash,
            name=defn["name"],
            version=defn.get("version") or "v1",
            pod_type=detected_pod_type.value,
        )
        pod_definition_id = sync_result_se.pod_definition_id
        se_logs.append(f"SE accepted: pod_definition_id={pod_definition_id} status={sync_result_se.status}")

        upstream_status["scenario_engine"] = {
            "status": "success",
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "pod_definition_id": pod_definition_id,
            "pod_type": detected_pod_type.value,
            "logs": se_logs,
        }
    except Exception as se_err:
        # Q-02 resolution / AD-CSI-014: SE is best-effort.
        # Do NOT abort the CPA notification — CPA still gets the content sync
        # result with pod_definition_id=None and pod_definition_sync_status=pending.
        se_logs.append(f"WARN: {se_err}")
        logger.warning(
            "SE notification failed for %s: %s (continuing with CPA notification)",
            definition_id, se_err
        )
        upstream_status["scenario_engine"] = {
            "status": "failed",
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "error": str(se_err),
            "logs": se_logs,
        }
```

Then **extend the `sync_result` dict** built for the CPA call:

```python
sync_result: dict[str, Any] = {
    ...
    "pod_definition_id": pod_definition_id,                          # NEW
    "pod_type": detected_pod_type.value if detected_pod_type else None,  # NEW
    "upstream_sync_status": upstream_status,
}
```

`PodTypeDetector` exposes detection from a `pathlib.Path` or `ZipFile` today — add a small wrapper `detect_from_bytes(data: bytes) -> tuple[PodType, list[str]]` in `lcm_core/infrastructure/content_store/pod_type_detector.py` if missing; use `io.BytesIO(data) → zipfile.ZipFile(...)`.

**Tests:** extend `src/lablet-controller/tests/integration/hosted_services/test_content_sync_service.py` (or create) — happy path with `SE_INTEGRATION_ENABLED=true`, SE-down path (asserts CPA still notified, scenario_engine status=failed in upstream_status), feature-flag-off path (no SE call at all).

**Acceptance:** see Step 7 final verification.

---

### Step 4 — Pass `pod_definition_id` + `pod_type` to CPA (G-02 part 4)

**Edit** `src/core/lcm_core/integration/clients/control_plane_api_client.py`:

- The existing `record_content_sync_result(definition_id, payload)` already accepts a free-form dict and POSTs to `/api/internal/lablet-definitions/{id}/content-synced`. CPA's `RecordContentSyncResultDto` (Phase 0, G-07) already accepts `pod_type` and `pod_definition_id` as optional. Verify both fields are in the DTO and round-trip end-to-end. If the DTO lacks `pod_definition_id`, add it as `Optional[str]` and thread to the aggregate via `LabletDefinition.confirm_pod_definition(...)`.

**Edit** `src/control-plane-api/application/commands/lablet_definition/record_content_sync_result_command.py`:

- Confirm the handler forwards both fields to `aggregate.confirm_pod_definition(pod_definition_id=..., pod_type=..., content_hash=...)`. If `pod_definition_id` is missing but `pod_type` is present, behave exactly as today (Phase 0 path).

**Tests:** extend CPA's existing `tests/application/commands/test_record_content_sync_result_command.py` — case: full success with both new fields → `LabletDefinition.pod_definition_ref.definition_id` equals incoming `pod_definition_id`.

**Acceptance:** CPA suite stays green; the new "with `pod_definition_id`" test passes.

---

### Step 5 — CPA `events_controller` (G-12 part 1)

**Create** `src/control-plane-api/api/controllers/events_controller.py`:

- Pattern: **mirror** `src/lablet-controller/api/controllers/events_controller.py` for CloudEvent parsing (structured `application/cloudevents+json` _and_ binary `ce-*` headers). Do **not** import lablet-controller code — copy the parsing helpers.
- Route: `POST /events` (no prefix override needed; will mount as `/events` per Neuroglia convention if controller class is `EventsController`, or set `self.prefix = "/events"` explicitly).
- Dispatcher: switch on `event.type`:
  - `scenario_engine.pod_definition.ready.v1` → dispatch `ProjectPodDefinitionReadyCommand`
  - `scenario_engine.pod_definition.sync_failed.v1` → dispatch `ProjectPodDefinitionSyncFailedCommand`
  - Unknown event types → 202 Accepted with a `logged_unhandled=true` log line (do **not** 4xx — SE retries are bounded, but we want to be forward-compatible with new event types).
- Return 202 on success; 400 on malformed CloudEvent; 500 only on genuine internal errors (lets SE retry exactly the failures worth retrying).
- **Security**: Phase 2 ships with open `/events` (intra-cluster). Add a `@security` placeholder comment referencing future mTLS / shared-secret HMAC; record as open question Q-07 if not already.

**Tests:** `src/control-plane-api/tests/integration/api/test_events_controller_pod_definition.py` — structured-mode ready event, binary-mode ready event, sync_failed event, unknown event type (202 + log), malformed JSON (400). Use FastAPI `TestClient` and a fake mediator that captures dispatched commands.

---

### Step 6 — CPA read model + repository (G-12 part 2)

**Create** `src/control-plane-api/domain/read_models/pod_definition_read_model.py`:

```python
@dataclass
class PodDefinitionReadModel:
    id: str
    name: str
    version: str
    pod_type: str
    status: str                       # "READY" | "SUPERSEDED" | "FAILED"
    content_hash: str
    source_uri: str | None
    lifecycle_phases: dict[str, Any] | None
    scenarios: dict[str, dict] | None
    grading_rules: dict[str, Any] | None
    reports: dict[str, Any] | None
    restore_rules: dict[str, Any] | None
    error_message: str | None         # only when status=FAILED
    error_detail: dict[str, Any] | None
    last_event_at: datetime
    superseded_by: str | None
```

**Create** `src/control-plane-api/integration/repositories/pod_definition_read_repository.py`:

- Motor-backed; collection `pod_definitions_read` (sets the suffix to distinguish from any future write model and to satisfy AD-CSI-007 "read-only" intent in naming).
- Methods: `async def upsert_async(model: PodDefinitionReadModel) -> None`, `async def get_by_id_async(id: str) -> PodDefinitionReadModel | None`, `async def list_by_name_pod_type_async(name: str, pod_type: str) -> list[PodDefinitionReadModel]`, `async def mark_superseded_async(ids: list[str], superseded_by: str, last_event_at: datetime) -> int`.
- Indexes: create on `name + pod_type` (compound) and on `status`. Add to a one-time `ensure_indexes_async()` called at startup.

**No** abstract interface needed in the domain layer (it's a read model — concrete repo is fine; AD-CSI-007 already explains it doesn't participate in the aggregate write model).

---

### Step 7 — CPA projection commands (G-12 part 3)

**Create** the following self-contained CQRS commands (request + handler in same file, per repo convention):

- `src/control-plane-api/application/commands/pod_definition_read/project_pod_definition_ready_command.py`
  - `ProjectPodDefinitionReadyCommand(pod_definition_id, name, version, pod_type, content_hash, source_uri, lifecycle_phases, scenarios, grading_rules, reports, restore_rules, superseded_ids: list[str], emitted_at: datetime)`
  - Handler:
    1. Build `PodDefinitionReadModel(status="READY", ...)` from payload.
    2. `await repo.upsert_async(model)`.
    3. If `superseded_ids`: `await repo.mark_superseded_async(superseded_ids, superseded_by=pod_definition_id, last_event_at=emitted_at)`.
    4. Return `self.no_content()`.
  - **Idempotency**: handler is naturally idempotent — re-running with the same `emitted_at` produces the same row. To guard against stale events arriving out-of-order, **skip upsert** if the existing row has a newer `last_event_at` and a different `content_hash`. Log the skip.

- `src/control-plane-api/application/commands/pod_definition_read/project_pod_definition_sync_failed_command.py`
  - `ProjectPodDefinitionSyncFailedCommand(pod_definition_id, reason, error_detail, emitted_at)`
  - Handler upserts with `status="FAILED"`, `error_message=reason`, `error_detail=...`. Same staleness guard.

**Add a read query** for the UI / future `ContentDrivenTemplateLoader`:

- `src/control-plane-api/application/queries/pod_definition_read/get_pod_definition_query.py`
  - `GetPodDefinitionQuery(pod_definition_id)` → `OperationResult[PodDefinitionReadDto]`. Use `self.not_found("PodDefinition", pod_definition_id)` on miss.

**Tests:** one happy-path test per command + the staleness-skip test + a "ready then superseded later" sequence test that verifies the SUPERSEDED status appears on the older row.

---

### Step 8 — DI wiring + startup index creation in CPA `main.py`

**Edit** `src/control-plane-api/main.py`:

- Register `PodDefinitionReadRepository` as a singleton (uses Motor client already in DI).
- Mount `EventsController` (controllers are auto-discovered; verify nothing extra needed — if `controllers` package scanning is opt-in, add the import).
- In the existing lifespan startup, call `await read_repo.ensure_indexes_async()` once (alongside other index-creation calls; if no such pattern exists yet, add it as a small helper).

---

### Step 9 — Resolve open questions in `cpa-se-integration-plan.md §8`

Append to `§7` and update `§8`:

- **AD-CSI-014**: SE notification is **best-effort**; if SE is unreachable, lablet-controller still POSTs the content-synced result to CPA with `pod_definition_id=None` and `upstream_sync_status.scenario_engine.status="failed"`. CPA proceeds with the `LabletDefinition.confirm_pod_definition` flow but cannot finalise `pod_definition_ref.definition_id` until a retry succeeds. Closes Q-02 (option b).
- **AD-CSI-015**: CPA `pod_definitions_read` is **last-write-wins from event payload**, with a `last_event_at` staleness guard against out-of-order delivery. No event sourcing; the projection is replaceable by replaying recent events from SE. Closes Q-05.

Both must also be stored via `mcp_knowledge_store_decision`.

---

### Step 10 — Final verification

```bash
cd src/core             && .venv/bin/pytest -q && .venv/bin/ruff check
cd src/lablet-controller && make lint && make test
cd src/control-plane-api && make lint && make test
```

All three suites must be green. **Do not** run the full Docker stack — Phase 2 is service-isolated; integration tests use mocked HTTP transports for the SE call.

---

## Out of scope for Phase 2 (do NOT implement here)

- ❌ `ScenarioEngineStep` base class / Tier-B steps (Phase 3, G-05)
- ❌ The 5 SE-side `events_controller` handlers in **lablet-controller** for job lifecycle CloudEvents (Phase 3, G-06)
- ❌ `ResumePipelineStepCommand` / `FailPipelineStepCommand` (Phase 3, G-06)
- ❌ `ContentDrivenTemplateLoader` (Phase 4, G-09) — the read model created here is its dependency, but the loader itself ships later
- ❌ Grading / report scenarios (Phase 5, G-10)
- ❌ Scheduler `pod_type` filter (Phase 6, G-11)
- ❌ Migrating any seeded `LabletDefinition` to actually exercise the SE flow in production — flag stays off

If you find yourself touching files outside the **Implementation Steps** list above (notably anything in `src/scenario-engine/`, `src/resource-scheduler/`, `src/worker-controller/`), **stop** and update the master plan §3 with a new gap or open question first. The SE API is the **contract** between services this phase — do not modify it.

---

## Open questions for Phase 2

- **Q-02 (Plan §8)** — Decided here: best-effort SE notification (option b). Document as `AD-CSI-014`.
- **Q-05 (Plan §8)** — Decided here: last-write-wins from event payload with `last_event_at` guard. Document as `AD-CSI-015`.
- **Q-07 (NEW)** — `/events` ingestion endpoint on CPA: how is it authenticated? Options: (a) intra-cluster only (Phase 2 default — relies on network policy), (b) shared HMAC secret in CloudEvent extension, (c) mTLS. Recommended: open in Phase 2, decide in Phase 4 alongside `SE_INTEGRATION_ENABLED=true` flip.
- **Q-08 (NEW)** — What should the read-model `_id` be? The SE PodDefinition id (deterministic via Q-01) or a separate Mongo ObjectId? Recommended: re-use SE's id verbatim (no translation layer; simplifies projector + UI queries).

---

## Knowledge Manager hygiene during the session

After each Step, call `mcp_knowledge_update_task` with `title: "Phase 2: SE notification + CPA projection (G-02 + G-12)"` and the appropriate `status`.

For each architecturally important new file (`scenario_engine_client.sync_content`, `events_controller`, `pod_definition_projector` commands, `pod_definition_read_repository`), call `mcp_knowledge_add_file_context` with `purpose`, `key_exports`, `patterns_used`.

Record AD-CSI-014, AD-CSI-015 (and any further) via `mcp_knowledge_store_decision` **and** append to `cpa-se-integration-plan.md §7`.

---

## Definition of Done — Phase 2

- [ ] `ScenarioEngineClient.sync_content(...)` shipped with `ContentSyncResult` dataclass + 4 tests (happy, 409, 500, connection error)
- [ ] `PodTypeDetector.detect_from_bytes(...)` helper added to `lcm_core`
- [ ] `Settings.scenario_engine_integration_enabled` field added (default `false`)
- [ ] `ContentSyncService._process_sync_request` invokes SE between RustFS upload and CPA notification when the flag is on; SE failure is non-fatal (AD-CSI-014)
- [ ] `upstream_sync_status["scenario_engine"]` populated on success / failure
- [ ] `sync_result` passed to CPA includes `pod_definition_id` and `pod_type`
- [ ] CPA `EventsController` ships at `POST /events` (structured + binary CloudEvent parsing) — 5 tests
- [ ] CPA `PodDefinitionReadModel` + `PodDefinitionReadRepository` shipped with `name + pod_type` and `status` indexes
- [ ] CPA `ProjectPodDefinitionReadyCommand` + `ProjectPodDefinitionSyncFailedCommand` self-contained handlers, both with staleness-skip guard
- [ ] CPA `GetPodDefinitionQuery` shipped for read access
- [ ] CPA `main.py` registers read repo + calls `ensure_indexes_async()` at startup
- [ ] End-to-end test (mocked SE) demonstrates: lablet-controller call → SE returns `pod_definition_id` → CPA receives the id → simulated CloudEvent → `pod_definitions_read` row in READY → second sync with new hash → row updated, old one SUPERSEDED
- [ ] `cd src/lablet-controller && make lint && make test` green
- [ ] `cd src/control-plane-api && make lint && make test` green
- [ ] `cd src/core && pytest -q && ruff check` green
- [ ] Master plan §3 G-02 + G-12 banners flipped 🔴 → 🟢 with `**Closed:** <commits>` lines
- [ ] Master plan §1 exec summary row "Content extraction → SE" updated to 🟢 Complete; "Versioning & supersession" row updated
- [ ] Master plan §6 Phase 2 bullets ticked (`🟢 Complete` + verification line)
- [ ] Master plan §7 has AD-CSI-014 + AD-CSI-015 (+ any further) appended
- [ ] Master plan §8 Q-02 + Q-05 marked Resolved; Q-07 + Q-08 added if appropriate
- [ ] Task `Phase 2: SE notification + CPA projection (G-02 + G-12)` marked `completed` in Knowledge Manager
- [ ] Commits atomic with `-s`, prefixed `feat:` / `test:` / `docs:`

---

## Suggested commit slicing

1. `feat(lablet-controller): ScenarioEngineClient.sync_content + ContentSyncResult`
2. `feat(content-store): PodTypeDetector.detect_from_bytes helper`
3. `feat(lablet-controller): wire SE notification into ContentSyncService (G-02, AD-CSI-014)`
4. `feat(control-plane-api): EventsController + PodDefinitionReadRepository + projector commands (G-12)`
5. `feat(control-plane-api): GetPodDefinitionQuery + read-model DTOs`
6. `docs(integration-plan): mark G-02 + G-12 closed (Phase 2); record AD-CSI-014/015`

Each `git commit -s`; expect pre-commit hooks (`ruff-format`, `ruff`, `prettier`, `markdownlint`) to auto-modify files — re-`git add` the touched paths and retry.

---

## When to ask vs proceed

- **`PodTypeDetector` doesn't expose a `from_bytes` helper today** — **add it** (small, in-scope). Don't ask.
- **CPA's existing `RecordContentSyncResultDto` already has `pod_definition_id`** (verify with a `grep`) — proceed without re-asking. If it's missing, add the field as optional with a sensible default.
- **Controller route prefix is ambiguous** — explicit `self.prefix = "/events"` in `__init__` per the established Neuroglia override pattern (see `.github/copilot-instructions.md`).
- **Mediator vs direct repo write in the projector** — **always** via mediator-dispatched command per AD-CSI-005, even though the repo is the "read" model. Crossing services means crossing the CQRS boundary, period.
- **Pre-existing seeded definitions without `version`** — default to `"v1"`; do not block sync on missing version.
- **You find the plan §2 inventory drifts from reality** — **stop, update §2, then continue**. The plan is the source of truth.
