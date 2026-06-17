# Bootstrap Prompt: CPA↔SE Integration — Phase 3 Tier-B steps + CloudEvent → pipeline resumption

> **� Status: Complete.** All 5 waves landed. G-05 (Tier-B step delegation) and G-06 (CloudEvent → pipeline
> resumption) are closed; behaviour is still gated by `scenario_engine_integration_enabled` (default
> `false`) so the legacy in-process path remains the production default until Phase 4 flips the flag. CPA's
> `LabletDefinitionDto` now exposes `pod_definition_ref` (the prior read-path gap that would have left the
> Tier-B branch always falling back). New decisions: AD-CSI-016 (in-process registry of suspended handlers
> on `LifecyclePhaseHandler`) and AD-CSI-017 (SE round-trips `metadata` on every job lifecycle event). New
> open questions: Q-10 (suspended-step watchdog) and Q-11 (CloudEvent ingest source allow-list).
>
> **Verification (final):** lablet-controller 546 ✓ · control-plane-api 1228 ✓ · lcm-core 269 ✓ · scenario-engine 114 ✓.>
> **📢 Post-Phase-3 refactor (AD-CSI-020).** The bespoke `src/lablet-controller/api/controllers/events_controller.py`
> described throughout this prompt (Steps 6, 8, etc.) was **subsequently deleted** and replaced by
> Neuroglia's framework-native CloudEvent pipeline: 5 `@cloudevent`-decorated dataclasses in
> `src/lablet-controller/application/events/integration/scenario_engine_events.py` + 5
> `IntegrationEventHandler`s in `scenario_engine_handler.py`, auto-discovered via
> `Mediator.configure(builder, ["application.events.integration"])` +
> `CloudEventIngestor.configure(builder, ["application.events.integration"])` in `main.py`. Source
> allow-list enforcement moved into a per-handler `_source_allowed(...)` helper (AD-CSI-019, closes Q-11).
> When reading the steps below, treat "`EventsController`" as the historical shape that was implemented
> first — the equivalent current code lives in `application/events/integration/`. CPA's own
> `EventsController` (used for `pod_definition.ready.v1` ingest, G-12) was **not** part of this refactor
> and still exists as a bespoke FastAPI router today.
| Attribute | Value |
|-----------|-------|
| **Sprint** | CSI-Phase3 |
| **Plan (living doc)** | [docs/implementation/cpa-se-integration-plan.md](../cpa-se-integration-plan.md) |
| **Authority** | [ADR-044 Content-Driven Lifecycle Engine](../../architecture/adr/ADR-044-content-driven-lifecycle-engine.md) (Rev 2) |
| **Closes** | G-05 (🔥 Blocker), G-06 (🔥 Blocker) |
| **Resolves open questions** | Q-01 (deterministic vs random `pod_definition_id` — proposed deterministic), one or two new Q-NN raised during implementation |
| **Services touched** | `src/lablet-controller/`, `src/control-plane-api/` (do **not** touch `scenario-engine` — its job CloudEvent payload + scenario contracts for `lab_resolve@v1` / `lab_start@v1` are the contract) |
| **Tests must pass** | `cd src/core && pytest -q` · `cd src/lablet-controller && make lint && make test` · `cd src/control-plane-api && make lint && make test` |
| **Feature flag** | `SCENARIO_ENGINE_INTEGRATION_ENABLED` (existing, lablet-controller `Settings`, default still **`false`**) — Tier-B step replacement is opt-in for Phase 3; Phase 4 will flip the default after content-driven templates land |

---

## Mode & Session

Run as **`lcm-senior-architect`** agent mode. First action:

```text
mcp_knowledge_recall_session(
  workspace_id: "lablet-cloud-manager",
  focus_hint: "Phase 3 lablet-controller ScenarioEngineStep TierB pipeline executor StepResult suspended events_controller CloudEvent job lifecycle ResumePipelineStepCommand FailPipelineStepCommand"
)

mcp_knowledge_set_focus(
  workspace_id: "lablet-cloud-manager",
  name: "CPA↔SE Phase 3 Tier-B steps + CloudEvent resumption",
  description: "Introduce ScenarioEngineStep base; rewrite lab_resolve/lab_start step handlers as Tier-B; extend PipelineExecutor to honour StepResult.suspended; implement the 5 job-lifecycle handlers in lablet-controller events_controller; add ResumePipelineStepCommand + FailPipelineStepCommand to CPA. All behind SCENARIO_ENGINE_INTEGRATION_ENABLED.",
  active_plan: "docs/implementation/cpa-se-integration-plan.md",
  current_phase: "Phase 3 — Pipeline ↔ SE delegation (Tier-B steps)",
  priority_files: [
    "src/lablet-controller/application/services/step_handlers/_scenario_engine_step.py",
    "src/lablet-controller/application/services/step_handlers/lab_resolve_step.py",
    "src/lablet-controller/application/services/step_handlers/lab_start_step.py",
    "src/lablet-controller/application/services/step_registry.py",
    "src/lablet-controller/application/services/pipeline_executor.py",
    "src/lablet-controller/application/services/lifecycle_phase_handler.py",
    "src/lablet-controller/api/controllers/events_controller.py",
    "src/lablet-controller/integration/services/scenario_engine_client.py",
    "src/lablet-controller/application/settings.py",
    "src/control-plane-api/application/commands/lablet_session/resume_pipeline_step_command.py",
    "src/control-plane-api/application/commands/lablet_session/fail_pipeline_step_command.py",
    "src/control-plane-api/application/commands/lablet_session/update_pipeline_progress_command.py"
  ],
  priority_components: ["ScenarioEngineStep", "PipelineExecutor", "EventsController", "ResumePipelineStepCommand", "FailPipelineStepCommand"]
)
```

