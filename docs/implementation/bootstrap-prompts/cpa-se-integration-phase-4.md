# Bootstrap Prompt: CPA↔SE Integration — Phase 4 Content-driven lifecycle templates + flag flip + legacy delete

> **🔵 Status: Ready to start.** Phases 0–3 + follow-ups (Q-10/Q-11) are closed. Phase 4 closes the last
> ADR-044 gap by sourcing pipeline templates from PAv1 content (`PAv1/lifecycle.yaml`) rather than from
> the hardcoded Python `_TEMPLATES` dict in `pipeline_template_resolver.py`. It also flips the
> `SCENARIO_ENGINE_INTEGRATION_ENABLED` default to `true` (Tier-B becomes production default) and **deletes**
> the legacy in-process bodies of `lab_resolve_step.py` and `lab_start_step.py` so there is exactly one
> code path at runtime.
>
> **Baseline verification (entering Phase 4):** lablet-controller 569 + 27 ✓ · control-plane-api 1228 ✓ · lcm-core 269 ✓ · scenario-engine 114 ✓.

| Attribute | Value |
|-----------|-------|
| **Sprint** | CSI-Phase4 |
| **Plan (living doc)** | [docs/implementation/cpa-se-integration-plan.md](../cpa-se-integration-plan.md) |
| **Authority** | [ADR-044 Content-Driven Lifecycle Engine](../../architecture/adr/ADR-044-content-driven-lifecycle-engine.md) (Rev 2) |
| **Closes** | G-09 (🔥 Blocker), the `SCENARIO_ENGINE_INTEGRATION_ENABLED` default flip, legacy in-process step body delete |
| **Resolves open questions** | (none directly — defers Q-04 customisation precedence to Q-12; defers Q-10 watchdog) |
| **Services touched** | `src/scenario-engine/` (payload-only, additive), `src/control-plane-api/`, `src/core/`, `src/lablet-controller/`, `docs/` (PAv1 spec + plan), one fixture under `src/lablet-controller/tests/fixtures/` |
| **Tests must pass** | `cd src/core && pytest -q` · `cd src/scenario-engine && make lint && make test` · `cd src/control-plane-api && make lint && make test` · `cd src/lablet-controller && make lint && make test` |
| **Feature flag** | `SCENARIO_ENGINE_INTEGRATION_ENABLED` (lablet-controller `Settings`) — **flipped to `true` by default in Step 10** |

---

## Mode & Session

Run as **`lcm-senior-architect`** agent mode. First action:

```text
mcp_knowledge_recall_session(
  workspace_id: "lablet-cloud-manager",
  focus_hint: "Phase 4 content-driven templates G-09 ContentDrivenTemplateLoader PipelineTemplateResolver chain lifecycle.yaml PAv1 PodDefinitionReadModel lifecycle_phases scenarios flag flip legacy delete"
)

mcp_knowledge_set_focus(
  workspace_id: "lablet-cloud-manager",
  name: "CPA↔SE Phase 4 — content-driven lifecycle templates (G-09) + flag flip + legacy delete",
  description: "Close G-09: ship ContentDrivenTemplateLoader that reads PAv1/lifecycle.yaml via PodDefinitionReadModel; refactor PipelineTemplateResolver into a chain (ContentDriven → DB → Hardcoded); extend SE payload + CPA projection to carry lifecycle_phases + scenarios; flip SCENARIO_ENGINE_INTEGRATION_ENABLED to true; delete legacy in-process bodies of lab_resolve_step and lab_start_step.",
  active_plan: "docs/implementation/cpa-se-integration-plan.md",
  current_phase: "Phase 4 — Content-driven lifecycle templates",
  priority_files: [
    "docs/architecture/content-format/PAv1.md",
    "docs/architecture/content-format/schemas/lifecycle.schema.json",
    "src/scenario-engine/integration/services/cloud_event_client.py",
    "src/scenario-engine/application/commands/sync_content_command.py",
    "src/control-plane-api/domain/read_models/pod_definition_read_model.py",
    "src/control-plane-api/application/commands/pod_definition_read/project_pod_definition_ready_command.py",
    "src/control-plane-api/application/queries/pod_definition_read/get_pod_definition_query.py",
    "src/control-plane-api/api/controllers/pod_definitions_controller.py",
    "src/core/lcm_core/integration/clients/control_plane_client.py",
    "src/lablet-controller/application/services/content_driven_template_loader.py",
    "src/lablet-controller/application/services/pipeline_template_resolver.py",
    "src/lablet-controller/application/hosted_services/lablet_reconciler.py",
    "src/lablet-controller/application/services/step_handlers/lab_resolve_step.py",
    "src/lablet-controller/application/services/step_handlers/lab_start_step.py",
    "src/lablet-controller/application/settings.py"
  ],
  priority_components: ["ContentDrivenTemplateLoader", "PipelineTemplateResolver", "PodDefinitionReadModel", "GetPodDefinitionQuery", "ControlPlaneClient.get_pod_definition"]
)
```

