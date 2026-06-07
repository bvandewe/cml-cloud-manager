# Bootstrap Prompt: Scenario Engine Job Execution Engine Implementation

| Attribute | Value |
|-----------|-------|
| **Sprint** | SE-Phase2 |
| **Created** | 2026-06-05 |
| **Design Doc** | `docs/implementation/scenario-engine-job-execution.md` |
| **Service** | `src/scenario-engine/` |
| **Tests pass** | `make lint && make test` ✅ (as of 2026-06-05) |

---

## Objective

Implement the **Job Execution Engine** for the `scenario-engine` microservice. This is the HostedService that picks up submitted jobs from an asyncio.Queue, resolves the scenario from the registry, executes it with a `ScenarioContext`, and emits CloudEvents callbacks on completion/failure.

**Read the full design document first**: `docs/implementation/scenario-engine-job-execution.md`

---

## Implementation Steps (in order)

### Step 1: `ScenarioContext` + `AdapterRegistry`

**Create** `src/scenario-engine/application/services/scenario_context.py`

- `AdapterRegistry` — simple dict wrapper with `get(type)` and `require(type)` methods
- `ScenarioContext` — frozen dataclass with fields:
  - `job_id: str`, `scenario_name: str`, `scenario_version: str`
  - `input_data: dict[str, Any]`
  - `pod_definition_id: str | None`, `callback_url: str | None`
  - `adapters: AdapterRegistry`
  - `report_progress: Callable[[int, str, dict | None], Awaitable[None]]`
  - `cancellation_event: asyncio.Event`
  - `logger: logging.Logger`
- No external dependencies beyond stdlib + dataclasses

### Step 2: `AdapterBase` stub

**Create** `src/scenario-engine/integration/services/adapters/__init__.py` and `adapter_base.py`

- Abstract base class with `adapter_type: str` property
- This is a Phase 4 extension point — only the interface is needed now

### Step 3: `CloudEventCallbackService`

**Create** `src/scenario-engine/integration/services/cloud_event_client.py`

- Uses `httpx.AsyncClient` to POST CloudEvents to a target URL
- Resolution logic: use `job.callback_url` if set, else `settings.cloud_event_sink`
- Retry: 3 attempts, exponential backoff (1s/2s/4s)
- Fire-and-forget — failures logged, never raise to caller
- Events use CloudEvents spec 1.0 JSON format with `ce-` headers
- Event types: `scenario_engine.job.started.v1`, `.progress.v1`, `.completed.v1`, `.failed.v1`, `.cancelled.v1`
- Progress throttling: max one progress event per `settings.job_progress_interval` seconds per job

### Step 4: `JobExecutionService` (HostedService)

**Create** `src/scenario-engine/application/services/job_execution_service.py`

- Extends `neuroglia.hosting.HostedService`
- **`configure()` class method**: registers as singleton + HostedService in DI container
- **`start_async()`**: runs `_startup_sweep()` then spawns `_dispatch_loop()` task
- **`stop_async()`**: cancels dispatch loop, cancels all running tasks with grace period, awaits drain
- **`enqueue_job(job_id: str)`**: public method called by SubmitJobCommandHandler — puts job_id on queue
- **`request_cancel(job_id: str)`**: public method called by CancelJobCommandHandler — sets cancellation event + task.cancel() after grace
- **`_startup_sweep()`**: queries repo for SUBMITTED → re-enqueue; RUNNING → mark FAILED("service restarted")
- **`_dispatch_loop()`**: `while running: job_id = await queue.get(); await semaphore.acquire(); create_task(_execute_job)`
- **`_execute_job(job_id)`**: loads Job, resolves scenario from registry, builds ScenarioContext, calls `scenario.execute()`, handles result/timeout/error, persists, emits CloudEvent, releases semaphore
- Concurrency: `asyncio.Semaphore(settings.max_concurrent_jobs)`
- Timeout: `asyncio.wait_for(scenario.execute(...), timeout=settings.job_default_timeout)`
- Task tracking: `_running_tasks: dict[str, asyncio.Task]`

### Step 5: Wire into `SubmitJobCommandHandler`

**Edit** `src/scenario-engine/application/commands/submit_job_command.py`

- Inject `JobExecutionService` into handler constructor
- After `self._repository.add_async(job)`, call `self._executor.enqueue_job(job.id())`
- The handler already returns `self.accepted(...)` — no change to API contract