**Pre-existing decisions (do not re-store):** `AD-CSI-001` … `AD-CSI-015` as recorded in
[cpa-se-integration-plan.md §7](../cpa-se-integration-plan.md#7-decision-log). Particularly load into context:

- **AD-CSI-005** Mediator-only CloudEvent handlers (no direct repository writes from `events_controller`).
- **AD-CSI-008** Tier-A vs Tier-B step classification (which steps move, which stay).
- **AD-CSI-009** Suspension/resumption uses `StepResult.suspended` + CloudEvent — this is the canonical pattern you implement here.

**New decisions you will record this phase (AD-CSI-016+):**

- The exact `StepResult.suspended(...)` shape (`reason`, `external_job_id`, `step_correlation_id`).
- Resumption identity: how the CloudEvent matches back to the suspended step (proposed: `subject = job_id`; lookup via `pipeline_execution_record.external_jobs[].job_id`).
- Watchdog timeout strategy (mentioned in §9 Risks — kept out of scope here or shipped as a small primer; decide).

---

## Objective

Close the runtime delegation loop:

```text
┌────────────────────────────────────────────────────────────────────────────────┐
│  control-plane-api                                                             │
│    LabletSession[phase=instantiate, pipeline=standard-instantiate]             │
│        │                                                                       │
│        ▼                                                                       │
│    StartInstantiationCommand → writes /lcm/sessions/{id}/desired_state         │
└────────────────────────────────────────────────────────────────────────────────┘
                              │  etcd watch
                              ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│  lablet-controller                                                             │
│    LifecyclePhaseHandler ── PipelineExecutor.run(template, existing_progress)  │
│        │                                                                       │
│        ▼  for each step in topological order                                   │
│    @step_handler("lab_resolve")  ──── *NEW: ScenarioEngineStep* ───────────┐   │
│      build_input(ctx) → SE.submit_job(scenario="lab_resolve@v1",           │   │
│                                       input_data=…,                        │   │
│                                       pod_definition_id=…,                 │   │
│                                       callback_url=settings.callback_url)  │   │
│      → record external_job_id on pipeline_execution_record                 │   │
│      → return StepResult.suspended(job_id=…, correlation_id=…)             │   │
│    PipelineExecutor sees SUSPENDED → persist progress → release the task   │   │
└────────────────────────────────────────────────────────────────────────────────┘
                              ▲                                 │
                              │ CloudEvent                      ▼
                              │  scenario_engine.job.completed.v1  ──> SE runs the scenario
                              │
┌────────────────────────────────────────────────────────────────────────────────┐
│  lablet-controller  (existing events_controller, currently TODO)               │
│    POST /events  →  parse CloudEvent  →  dispatch via Mediator:                │
│      • job.started        → log + (optional) audit command                     │
│      • job.progress       → UpdatePipelineProgressCommand   (already in CPA)   │
│      • job.completed      → ResumePipelineStepCommand       (NEW in CPA)       │
│      • job.failed         → FailPipelineStepCommand         (NEW in CPA)       │
│      • job.cancelled      → FailPipelineStepCommand(reason="cancelled")        │
│                                                                                │
│    ResumePipelineStepCommand handler:                                          │
│      • mark step COMPLETED on pipeline_execution_record                        │
│      • merge job output into step result_data                                  │
│      • signal the suspended LifecyclePhaseHandler task to wake                 │
│        (etcd write OR in-process asyncio.Event registry — see Step 5)          │
└────────────────────────────────────────────────────────────────────────────────┘
```

After Phase 3, a `standard-instantiate` run with `SCENARIO_ENGINE_INTEGRATION_ENABLED=true`:

1. Reaches the `lab_resolve` step → submits SE Job → step transitions `RUNNING → SUSPENDED`.
2. SE executes the registered Python `lab_resolve@v1` scenario → emits `scenario_engine.job.completed.v1`.
3. lablet-controller's `events_controller` ingests → mediator → `ResumePipelineStepCommand` → step is `COMPLETED` and its `result_data` populated from the event payload.
4. The pipeline executor resumes and dispatches the next step (`ports_alloc`, which stays Tier-A).
5. Same flow at `lab_start`.

When the flag is **off**, the existing in-process step handlers run unchanged (current behaviour preserved).

---

## Implementation Steps (in order)

### Step 1 — `StepResult.suspended(...)` (G-05 part 1)

**Edit** `src/lablet-controller/application/services/step_registry.py`:

- Extend the existing `status` literal:

  ```python
  status: str  # "completed" | "skipped" | "failed" | "suspended"
  ```

- Add two fields to the dataclass:

  ```python
  external_job_id: str | None = None      # SE Job id when suspended
  step_correlation_id: str | None = None  # echo for CloudEvent correlation
  ```

- Add a fourth factory:

  ```python
  @staticmethod
  def suspended(
      *,
      external_job_id: str,
      step_correlation_id: str,
      reason: str | None = None,
  ) -> StepResult:
      return StepResult(
          status="suspended",
          external_job_id=external_job_id,
          step_correlation_id=step_correlation_id,
          reason=reason or f"awaiting external job {external_job_id}",
      )
  ```

- Extend `to_dict()` to include the new fields when present.

**Tests:** update existing `StepResult` unit tests with a `suspended()` factory case and a `to_dict()` round-trip.

**Acceptance:** `make test` (lablet-controller) stays green; the new factory exists.

---

### Step 2 — `ScenarioEngineStep` base + step adapter helpers (G-05 part 2)

**Create** `src/lablet-controller/application/services/step_handlers/_scenario_engine_step.py`:

```python
"""Tier-B step adapter: submits an SE Job and returns SUSPENDED.

AD-CSI-008: any step that operates on an *external system* (CML, RADkit, …)
delegates to the Scenario Engine instead of using in-process adapters.
"""
from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel
from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScenarioBinding:
    scenario_name: str
    scenario_version: str = "v1"


async def submit_scenario_engine_job(
    *,
    binding: ScenarioBinding,
    step_name: str,
    instance: LabletSessionReadModel,
    context: PipelineContext,
    input_data: dict[str, Any],
) -> StepResult:
    """Submit a Job to SE; return StepResult.suspended.

    The CloudEvent emitted by SE on completion will carry `subject=job_id`,
    which the lablet-controller events_controller uses to find the suspended
    step (see Step 6).
    """
    if context.scenario_engine_client is None:
        return StepResult.failed(
            f"{step_name}: ScenarioEngineClient not available on PipelineContext"
        )

    pod_definition_id = (
        instance.pod_definition_ref.definition_id
        if instance.pod_definition_ref is not None
        else None
    )
    if pod_definition_id is None:
        return StepResult.failed(
            f"{step_name}: instance {instance.id} has no pod_definition_ref"
        )

    step_correlation_id = f"{instance.id}:{step_name}:{uuid.uuid4().hex[:8]}"

    try:
        result = await context.scenario_engine_client.submit_job(
            scenario_name=binding.scenario_name,
            scenario_version=binding.scenario_version,
            input_data=input_data,
            pod_definition_id=pod_definition_id,
            callback_url=context.cloud_event_callback_url,
            metadata={
                "lablet_session_id": instance.id,
                "step_name": step_name,
                "step_correlation_id": step_correlation_id,
            },
        )
    except Exception as exc:  # noqa: BLE001 — SE downtime must fail the step
        logger.exception("Failed to submit SE job for %s: %s", step_name, exc)
        return StepResult.failed(f"{step_name}: SE submit_job failed: {exc}")

    logger.info(
        "SE job submitted: scenario=%s@%s job_id=%s step=%s session=%s",
        binding.scenario_name, binding.scenario_version,
        result.job_id, step_name, instance.id,
    )

    return StepResult.suspended(
        external_job_id=result.job_id,
        step_correlation_id=step_correlation_id,
        reason=f"awaiting SE job {result.job_id} (scenario={binding.scenario_name}@{binding.scenario_version})",
    )
```

> **Verify before writing**: `ScenarioEngineClient.submit_job(...)` signature
> currently does **not** accept `metadata`. Either (a) extend the client +
> wire `metadata` into SE's `SubmitJobCommand` (small SE-side change — note
> that AD says SE is contract, but adding an _optional_ pass-through field is
> within scope and well-isolated), or (b) drop the `metadata` argument and
> rely solely on `subject = job_id` for correlation (simpler, recommended).
> Pick (b) and document the choice as a new AD-CSI-NNN.