**Pre-existing decisions (do not re-store):** `AD-CSI-001` … `AD-CSI-022` as recorded in
[cpa-se-integration-plan.md §7](../cpa-se-integration-plan.md#7-decision-log). Particularly load into context:

- **AD-CSI-004** — PodDefinition carries first-class typed fields (`lifecycle_phases`, `scenarios`, …) rather than an opaque manifest blob.
- **AD-CSI-007** — CPA's `pod_definitions_read` is a read-only projection of SE state.
- **AD-CSI-008** — Tier-A vs Tier-B step classification (Phase 4 deletes the Tier-A fallback for the Tier-B steps that have already migrated).
- **AD-CSI-015** — Last-write-wins projection with `last_event_at` staleness guard (Step 3 below extends payload but the staleness contract stays).
- **AD-CSI-021** — CPA's `pod_definition.*` CloudEvent ingest is Neuroglia framework-native (`@cloudevent` dataclasses + `IntegrationEventHandler`s in `application/events/integration/scenario_engine_pod_definition_{events,handler}.py`); Step 3 below edits the handler dataclass + handler, **not** a bespoke FastAPI route.
- **AD-CSI-022** — `Settings.scenario_engine_allowed_sources` enforces source allow-list on the same ingest path; new fields added in Step 3 do not change the validation surface.

**New decisions you will record this phase (AD-CSI-023+):**

- **AD-CSI-023** — SE `pod_definition.ready.v1` payload extended (additively) with `lifecycle_phases` + `scenarios`; CPA `PodDefinitionReadModel` gains typed fields with safe defaults.
- **AD-CSI-024** — `PipelineTemplateResolver` becomes a **chain of responsibility**: `ContentDrivenLoader → DBLoader → HardcodedLoader`. First non-empty hit wins; downstream operators (`extends`/`insert_after`/`overrides`/`remove`) still apply to the loaded base.
- **AD-CSI-025** — `PAv1/lifecycle.yaml` is the canonical lifecycle authoring format; one document, top-level key = phase name (`instantiate`, `teardown`, `collect-evidence`, `compute-grading`), value = the same pipeline schema currently used inline in `LabletDefinition.pipelines`. Schema vendored under `lcm_core/infrastructure/content_store/schemas/lifecycle.schema.json`.

---

## Objective

Close the last ADR-044 gap: **all lifecycle pipelines run by lablet-controller come from synced
PAv1 content**, not from compiled Python dicts. The hardcoded `_TEMPLATES` becomes an emergency
fallback only. After Phase 4 a content author can add a new `instantiate` step (e.g. an extra
RADkit health-check) purely by editing `PAv1/lifecycle.yaml`, pushing a new content version, and
letting SE re-sync — **no lablet-controller deploy required**.

```text
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  Content author                                                                      │
│    PAv1/lifecycle.yaml ── { instantiate: { steps: [...] }, teardown: {...}, ... }    │
└──────────────────────────────────────────────────────────────────────────────────────┘
                                       │ S3 upload + lablet-controller sync
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  scenario-engine                                                                     │
│    SyncContentCommand → PAv1Extractor.parse_lifecycle_yaml(...)                      │
│      → PodDefinition.lifecycle_phases = {instantiate: {...}, teardown: {...}}        │
│      → emit_content_synced(... lifecycle_phases=..., scenarios=...)  [AD-CSI-021]    │
└──────────────────────────────────────────────────────────────────────────────────────┘
                                       │ CloudEvent  scenario_engine.pod_definition.ready.v1
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  control-plane-api                                                                   │
│    CloudEventIngestor → ProjectPodDefinitionReadyCommand                             │
│      → PodDefinitionReadModel(lifecycle_phases=…, scenarios=…)                       │
│    GET /api/v1/pod-definitions/{id} → returns lifecycle_phases + scenarios           │
└──────────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  lablet-controller                                                                   │
│    LabletReconciler._resolve_pipeline(instance, pipeline_name)                       │
│      pipeline_def = definition.pipelines.get(pipeline_name)  # may be None           │
│      pipeline_def = PipelineTemplateResolver.resolve(pipeline_def, context=ctx)      │
│         ├── ContentDrivenLoader: GET /pod-definitions/{def.pod_definition_ref.id}    │
│         │     → lifecycle_phases[pipeline_name]  (preferred)                         │
│         ├── DBLoader: definition.pipelines.get(pipeline_name)  (legacy override)     │
│         └── HardcodedLoader: _TEMPLATES["standard-" + pipeline_name]  (fallback)     │
│      PipelineExecutor.run(resolved, ...)  ── Tier-A in-process + Tier-B SE jobs      │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

When `SCENARIO_ENGINE_INTEGRATION_ENABLED=true` (the new default, Step 10), Tier-B steps
`lab_resolve` / `lab_start` always delegate to SE — the legacy in-process bodies deleted in
Step 11 stop existing, eliminating the dual-path maintenance burden.

---

## Implementation Steps (in order)

### Step 1 — `PAv1/lifecycle.yaml` JSON Schema + spec amendment (AD-CSI-023)

**Create** `docs/architecture/content-format/schemas/lifecycle.schema.json`:

```jsonc
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://lcm/schemas/pav1/lifecycle.schema.json",
  "title": "PAv1 lifecycle.yaml",
  "description": "Lifecycle pipeline definitions, one per phase. ADR-044 / AD-CSI-023.",
  "type": "object",
  "additionalProperties": {
    "$ref": "#/$defs/Pipeline"
  },
  "$defs": {
    "Pipeline": {
      "type": "object",
      "required": ["steps"],
      "properties": {
        "description": { "type": "string" },
        "trigger": { "type": "string" },
        "max_retries": { "type": "integer", "minimum": 0 },
        "retry_backoff": { "type": "integer", "minimum": 0 },
        "extends": { "type": "string" },
        "insert_after": { "type": "object" },
        "insert_before": { "type": "object" },
        "overrides": { "type": "object" },
        "remove": { "type": "array", "items": { "type": "string" } },
        "steps": { "type": "array", "items": { "$ref": "#/$defs/Step" } },
        "outputs": { "type": "object" }
      }
    },
    "Step": {
      "type": "object",
      "required": ["name", "handler"],
      "properties": {
        "name": { "type": "string", "pattern": "^[a-z][a-z0-9_]*$" },
        "handler": { "type": "string" },
        "description": { "type": "string" },
        "needs": { "type": "array", "items": { "type": "string" } },
        "skip_when": { "type": "string" },
        "timeout_seconds": { "type": "integer", "minimum": 1 },
        "optional": { "type": "boolean" },
        "retry": {
          "type": "object",
          "properties": {
            "max_attempts": { "type": "integer", "minimum": 1 },
            "delay_seconds": { "type": "integer", "minimum": 0 }
          }
        }
      }
    }
  }
}
```

**Edit** `docs/architecture/content-format/PAv1.md`:

- Add a `lifecycle.yaml` section between the existing `topology.yaml` and `scenarios/` sections.
- Spec the file as **optional**: if absent, lablet-controller falls through to DB-stored
  `definition.pipelines` (next loader in the chain) and finally the hardcoded baseline (so
  legacy PAv1 packages keep working unchanged).
- Provide a worked example covering `instantiate` (mirroring today's `standard-instantiate`),
  `teardown`, `collect-evidence`, and `compute-grading`.
- Cross-link to `lcm_core/infrastructure/content_store/schemas/lifecycle.schema.json` (Step 2 copies the schema there).

**Vendor** the schema into lcm-core: copy the JSON file (verbatim) to
`src/core/lcm_core/infrastructure/content_store/schemas/lifecycle.schema.json` and register
it next to the existing PAv1 schemas (mirror the existing `topology.schema.json` / `scenarios.schema.json`
registration pattern in that directory's `__init__.py`).

**Tests:** `src/core/tests/infrastructure/content_store/test_lifecycle_schema.py` — load the schema with `jsonschema`, validate the worked example from PAv1.md, validate a deliberately broken example fails.

**Acceptance:** schema file lints, `cd src/core && pytest -q` green, PAv1.md renders in MkDocs.

---

### Step 2 — SE: extend `emit_content_synced` payload + `SyncContentCommand` (AD-CSI-021)

**Edit** `src/scenario-engine/integration/services/cloud_event_client.py`:

Extend `emit_content_synced(...)` signature **additively** with two new keyword-only optional fields:

```python
async def emit_content_synced(
    self,
    *,
    pod_definition_id: str,
    name: str,
    version: str,
    pod_type: str,
    content_hash: str,
    lifecycle_phases: dict[str, Any] | None = None,   # NEW
    scenarios: dict[str, Any] | None = None,          # NEW
    callback_url: str | None = None,
) -> None:
```

Include both in the `data` dict only when non-`None` (keeps payload small for content packages without `lifecycle.yaml`).

**Edit** `src/scenario-engine/application/commands/sync_content_command.py`:

At the existing `events.emit_content_synced(...)` call site, forward `lifecycle_phases=pod_def.lifecycle_phases, scenarios=pod_def.scenarios`. `pod_def.scenarios` and `pod_def.lifecycle_phases` already exist (Phase 0 G-03).

**Tests:** extend `src/scenario-engine/tests/unit/test_sync_content_command.py`:

- A new test asserts the emitted kwargs include `lifecycle_phases` + `scenarios` when present in the parsed PAv1 package.
- A new test asserts both keys are **absent** from `data` when the parsed PAv1 has neither (legacy packages).

**Acceptance:** `cd src/scenario-engine && make lint && make test` green. **No** changes to `emit_sync_failed` or the DSL executor.

---

### Step 3 — CPA: extend projection + read model with typed `lifecycle_phases` + `scenarios`

**Edit** `src/control-plane-api/domain/read_models/pod_definition_read_model.py`:

Add two fields with safe defaults (preserve existing `raw_event` field for audit):

```python
lifecycle_phases: dict[str, Any] | None = None
scenarios: dict[str, Any] | None = None
```

**Edit** `src/control-plane-api/application/commands/pod_definition_read/project_pod_definition_ready_command.py`:

- Add `lifecycle_phases: dict[str, Any] | None = None` and `scenarios: dict[str, Any] | None = None` to `ProjectPodDefinitionReadyCommand`.
- In `handle_async`, copy both onto `PodDefinitionReadModel(...)`.
- Preserve **AD-CSI-015** staleness guard semantics exactly — the new fields participate in last-write-wins but do not change the comparison.

**Edit** `src/control-plane-api/application/events/integration/scenario_engine_pod_definition_events.py` (the `@cloudevent`-decorated `ScenarioEnginePodDefinitionReadyIntegrationEventV1` dataclass landed by G-13 / AD-CSI-021): add the two new optional fields `lifecycle_phases: dict[str, Any] | None = None` and `scenarios: dict[str, Any] | None = None`. **Edit** the matching handler `ScenarioEnginePodDefinitionReadyHandler` in `scenario_engine_pod_definition_handler.py` to forward both fields into `ProjectPodDefinitionReadyCommand(...)` via `getattr(event, "lifecycle_phases", None)` / `getattr(event, "scenarios", None)` (AD-CSI-021 gotcha: `CloudEventIngestor` bypasses `__init__`, so dataclass defaults are not applied — use `getattr`). _Note: CPA's SE-event ingest is now Neuroglia framework-native per AD-CSI-021, so this edit is to the `IntegrationEventHandler` dataclass + handler, not to any bespoke FastAPI route. The previous bespoke `EventsController.ingest_cloud_event` POST and its `CE_POD_DEFINITION_READY` branch were deleted as part of G-13._

**Edit** `src/control-plane-api/integration/repositories/motor_pod_definition_read_repository.py`:

- Update `_to_model(...)` / `_to_document(...)` (whichever names the file uses) so the two new fields round-trip through MongoDB.

**Edit** `src/control-plane-api/application/queries/pod_definition_read/get_pod_definition_query.py`:

- Extend `PodDefinitionReadDto` with both fields.
- Update `from_model(...)` to copy them.

**Tests:**

- `src/control-plane-api/tests/unit/application/commands/pod_definition_read/test_project_pod_definition_ready_with_lifecycle.py` — project an event with `lifecycle_phases` + `scenarios`, assert they land on the read model; projection without them leaves both `None`.
- `src/control-plane-api/tests/unit/integration/repositories/test_motor_pod_definition_read_repository_round_trip.py` — extend to assert both fields round-trip.
- `src/control-plane-api/tests/unit/application/queries/pod_definition_read/test_get_pod_definition_query.py` — extend to assert DTO carries both fields.

**Acceptance:** `cd src/control-plane-api && make lint && make test` green.

---

### Step 4 — CPA: expose `GetPodDefinitionQuery` via REST controller

`GetPodDefinitionQueryHandler` is already shipped but has **no controller route** exposing it
(verified during phase-3 inventory). Phase 4 needs it because `ContentDrivenTemplateLoader`
fetches the read model over HTTP via lcm-core.

**Create** `src/control-plane-api/api/controllers/pod_definitions_controller.py`:

```python
from neuroglia.mvc import ControllerBase, get