### Step 6: Wire into `CancelJobCommandHandler`

**Edit** `src/scenario-engine/application/commands/cancel_job_command.py`

- Inject `JobExecutionService` into handler constructor
- After `self._repository.update_async(job)`, call `self._executor.request_cancel(job_id)`

### Step 7: Register in `main.py`

**Edit** `src/scenario-engine/main.py`

- Import `JobExecutionService`
- Call `JobExecutionService.configure(builder.services, settings)` in the DI section
- Import `CloudEventCallbackService` and register as singleton

### Step 8: `EchoScenario` test scenario

**Create** `src/scenario-engine/scenarios/echo_scenario.py`

- Uses `@scenario(name="echo", version="v1")` decorator
- `execute()` sleeps briefly, calls `context.report_progress(50, "Processing...")`, returns `ScenarioResult.completed(output_data=input_data)`
- Import in `scenarios/__init__.py` to trigger registration

### Step 9: Unit tests

**Create** `src/scenario-engine/tests/unit/test_job_execution_service.py`

- Test startup sweep (orphaned SUBMITTED re-enqueued, orphaned RUNNING marked FAILED)
- Test dispatch + execution flow (SUBMITTED → RUNNING → COMPLETED)
- Test timeout (job exceeding timeout → FAILED)
- Test cancellation (cooperative + hard)
- Test concurrency limit (semaphore blocks excess)

**Create** `src/scenario-engine/tests/unit/test_cloud_event_callback.py`

- Test URL resolution (per-job override vs global sink)
- Test retry on failure
- Test progress throttling

---

## Key Reference Files (read before implementing)

| File | Why |
|------|-----|
| `docs/implementation/scenario-engine-job-execution.md` | Full design with rationale, sequence diagram, error handling |
| `src/scenario-engine/application/services/scenario_registry.py` | Registry API — `get_scenario()` returns `ScenarioMetadata` with `.implementation` |
| `src/scenario-engine/domain/entities/job.py` | Job aggregate — `start()`, `complete()`, `fail()`, `cancel()`, `update_progress()` methods |
| `src/scenario-engine/application/commands/submit_job_command.py` | Current handler — add `enqueue_job()` call |
| `src/scenario-engine/application/commands/cancel_job_command.py` | Current handler — add `request_cancel()` call |
| `src/scenario-engine/application/settings.py` | Settings: `max_concurrent_jobs`, `job_default_timeout`, `job_progress_interval`, `cloud_event_sink` |
| `src/scenario-engine/main.py` | DI registration — follow existing pattern for repos |
| `src/core/lcm_core/infrastructure/hosted_services/reconciliation_hosted_service.py` | Reference: HostedService lifecycle, semaphore, startup pattern |
| `src/lablet-controller/application/services/lifecycle_phase_handler.py` | Reference: managed asyncio.Task wrapper pattern |
| `src/lablet-controller/application/services/pipeline_executor.py` | Reference: execution context, timeout, retry, progress |

---

## Patterns to Follow

1. **HostedService lifecycle**: `start_async()` / `stop_async()` — see `ReconciliationHostedService`
2. **`configure()` class method**: Registers service in DI — see `LabletReconciler.configure()` in lablet-controller
3. **Self-contained CQRS**: Command + Handler in same file
4. **Module-level imports only** (no inline imports except `TYPE_CHECKING`)
5. **Mediator calls take ONE argument** (no `cancellation_token`)
6. **Handler helper methods**: `self.ok()`, `self.accepted()`, `self.bad_request()`, etc.
7. **Black formatting** (line length 120) + **Ruff linting** (E, F, W, I, UP)
8. **All tests use pytest + pytest-asyncio** with `@pytest.mark.asyncio` and `@pytest.mark.unit`

---

## Validation Checklist

After implementation:

```bash
cd src/scenario-engine
make lint        # Ruff + format check
make test        # All tests pass (existing + new)
```

Verify:

- [ ] `JobExecutionService.configure()` called in `main.py`
- [ ] `EchoScenario` registered and visible at `GET /api/v1/scenarios`
- [ ] `POST /api/v1/jobs` with `scenario_name=echo` → job executes and transitions to COMPLETED
- [ ] `DELETE /api/v1/jobs/{id}` cancels a running job
- [ ] Startup sweep handles orphaned jobs correctly
- [ ] CloudEvents emitted to configured sink (log verification sufficient)
- [ ] No new lint errors, all existing tests still pass