**Extend `PipelineContext`** (`src/lablet-controller/application/models/pipeline_context.py`):

- Add optional injectable fields used by Tier-B steps:
  - `scenario_engine_client: ScenarioEngineClient | None = None`
  - `cloud_event_callback_url: str | None = None`
  - `scenario_engine_enabled: bool = False`

- Populate from settings/DI inside `LifecyclePhaseHandler` when constructing the context.

**Tests:** `tests/unit/services/step_handlers/test_scenario_engine_step.py` — happy path returns SUSPENDED; missing client returns FAILED; missing `pod_definition_ref` returns FAILED; SE raises → FAILED.

---

### Step 3 — Rewrite `lab_resolve_step.py` and `lab_start_step.py` as Tier-B (G-05 part 3)

**Edit** `src/lablet-controller/application/services/step_handlers/lab_resolve_step.py`:

- Keep the `@step_handler("lab_resolve")` decorator and signature.
- At the **top** of the body, branch on the feature flag:

  ```python
  if context.scenario_engine_enabled:
      return await submit_scenario_engine_job(
          binding=ScenarioBinding(scenario_name="lab_resolve", scenario_version="v1"),
          step_name="lab_resolve",
          instance=instance,
          context=context,
          input_data={
              "session_id": instance.id,
              "definition_id": instance.definition_id,
              "topology_yaml": topology_yaml,
              "worker_pool_hint": getattr(context, "worker_pool_hint", None),
          },
      )
  # else: existing in-process behaviour (unchanged)
  ```