from application.queries.pod_definition_read.get_pod_definition_query import (
    GetPodDefinitionQuery,
    PodDefinitionReadDto,
)


class PodDefinitionsController(ControllerBase):
    """Read-only access to the CPA-side projection of SE PodDefinition state.

    ADR-044 / G-09 / AD-CSI-007.
    """

    @get("/{pod_definition_id}", response_model=PodDefinitionReadDto)
    async def get_pod_definition(self, pod_definition_id: str):
        result = await self.mediator.execute_async(
            GetPodDefinitionQuery(pod_definition_id=pod_definition_id)
        )
        return self.process(result)
```

Neuroglia auto-prefixes `/pod-definitions`; the mounted API SubApp adds `/api/v1`. Final URL:
`GET /api/v1/pod-definitions/{pod_definition_id}`.

Authentication: this is a public read-model endpoint used by **lablet-controller** over the
internal network. Reuse the existing `EventsController` / `InternalController` authentication
pattern — verify whether the project uses an internal-token middleware or just network isolation
and follow the precedent. Do **not** invent a new scheme.

**Tests:** `src/control-plane-api/tests/integration/api/test_pod_definitions_controller.py`:

- 200 happy path (seeded read model).
- 404 when id unknown (handler already returns `not_found`).
- DTO shape includes `lifecycle_phases` + `scenarios`.

---

### Step 5 — lcm-core: `ControlPlaneClient.get_pod_definition`

**Edit** `src/core/lcm_core/integration/clients/control_plane_client.py`:

Add (mirroring the shape of existing methods like `get_lablet_session`):

```python
async def get_pod_definition(self, pod_definition_id: str) -> dict[str, Any]:
    """Fetch the CPA-side projection of a SE PodDefinition.

    Returns the raw JSON dict (callers care about ``lifecycle_phases`` /
    ``scenarios``; full DTO shape lives in ``PodDefinitionReadDto``). Raises
    ``ControlPlaneClientError`` on transport / 5xx errors and
    ``ControlPlaneNotFoundError`` on 404.
    """
    return await self._request(
        "GET",
        f"/api/v1/pod-definitions/{pod_definition_id}",
    )