- Do **not** delete the legacy body — it remains the fallback path until Phase 4 flips the flag.

**Edit** `src/lablet-controller/application/services/step_handlers/lab_start_step.py`:

- Mirror the above pattern with `scenario_name="lab_start"`. Input includes
  `{"session_id": instance.id, "cml_lab_id": instance.cml_lab_id}`.

**Tests:** parametrise existing step tests with both `scenario_engine_enabled=True` and `False`; the True path asserts `submit_scenario_engine_job` was invoked with the expected scenario binding and that the result is SUSPENDED.

> **DO NOT touch** the other 19 step handlers in
> `src/lablet-controller/application/services/step_handlers/`. Per AD-CSI-008, all
> CPA-state-touching steps (`ports_alloc`, `tags_sync`, `lab_binding`, `mark_ready`,
> `deregister_lds`, `archive`, capture/evidence/grading-record steps) stay Tier-A. Only `lab_resolve` and
> `lab_start` are in scope this phase. `lab_stop`, `lab_wipe`, `collect_grade`, `score_report` migrate later
> alongside their SE scenarios (Phase 5).

---

### Step 4 — Teach `PipelineExecutor` to honour SUSPENDED (G-05 part 4)

**Edit** `src/lablet-controller/application/services/pipeline_executor.py`:

- When a step returns `StepResult.status == "suspended"`:
  1. Persist progress so resumption can find it (the existing `existing_progress` mechanism is the substrate).
     Record on the per-step progress entry: `{"status": "suspended", "external_job_id": ..., "step_correlation_id": ..., "suspended_at": <utcnow>}`.
  2. **Append** the `external_job_id` to a per-execution registry:
     `pipeline_execution_record.external_jobs.append({"job_id": ..., "step_name": ..., "step_correlation_id": ..., "session_id": instance.id, "submitted_at": <utcnow>})`.
     (Add the column to the existing CPA `PipelineExecutionRecord` aggregate via a new value-object — see Step 5.)
  3. **Halt this step's downstream** (do not dispatch any topo-successors) and return from the executor with a sentinel `PipelineRunOutcome.SUSPENDED`. The executor is naturally re-entrant via `existing_progress`; the next invocation (triggered by `ResumePipelineStepCommand`) will see the step as `completed` and continue topologically.

- Add a new method `async def resume_after_external_completion(self, execution_id: str, step_correlation_id: str, result_data: dict[str, Any]) -> PipelineRunOutcome`. It looks up the suspended step, marks it COMPLETED with the supplied `result_data`, persists progress, and recursively dispatches successors via the existing dispatch loop.

- Add a parallel `fail_after_external_completion(...)`. If `pipeline_failure_strategy == "abort"` (the existing default per AD-PIPELINE-007), short-circuit the executor; otherwise continue with the failure recorded.

**Edit** `src/lablet-controller/application/services/lifecycle_phase_handler.py`:

- When the executor returns `SUSPENDED`, **do not** consider the phase complete — record `status=suspended`
  on the phase task state and exit the asyncio.Task gracefully (no exception). Resumption commands
  re-spawn the task or call `resume_after_external_completion` directly via an in-process registry.
  Pick one approach and document it (proposal: in-process `dict[execution_id, PipelineExecutor]` keyed
  registry held by the singleton `LifecyclePhaseHandler` — simpler than re-spawning; SE callback hits the
  same process).

**Tests:** integration test in `tests/integration/services/test_pipeline_executor_suspension.py`:

- Fake `@step_handler` that returns SUSPENDED on first call, COMPLETED on second.
- Assert `PipelineRunOutcome.SUSPENDED` on first run.
- Call `resume_after_external_completion(...)` and assert the run advances to completion.
- Assert downstream steps are dispatched only after resume.

**Acceptance:** `make test` green; new suspension tests pass.

---

### Step 5 — CPA `ResumePipelineStepCommand` + `FailPipelineStepCommand` (G-06 part 1)

> CPA is the **sole MongoDB writer** (AD-CSI-005). Any mutation of `pipeline_execution_record`
> goes through Mediator-dispatched CPA commands.

**Create** `src/control-plane-api/application/commands/lablet_session/resume_pipeline_step_command.py`:

```python
@dataclass
class ResumePipelineStepCommand(Command[OperationResult[ResumeResultDto]]):
    session_id: str
    execution_id: str            # pipeline_execution_record._id
    external_job_id: str         # SE Job id from CloudEvent subject
    step_correlation_id: str | None  # optional cross-check (fail if mismatched)
    output: dict[str, Any]       # merged into step result_data
    completed_at: datetime
```

Handler:

1. Load the `LabletSession` aggregate.
2. Locate the suspended step by `(execution_id, external_job_id)` and validate
   the `step_correlation_id` matches (mismatched → `self.conflict(...)`).
3. Apply via aggregate method `session.resume_external_step(execution_id=..., step_correlation_id=..., output=..., completed_at=...)` which:
   - Records the step transition `RUNNING/SUSPENDED → COMPLETED`.
   - Merges `output` into the step's `result_data`.
   - Emits `PipelineStepExternalCompletedDomainEvent` (new).
4. `await repository.save_async(...)`.
5. **Side-effect**: notify the lablet-controller's in-process pipeline executor.
   Since CPA and lablet-controller are separate services, CPA's command cannot directly call the executor.
   Two viable mechanisms:
   - **(a)** CPA writes a small entry to etcd at `/lcm/pipelines/{execution_id}/resume_signal/{step_name}` —
     lablet-controller's `LifecyclePhaseHandler` watches that key and invokes
     `resume_after_external_completion` on the in-process executor.
   - **(b)** lablet-controller's `events_controller` handler that issued the command **itself**, on
     receiving the 200 from CPA, immediately invokes `resume_after_external_completion` locally.
   - Recommended: **(b)** — events_controller and pipeline_executor live in the same process; etcd dance is unnecessary. Record as **AD-CSI-016**.

Return `OperationResult[ResumeResultDto]` with the updated step snapshot.

**Create** `src/control-plane-api/application/commands/lablet_session/fail_pipeline_step_command.py`:

Same pattern but transitions to FAILED with `error` payload. Handler decides if the parent pipeline aborts based on `pipeline_failure_strategy` (already an aggregate field).

**Domain extensions** (`src/control-plane-api/domain/entities/lablet_session.py`):

- Add methods `resume_external_step(...)` and `fail_external_step(...)` to the aggregate.
- Add `PipelineStepExternalCompletedDomainEvent` and `PipelineStepExternalFailedDomainEvent` to
  `src/control-plane-api/domain/events/lablet_session_events.py` (separate event types so projectors and audit logs distinguish externally-completed vs in-process-completed steps).

**Tests:** `tests/application/commands/lablet_session/test_resume_pipeline_step_command.py` and `test_fail_pipeline_step_command.py`:

- Happy path: suspended step → COMPLETED with merged output, event emitted.
- Wrong `step_correlation_id` → 409 conflict.
- Step not in SUSPENDED state → 409 conflict.
- Unknown `execution_id` → 404 not found.
- `fail` with `pipeline_failure_strategy="abort"` short-circuits remaining steps.

---

### Step 6 — Implement lablet-controller `events_controller` handlers (G-06 part 2)

**Edit** `src/lablet-controller/api/controllers/events_controller.py`:

> **State today**: the controller exists, the CloudEvent parsing helpers exist (structured + binary
> mode), the dispatch switch exists, but **all 5 handlers are TODO stubs that just log and exit**.

Refactor the controller to be an injected Neuroglia `ControllerBase` (or keep the current
`APIRouter` shape — check the surrounding controllers in `src/lablet-controller/api/controllers/` for
the canonical pattern; the SE-side events controller now lives on CPA but lablet-controller's local
events_controller is a separate beast). Either way, inject:

- The CPA `ControlPlaneApiClient` (or directly dispatch the CPA command via Mediator if both services share the deployment; verify whether `lablet-controller` has direct DB access to dispatch CPA commands — it does **not**, so this is HTTP via the existing `ControlPlaneApiClient`).
- The lablet-controller's `LifecyclePhaseHandler` (singleton) so handlers can call `resume_after_external_completion(...)` after CPA confirms the state change.

Implement each handler with thin, testable bodies:

| Event type | Action |
|---|---|
| `scenario_engine.job.started.v1` | Log + (optional) `RecordExternalJobStartedCommand` (audit-only — defer unless trivial). 202. |
| `scenario_engine.job.progress.v1` | Call existing CPA `UpdatePipelineProgressCommand` via `ControlPlaneApiClient.update_pipeline_progress(...)`. 202. |
| `scenario_engine.job.completed.v1` | (1) Call `ControlPlaneApiClient.resume_pipeline_step(session_id, execution_id, external_job_id, step_correlation_id, output, completed_at)`. (2) On 200, invoke `lifecycle_phase_handler.resume_after_external_completion(execution_id, step_correlation_id, output)`. 202. |
| `scenario_engine.job.failed.v1` | Similar but `fail_pipeline_step(...)`; on 200, invoke `lifecycle_phase_handler.fail_after_external_completion(...)`. 202. |
| `scenario_engine.job.cancelled.v1` | Same as `failed` with `reason="cancelled"`. 202. |
| Unknown type | Log `WARN unknown event type`, return 202 (forward-compat). |

The CloudEvent payload conventions to honour (verify against SE's
`CloudEventCallbackService.emit_job_*`):

- `subject = job_id`
- `id = uuid4` (delivery id, not job id)
- `time = RFC 3339` — parse with the helper added in Phase 2's CPA `events_controller`
  (`_parse_event_time`); copy verbatim — do **not** import across service boundaries.
- `data = {"job_id": str, "scenario_name": str, "scenario_version": str, "metadata": {"lablet_session_id": str, "step_name": str, "step_correlation_id": str}, "output": dict, "progress": dict, "error": dict, …}`

> **Validation rule**: If a CloudEvent is missing `metadata.lablet_session_id` or
> `metadata.step_correlation_id`, return **400** — these are required for routing.
> If a CloudEvent references an unknown `(execution_id, job_id)` pair (e.g. CPA returned 404),
> return **202** anyway (idempotency on the SE retry side) but log loudly.

**Extend** `src/lablet-controller/integration/services/scenario_engine_client.py` if needed so the
client's `submit_job(...)` accepts and forwards a `metadata` dict to SE's `SubmitJobCommand`. This
forms the only contract change to scenario-engine in this phase — **strictly additive**:
SE's `SubmitJobCommand` adds an optional `metadata: dict[str, Any] | None = None` field that
is round-tripped onto the emitted CloudEvent's `data.metadata`. **No behavioural change to the
DSL executor or registry.** Record as **AD-CSI-017** and call out as the only SE-side delta.

**Tests:** `tests/integration/api/test_events_controller_job_lifecycle.py`:

- Structured-mode `job.completed.v1` → asserts `ControlPlaneApiClient.resume_pipeline_step` called with parsed payload + `lifecycle_phase_handler.resume_after_external_completion` invoked.
- Binary-mode `job.failed.v1` → asserts fail path.
- Missing `metadata.step_correlation_id` → 400.
- CPA returns 404 → still 202 + warning log.
- Unknown event type → 202 + warning log.
- `job.progress.v1` → asserts `update_pipeline_progress` called.

---

### Step 7 — `ControlPlaneApiClient` additions

**Edit** `src/core/lcm_core/integration/clients/control_plane_api_client.py`:

Add three methods (HTTP POST to the new CPA internal endpoints):

```python
async def resume_pipeline_step(
    self, *, session_id: str, execution_id: str, external_job_id: str,
    step_correlation_id: str, output: dict[str, Any], completed_at: datetime,
) -> dict[str, Any]: ...

async def fail_pipeline_step(
    self, *, session_id: str, execution_id: str, external_job_id: str,
    step_correlation_id: str, error: dict[str, Any], failed_at: datetime,
    reason: str | None = None,
) -> dict[str, Any]: ...

async def record_external_job_started(
    self, *, session_id: str, execution_id: str, external_job_id: str,
    step_name: str, scenario_name: str, scenario_version: str, started_at: datetime,
) -> dict[str, Any]: ...
```

POST targets (new CPA internal routes added in Step 8):