```

Match the error-mapping pattern of the surrounding methods (404 → not-found exception, 5xx → retry-able error, transport → wrap).

**Tests:** `src/core/tests/integration/clients/test_control_plane_client_get_pod_definition.py` (or extend the existing client test module). Use `httpx.MockTransport`:

- Happy 200 with a full DTO payload returns the dict.
- 404 raises `ControlPlaneNotFoundError`.
- 500 raises `ControlPlaneClientError`.
- Transport error wrapped.

**Acceptance:** `cd src/core && pytest -q && ruff check` green.

---

### Step 6 — lablet-controller: `ContentDrivenTemplateLoader`

**Create** `src/lablet-controller/application/services/content_driven_template_loader.py`:

```python
"""ContentDrivenTemplateLoader — load lifecycle pipelines from CPA's PodDefinition projection.

ADR-044 / G-09 / AD-CSI-022. First link of the PipelineTemplateResolver chain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from lcm_core.integration.clients.control_plane_client import (
    ControlPlaneClient,
    ControlPlaneNotFoundError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TemplateLookupContext:
    """Carries everything the chain needs to look up a template.

    Built by ``LabletReconciler._resolve_pipeline`` immediately before calling
    ``PipelineTemplateResolver.resolve(...)``.
    """

    pipeline_name: str
    definition_id: str
    pod_definition_id: str | None


class ContentDrivenTemplateLoader:
    """Fetches ``lifecycle_phases[pipeline_name]`` from the CPA PodDefinition read model.

    Returns ``None`` when:
    - the definition has no ``pod_definition_ref`` yet (e.g. legacy seed),
    - CPA returns 404 (read model not yet projected),
    - the projection has no ``lifecycle_phases`` (legacy PAv1 package),
    - the requested ``pipeline_name`` is not in ``lifecycle_phases``.

    All ``None`` returns let the chain fall through to the next loader.
    """

    def __init__(self, control_plane_client: ControlPlaneClient) -> None:
        self._client = control_plane_client

    async def load(self, ctx: TemplateLookupContext) -> dict[str, Any] | None:
        if ctx.pod_definition_id is None:
            logger.debug(
                "ContentDrivenLoader: no pod_definition_id for definition %s — falling through",
                ctx.definition_id,
            )
            return None

        try:
            pod_def = await self._client.get_pod_definition(ctx.pod_definition_id)
        except ControlPlaneNotFoundError:
            logger.info(
                "ContentDrivenLoader: PodDefinition %s not yet projected — falling through",
                ctx.pod_definition_id,
            )
            return None
        except Exception:
            logger.exception(
                "ContentDrivenLoader: failed to fetch PodDefinition %s — falling through",
                ctx.pod_definition_id,
            )
            return None

        lifecycle = (pod_def or {}).get("lifecycle_phases") or {}
        pipeline_def = lifecycle.get(ctx.pipeline_name)
        if not pipeline_def:
            return None

        logger.info(
            "ContentDrivenLoader: matched '%s' for PodDefinition %s (definition=%s)",
            ctx.pipeline_name,
            ctx.pod_definition_id,
            ctx.definition_id,
        )
        return pipeline_def
```

**Tests:** `src/lablet-controller/tests/unit/application/services/test_content_driven_template_loader.py`:

- Returns `None` when `pod_definition_id is None`.
- Returns `None` on `ControlPlaneNotFoundError`.
- Returns `None` on transport error (logged, swallowed).
- Returns `None` when `lifecycle_phases` missing or empty.
- Returns `None` when phase not in `lifecycle_phases`.
- Returns the pipeline dict on happy path.

---

### Step 7 — lablet-controller: refactor `PipelineTemplateResolver` into a chain (AD-CSI-022)

**Edit** `src/lablet-controller/application/services/pipeline_template_resolver.py`:

Keep `_TEMPLATES`, `PipelineTemplateError`, `_apply_removes`/`_apply_inserts_*`/`_apply_overrides`,
and the **existing** `resolve(pipeline_def)` signature for backward-compat (Tier-A tests still call it).

Add a new async entry point:

```python
async def resolve_for(
    self,
    pipeline_def: dict[str, Any] | None,
    *,
    context: TemplateLookupContext,
) -> dict[str, Any] | None:
    """Chain-of-responsibility template resolution. AD-CSI-022.

    Order:
      1. ``ContentDrivenLoader`` (if injected) — PAv1 lifecycle.yaml.
      2. ``pipeline_def`` itself (DB-stored override from ``LabletDefinition.pipelines``).
      3. Hardcoded ``_TEMPLATES["standard-<pipeline_name>"]`` baseline.

    First non-empty hit becomes the *base*; downstream operators (``extends``,
    ``insert_after``, ``insert_before``, ``overrides``, ``remove``) from
    ``pipeline_def`` (when present) still apply to whatever base was selected.
    """
```

Implementation outline:

1. If `self._content_driven_loader is not None`, call `await self._content_driven_loader.load(context)`; if non-empty, use it as the base.
2. Else if `pipeline_def` is non-empty and lacks `extends`, use `pipeline_def` itself (current behaviour for inline DB pipelines).
3. Else if `pipeline_def` has `extends`, resolve as today via `_load_template`.
4. Else fall through to `_TEMPLATES["standard-" + context.pipeline_name]` (last-ditch).
5. Then apply DB-side operators (`pipeline_def`'s `insert_after`/`insert_before`/`overrides`/`remove`/top-level fields/outputs) on top of the base.

Constructor signature change:

```python
def __init__(
    self,
    extra_templates: dict[str, dict[str, Any]] | None = None,
    content_driven_loader: ContentDrivenTemplateLoader | None = None,
) -> None:
```

Keep the existing sync `resolve(pipeline_def)` as a thin wrapper that builds an empty
`TemplateLookupContext` (no `pod_definition_id`) and reuses the chain — it must remain
sync-callable for the handful of unit tests that exercise the operators alone, **OR**
refactor those tests to the new async API (recommended; preserves a single code path).

**Edit** `src/lablet-controller/application/hosted_services/lablet_reconciler.py` at line ≈215:

- Inject `ControlPlaneClient` (already a constructor param — verify) and build a
  `ContentDrivenTemplateLoader(control_plane_client)`.
- Pass it to `PipelineTemplateResolver(content_driven_loader=loader)`.

**Edit** `_resolve_pipeline(...)` at line ≈944 to call the new async entry point:

```python
ctx = TemplateLookupContext(
    pipeline_name=pipeline_name,
    definition_id=instance.definition_id,
    pod_definition_id=(
        definition.pod_definition_ref.definition_id
        if getattr(definition, "pod_definition_ref", None)
        else None
    ),
)
try:
    pipeline_def = await self._template_resolver.resolve_for(
        pipeline_def, context=ctx
    )
except Exception:
    logger.exception(
        "Failed to resolve pipeline template for '%s' in definition %s — using raw definition",
        pipeline_name, instance.definition_id,
    )
```

**Tests:** `src/lablet-controller/tests/unit/application/services/test_pipeline_template_resolver_chain.py`:

- Content-driven hit short-circuits DB + hardcoded.
- Content-driven miss + DB inline → DB inline wins.
- Content-driven miss + DB `extends` → hardcoded template + DB operators applied.
- Content-driven miss + DB missing + hardcoded match (just `pipeline_name="instantiate"`) → hardcoded.
- Content-driven hit + DB `insert_after` → operators still applied to content-driven base.
- Existing operator tests for `_apply_*` continue to pass unchanged.

---

### Step 8 — Reference fixture `pav1_with_lifecycle.zip`

**Create** `src/lablet-controller/tests/fixtures/pav1_with_lifecycle.zip` containing a minimal
PAv1 package that mirrors the existing `standard-instantiate` (so the test can assert
parity with the hardcoded baseline):

```
PAv1/
  mosaic_meta.json           # name, version, pod_type=cml_on_aws
  topology.yaml              # tiny 2-node CML topology
  lifecycle.yaml             # instantiate + teardown phases
  scenarios/                 # empty or 1 placeholder scenario
  devices.json
  grade.xml
```

`lifecycle.yaml` content (verbatim mirrors today's `_TEMPLATES["standard-instantiate"]` steps,
proves chain semantics):

```yaml
instantiate:
  description: "Standard lab instantiation pipeline (sourced from content)"
  trigger: "on_status:instantiating"
  max_retries: 3
  retry_backoff: 30
  steps:
    - name: lab_resolve
      handler: lab_resolve
      timeout_seconds: 120
      retry: {max_attempts: 2, delay_seconds: 10}
    - name: ports_alloc
      handler: ports_alloc
      needs: [lab_resolve]
      skip_when: "not $DEFINITION.port_template"
      timeout_seconds: 30
    # ... mirror remaining steps verbatim ...
  outputs:
    cml_lab_id: "$STEPS.lab_resolve.cml_lab_id"
    lab_record_id: "$STEPS.lab_resolve.lab_record_id"
    launch_url: "$STEPS.lds_provision.launch_url"
teardown:
  description: "Standard teardown pipeline (sourced from content)"
  trigger: "on_status:stopping"
  steps:
    # ... mirror standard-teardown ...
```

The fixture is consumed by Step 9's E2E test and by Step 12's seed migration.

---

### Step 9 — End-to-end test

**Create** `src/lablet-controller/tests/integration/services/test_content_driven_template_resolver.py`:

- Spin up the chain with a stubbed `ControlPlaneClient` returning a `PodDefinitionReadDto`-shaped
  dict whose `lifecycle_phases` was extracted from `pav1_with_lifecycle.zip`.
- Call `resolver.resolve_for(pipeline_def=None, context=TemplateLookupContext("instantiate", "def-id", "pod-id"))`.
- Assert the resolved pipeline's `steps` matches the hardcoded baseline (step-by-step equivalence
  guarantees no regression when the flag/fixture pair lands in production seeds).
- Assert a second call with `pipeline_name="teardown"` resolves equivalently.
- Assert a third call with `pod_definition_id=None` falls through to the hardcoded baseline.

---

### Step 10 — Flip `SCENARIO_ENGINE_INTEGRATION_ENABLED` default to `true`

**Edit** `src/lablet-controller/application/settings.py`:

```python
scenario_engine_integration_enabled: bool = True   # was False (Phase 3 default)
```

**Update** the doc-string comment and any inline help text to reflect that this is now
production behaviour; an operator may set the env var to `false` only as an emergency
break-glass during incident response.

**Tests:** any settings tests asserting the default `False` must flip; smoke-test that
`pipeline_executor` and `lab_resolve_step` / `lab_start_step` paths still resolve under the new default
in their unit tests (they should — they already branch on the flag and the Tier-B path is the
tested branch in phase 3).

**Edit** `docker-compose.yml` (root) + `deployment/docker-compose/docker-compose.prod.yml*` —
remove any explicit `SCENARIO_ENGINE_INTEGRATION_ENABLED=true` overrides (they were Phase 3
opt-ins) so the new default is the single source of truth. Keep one example commented-out
`SCENARIO_ENGINE_INTEGRATION_ENABLED=false` line per `.env.example` for operators who need
the break-glass.

---

### Step 11 — Delete legacy in-process bodies (G-05 cleanup)

**Edit** `src/lablet-controller/application/services/step_handlers/lab_resolve_step.py`:

- Drop the legacy block from `# ── Legacy in-process path (Tier-A) ─────` through the
  function end (lines ≈80–170 today).
- The handler becomes: validate `topology_yaml`, then unconditionally call
  `submit_scenario_engine_job(...)`. The `context.scenario_engine_enabled` branch disappears
  entirely (the flag is no longer consulted by this handler; it remains in `Settings` only
  as the break-glass switch — which now disables Tier-B by raising in the SE step adapter or
  by short-circuiting at `PipelineContext` construction; pick the latter for clarity).
- Delete `context.resolve_lab_for_instance`, `context.find_lab_record_id`,
  `context.register_lab_record`, `context.cml.import_lab`, `context.cml.get_lab`,
  `context.api.get_lab_records_for_worker` usage from this file.

**Edit** `src/lablet-controller/application/services/step_handlers/lab_start_step.py` analogously.

**Audit** `src/lablet-controller/application/models/pipeline_context.py`: any attributes used
**only** by the deleted legacy bodies (e.g. `resolve_lab_for_instance` callback,
`register_lab_record` callback, `freshly_imported_sessions`) must also be deleted from
`PipelineContext` — track call sites with grep before removing. Whatever is still used by
Tier-A steps (`ports_alloc`, `tags_sync`, `lab_binding`, `mark_ready`, …) stays.

**Tests:** delete `test_lab_resolve_step_legacy_*` and `test_lab_start_step_legacy_*` files
(or whichever names cover the Tier-A paths). Tier-B tests stay green.

**Acceptance:** `cd src/lablet-controller && make lint && make test` green; static analysis
reports zero unreferenced helpers from the deleted code path.

---

### Step 12 — Migrate canonical CML lablet seed

**Edit** `src/lablet-controller/config/seeds/<canonical-cml-lablet-seed>.yaml`
(or wherever the production seed lives — verify via `grep -r 'cml_on_aws' src/lablet-controller/config/`):

- Replace the inline `pipelines:` block (or augment, if you keep DB pipelines as override
  hooks) with a reference that lifecycle is now sourced from PAv1 content.
- Update the seed's PAv1 fixture (or the upstream Mosaic content reference) to include a
  `PAv1/lifecycle.yaml` shipping the same `standard-instantiate` and `standard-teardown`
  steps used in Step 8's fixture.
- After re-sync the runtime path is: `ContentDrivenLoader` → matches → no DB operators →
  hardcoded fallback never consulted.

If the canonical seed lives outside this repo (Mosaic content), open a TODO line item in
`docs/implementation/cpa-se-integration-plan.md §6 Phase 4 ▸ Deferrals` describing the
external action required.

---

### Step 13 — Final verification

```bash
cd src/core              && .venv/bin/pytest -q && .venv/bin/ruff check
cd src/scenario-engine   && make lint && make test
cd src/control-plane-api && make lint && make test
cd src/lablet-controller && make lint && make test
```

All four suites green. Then a manual smoke test:

```bash
make dev   # full stack with SCENARIO_ENGINE_INTEGRATION_ENABLED defaulting to true
# Seed a CML lablet whose PAv1 zip contains lifecycle.yaml.
# Trigger instantiate; tail logs:
#   - lablet-controller:    ContentDrivenLoader matched 'instantiate' for PodDefinition <id>
#   - lablet-controller:    lab_resolve: delegating to Scenario Engine
#   - scenario-engine:      executing scenario lab_resolve@v1
#   - lablet-controller:    events_controller: job.completed → resume step
```

---

### Step 14 — Plan + knowledge updates

**Edit** `docs/implementation/cpa-se-integration-plan.md`:

- §1 banner: flip Phase 4 from "next" to `🟢 Complete` with the test-count line.
- §2.4 inventory (lablet-controller): mark `pipeline_template_resolver.py` 🟢 with the
  chain-of-responsibility note; mark `content_driven_template_loader.py` (new) 🟢; mark
  `lab_resolve_step.py` / `lab_start_step.py` 🟢 with "(legacy body removed Phase 4)".
- §2.x SE inventory: mark `cloud_event_client.py::emit_content_synced` 🟢 with `lifecycle_phases` + `scenarios` note.
- §2.x CPA inventory: mark `pod_definition_read_model.py` + `project_pod_definition_ready_command.py` + `get_pod_definition_query.py` rows with the typed-fields delta; add `pod_definitions_controller.py` row.
- §6 Phase 4 bullets all ticked.
- §7 decision log: append AD-CSI-021, AD-CSI-022, AD-CSI-023 (and any further).
- §8 open questions: append **Q-12** (template precedence) and **Q-13** (lifecycle authoring tooling — out of scope, but worth tracking).

**Update** `CHANGELOG.md` `Unreleased` section with a Phase 4 entry block.

**Knowledge Manager calls during the session:**

- After each Step: `mcp_knowledge_update_task` with `title: "Phase 4: Content-driven templates + flag flip + legacy delete (G-09)"`.
- For each new architecturally important file (`content_driven_template_loader.py`,
  `pod_definitions_controller.py`, `lifecycle.schema.json`): `mcp_knowledge_add_file_context`.
- Record AD-CSI-021, AD-CSI-022, AD-CSI-023 via `mcp_knowledge_store_decision`.

---

## Out of scope for Phase 4 (do NOT implement here)

- ❌ Migrating remaining Tier-B steps (`lab_stop`, `lab_wipe`, `collect_grade`, `score_report`) — Phase 5 (G-10).
- ❌ Scheduler `pod_type` filter — Phase 6 (G-11).
- ❌ Suspended-step watchdog (Q-10) — still deferred.
- ❌ Lifecycle authoring CLI / linter for content authors — record as Q-13.
- ❌ Versioning the `lifecycle.schema.json` itself (`$id` already includes `pav1`; bump only when v2 lands).
- ❌ Changing `_TEMPLATES` dict shape — keep as last-ditch fallback; remove only when **all** canonical seeds ship a `lifecycle.yaml` and we have a runtime metric proving the fallback is never hit (track as Q-13 follow-up).
- ❌ Reworking `pod_definition_sync_failed` event payload — Phase 4 touches only the **ready** payload.
- ❌ Any change to SE scenarios (`lab_resolve_scenario.py`, `lab_start_scenario.py`).

If you find yourself touching files outside the **Implementation Steps** list above, **stop** and
update the master plan §3 with a new gap or open question first.

---

## Open questions for Phase 4

- **Q-12 (NEW)** — Precedence when **both** content-driven (`PAv1/lifecycle.yaml`) **and** DB-stored
  (`LabletDefinition.pipelines`) supply a pipeline of the same name. AD-CSI-022 picks content-driven
  first, but DB operators (`insert_after`, `overrides`, …) still apply on top. Is that what content
  authors actually want, or should DB-side overrides **replace** the content-driven base entirely?
  Defer resolution; ship AD-CSI-022 as the conservative "operators always apply" stance.
- **Q-13 (NEW)** — Authoring tooling: do we ship a `lcm lint-pav1` CLI that runs the
  `lifecycle.schema.json` validation locally before content authors push to Mosaic? Out of scope
  for Phase 4 implementation; record so it does not get lost.

---

## Knowledge Manager hygiene during the session

After each Step, call `mcp_knowledge_update_task` with the Phase 4 title and the appropriate
`status`. For each architecturally important new file, call `mcp_knowledge_add_file_context`
with `purpose`, `key_exports`, `patterns_used`.

Record AD-CSI-021, AD-CSI-022, AD-CSI-023 (and any further AD-CSI-NN you raise) via
`mcp_knowledge_store_decision` **and** append to `cpa-se-integration-plan.md §7`. Open
questions go via `mcp_knowledge_store_insight` (insight_type=`gotcha` or `constraint`) **and**
into §8.

---

## Definition of Done — Phase 4

- [ ] `PAv1/lifecycle.yaml` JSON Schema shipped at `docs/architecture/content-format/schemas/lifecycle.schema.json` and vendored under `lcm_core/infrastructure/content_store/schemas/`
- [ ] `docs/architecture/content-format/PAv1.md` documents `lifecycle.yaml` with worked example
- [ ] SE `emit_content_synced(...)` forwards `lifecycle_phases` + `scenarios` (AD-CSI-021); tests cover both presence + absence
- [ ] `SyncContentCommandHandler` populates both fields on the emitted event
- [ ] CPA `PodDefinitionReadModel` gains typed `lifecycle_phases` + `scenarios` (safe defaults)
- [ ] `ProjectPodDefinitionReadyCommand` projects both; `PodDefinitionReadDto` returns both
- [ ] Mongo repo round-trip covered for both new fields
- [ ] `PodDefinitionsController` exposes `GET /api/v1/pod-definitions/{id}`; auth follows precedent; 200/404 covered
- [ ] `ControlPlaneClient.get_pod_definition(...)` shipped with httpx.MockTransport tests
- [ ] `ContentDrivenTemplateLoader` shipped with full unit coverage (6 cases minimum)
- [ ] `PipelineTemplateResolver` refactored into chain-of-responsibility (AD-CSI-022) preserving operator semantics
- [ ] `LabletReconciler._resolve_pipeline` switched to `resolve_for(pipeline_def, context=…)`
- [ ] Reference fixture `pav1_with_lifecycle.zip` shipped under lablet-controller tests
- [ ] E2E test demonstrates content-driven `instantiate` resolves to step-by-step parity with hardcoded baseline
- [ ] `SCENARIO_ENGINE_INTEGRATION_ENABLED` default flipped to `true`; settings + docker-compose updated
- [ ] Legacy in-process bodies of `lab_resolve_step.py` + `lab_start_step.py` deleted; tests pruned; `PipelineContext` callbacks no longer referenced are removed
- [ ] Canonical CML lablet seed migrated to ship `PAv1/lifecycle.yaml` (or external TODO recorded)
- [ ] `cd src/core && pytest -q && ruff check` green
- [ ] `cd src/scenario-engine && make lint && make test` green
- [ ] `cd src/control-plane-api && make lint && make test` green
- [ ] `cd src/lablet-controller && make lint && make test` green
- [ ] Master plan §1 banner flipped to "Phase 4 complete; **Phase 5 next**"
- [ ] Master plan §6 Phase 4 bullets ticked with verification line
- [ ] Master plan §7 has AD-CSI-021 + AD-CSI-022 + AD-CSI-023 appended
- [ ] Master plan §8 has Q-12 + Q-13 added
- [ ] `CHANGELOG.md Unreleased` section has a Phase 4 block