- `/api/internal/lablet-sessions/{session_id}/pipelines/{execution_id}/steps/resume`
- `/api/internal/lablet-sessions/{session_id}/pipelines/{execution_id}/steps/fail`
- `/api/internal/lablet-sessions/{session_id}/pipelines/{execution_id}/external-jobs/started`

**Tests:** standard `httpx.MockTransport` tests for each method — happy path, 4xx, 5xx, transport error.

---

### Step 8 — CPA internal API controller endpoints (G-06 part 3)

**Edit** the existing internal controller (e.g. `src/control-plane-api/api/controllers/internal_controller.py`) — do **not** create a new file unless the existing one is already too large. Add three `@post` routes that thinly dispatch:

```python
@post("/lablet-sessions/{session_id}/pipelines/{execution_id}/steps/resume", status_code=200)
async def resume_step(self, session_id: str, execution_id: str, body: ResumePipelineStepRequest):
    cmd = ResumePipelineStepCommand(session_id=session_id, execution_id=execution_id, **body.model_dump())
    return self.process(await self.mediator.execute_async(cmd))
```

Same pattern for `fail` and `external-jobs/started`. Pydantic `Request` DTOs are minimal (one
per endpoint).

**Tests:** controller-level happy-path tests; auth tests use the existing fixture.

---

### Step 9 — Settings + DI plumbing

**Edit** `src/lablet-controller/application/settings.py`:

- Reuse `scenario_engine_integration_enabled` (the Phase 2 flag — same semantic boundary).
- Add `pipeline_external_step_default_timeout_seconds: int = 1800` (used by the watchdog if you choose to ship it — see Out-of-Scope).

**Edit** `src/lablet-controller/main.py`:

- Ensure `LifecyclePhaseHandler` is registered as a singleton (it likely already is — verify) so the
  `events_controller` can resolve the same instance the executor uses.
- Ensure `ControlPlaneApiClient` is registered and injected into `events_controller`.

**Edit** `src/control-plane-api/main.py`:

- Register the new commands' DI (they should be auto-discovered by the Mediator if the handler classes follow naming conventions — verify against `RecordContentSyncResultCommandHandler`).

---

### Step 10 — Resolve open questions in `cpa-se-integration-plan.md §8`

Append to §7 and update §8:

- **AD-CSI-016** — Resumption signal is **in-process** (lablet-controller `events_controller` → `LifecyclePhaseHandler.resume_after_external_completion(...)` directly), **not** via etcd watch. The etcd channel remains only for desired-state writes from CPA. (Closes a question that surfaced during Step 5.)
- **AD-CSI-017** — `SubmitJobCommand` accepts an optional `metadata: dict | None` that is round-tripped onto CloudEvents as `data.metadata`. This is the only Phase-3 contract change to scenario-engine; behaviour of the DSL executor and registry is unchanged.
- **Q-01 resolution** — Phase 3 does not require Q-01 to be resolved (deterministic `pod_definition_id`) because resumption keys on `(execution_id, external_job_id)`, not on `pod_definition_id`. Defer.
- Possibly new **Q-10** — watchdog strategy: if a CloudEvent is never received for a suspended step, after `pipeline_external_step_default_timeout_seconds` should the step (a) auto-fail, (b) auto-retry via `SE.get_job_status(...)`, or (c) page an operator? Recommend (b) with a `max_polls` limit; out of scope to implement here but should be raised.

Both new ADs must also be stored via `mcp_knowledge_store_decision`.

---

### Step 11 — Final verification

```bash
cd src/core              && .venv/bin/pytest -q && .venv/bin/ruff check
cd src/scenario-engine   && make lint && make test     # because of AD-CSI-017 (metadata pass-through)
cd src/lablet-controller && make lint && make test
cd src/control-plane-api && make lint && make test
```

All four suites must be green. **Do** run a manual end-to-end smoke with the Docker stack if practical:

```bash
make dev   # full stack
# In a second shell:
SCENARIO_ENGINE_INTEGRATION_ENABLED=true \
  curl -X POST http://localhost:8080/api/v1/lablet-sessions/{id}/start-instantiation
# Watch logs: lablet-controller submits SE Job → SE executes → CloudEvent → pipeline resumes
```

---

## Out of scope for Phase 3 (do NOT implement here)

- ❌ `ContentDrivenTemplateLoader` (Phase 4, G-09) — still consume the hardcoded templates.
- ❌ Migrating `lab_stop` / `lab_wipe` / `collect_grade` / `score_report` to Tier-B (Phase 5, G-10).
- ❌ Removing the legacy in-process bodies of `lab_resolve_step` / `lab_start_step` — keep both paths,
  flag-gated, until Phase 4 flips `SCENARIO_ENGINE_INTEGRATION_ENABLED=true` by default.
- ❌ Watchdog for stuck SUSPENDED steps — recommended but defer (Q-10).
- ❌ Flipping `SCENARIO_ENGINE_INTEGRATION_ENABLED` default — stays `false`.
- ❌ Scheduler `pod_type` filter (Phase 6, G-11).
- ❌ Any change to SE scenarios (`lab_resolve_scenario.py`, `lab_start_scenario.py`) beyond what
  `AD-CSI-017` mandates (which is _not_ a scenario change — it's a `SubmitJobCommand` field add).

If you find yourself touching files outside the **Implementation Steps** list above (notably anything in
`src/scenario-engine/scenarios/` or in `src/resource-scheduler/`), **stop** and update the master plan §3
with a new gap or open question first.

---

## Open questions for Phase 3

- **Q-10 (NEW)** — Watchdog strategy for stuck SUSPENDED steps (see Step 10). Propose: periodic `SE.get_job_status` poll after `pipeline_external_step_default_timeout_seconds × 1.5`; fail the step after `max_polls=3` consecutive `404|FAILED` results. Defer implementation.
- **Q-11 (NEW)** — Should `events_controller` validate the CloudEvent `source` against an allow-list (only accept events whose `source` URI matches the configured SE base URL)? Cheap defence against a misconfigured CloudEvent emitter sending spurious events. Recommend yes (one-line check), but if you defer, document as Q-11.

---

## Knowledge Manager hygiene during the session

After each Step, call `mcp_knowledge_update_task` with
`title: "Phase 3: Tier-B steps + CloudEvent resumption (G-05 + G-06)"` and the appropriate `status`.

For each architecturally important new file (`_scenario_engine_step.py`, `resume_pipeline_step_command.py`,
`fail_pipeline_step_command.py`, the updated `events_controller.py`, the updated `pipeline_executor.py`),
call `mcp_knowledge_add_file_context` with `purpose`, `key_exports`, `patterns_used`.

Record AD-CSI-016, AD-CSI-017 (and any further) via `mcp_knowledge_store_decision` **and** append to
`cpa-se-integration-plan.md §7`.

---

## Definition of Done — Phase 3

- [ ] `StepResult` gains a `suspended(...)` factory + `external_job_id` + `step_correlation_id` fields
- [ ] `_scenario_engine_step.submit_scenario_engine_job(...)` helper shipped with full test coverage
- [ ] `PipelineContext` exposes `scenario_engine_client`, `cloud_event_callback_url`, `scenario_engine_enabled`
- [ ] `lab_resolve_step` + `lab_start_step` branch on the flag and submit SE Jobs when enabled
- [ ] `PipelineExecutor` honours `StepResult.suspended` (persists progress + halts dispatch) and exposes
      `resume_after_external_completion` + `fail_after_external_completion`
- [ ] `LifecyclePhaseHandler` is reachable from `events_controller` as a singleton
- [ ] CPA `ResumePipelineStepCommand` + `FailPipelineStepCommand` self-contained handlers
      shipped with 5+ tests each
- [ ] `LabletSession` aggregate gains `resume_external_step(...)` + `fail_external_step(...)` and emits
      `PipelineStepExternalCompletedDomainEvent` / `PipelineStepExternalFailedDomainEvent`
- [ ] CPA internal API routes `…/steps/resume`, `…/steps/fail`, `…/external-jobs/started` shipped
- [ ] `ControlPlaneApiClient.resume_pipeline_step` + `fail_pipeline_step` + `record_external_job_started` shipped
- [ ] lablet-controller `events_controller` 5 handlers fully implemented (no TODO stubs left); dispatch via Mediator/HTTP per AD-CSI-005
- [ ] SE `SubmitJobCommand` accepts optional `metadata` (AD-CSI-017); CloudEvent payload rebuilt to include it
- [ ] End-to-end test (mocked SE) demonstrates: `lab_resolve_step` (flag on) → SUSPENDED → simulated CloudEvent → step COMPLETED → `ports_alloc` dispatched
- [ ] `cd src/lablet-controller && make lint && make test` green
- [ ] `cd src/control-plane-api && make lint && make test` green
- [ ] `cd src/core && pytest -q && ruff check` green
- [ ] `cd src/scenario-engine && make lint && make test` green (metadata pass-through covered)
- [ ] Master plan §3 G-05 + G-06 banners flipped 🔴 → 🟢 with `**Closed:** <commits>` lines
- [ ] Master plan §1 exec summary rows "`ScenarioEngineClient` call sites" and "CloudEvent callbacks → CPA" updated
- [ ] Master plan §6 Phase 3 bullets ticked (`🟢 Complete` + verification line)
- [ ] Master plan §7 has AD-CSI-016 + AD-CSI-017 (+ any further) appended
- [ ] Master plan §8 has Q-10 + Q-11 (or their resolutions) added
