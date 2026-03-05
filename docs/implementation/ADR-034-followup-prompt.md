# ADR-034 Implementation — Follow-Up Session Prompt

> **Purpose:** This file contained the Sprint A+B bootstrap prompt. Sprints A, B, and C are now complete.
>
> **Current sprint:** Sprint D — see `docs/implementation/ADR-034-sprint-d-prompt.md`
>
> **Completed sprints:**
>
> - **Sprint A** ✅ — Foundation (LabletDefinitionReadModel.pipelines, simpleeval)
> - **Sprint B** ✅ — PipelineExecutor, PipelineContext, PipelineResult (58 tests)
> - **Sprint C** ✅ — LifecyclePhaseHandler, reconciler integration, fire-and-check (126 total tests)
> - **Sprint C bonus** ✅ — graphlib refactor (AD-PIPELINE-010)

---

## Sprint D Prompt

See [ADR-034-sprint-d-prompt.md](ADR-034-sprint-d-prompt.md) for the full Sprint D session prompt.

---

## Historical Sprint A+B Prompt (archived)

```
I need to implement ADR-034 Sprint A + Sprint B for the Lablet Cloud Manager project.
Read the implementation guide at docs/implementation/ADR-034-next-steps.md first.

### Context

ADR-034 introduces a PipelineExecutor to replace the current one-step-per-reconcile
pattern in the lablet-controller. The architecture is fully documented in
docs/architecture/adr/ADR-034-pipeline-executor-lifecycle-handlers.md (726 lines).

Phase 1 (Foundation) is 5/6 done. The remaining gap is:
- Task 1.5: `LabletDefinitionReadModel` in lcm_core does NOT have a `pipelines` field.
  Definitions flow via HTTP API (not etcd). The read model at
  src/core/lcm_core/domain/entities/read_models/lablet_definition_read_model.py
  needs `pipelines: dict | None = None` added to the dataclass AND to `from_dict()`.

### Sprint A Tasks (Foundation Completion)

1. **A1**: Add `pipelines: dict | None = None` to `LabletDefinitionReadModel` and
   update `from_dict()` to parse it. File:
   `src/core/lcm_core/domain/entities/read_models/lablet_definition_read_model.py`

2. **A2**: Add `simpleeval = "^1.0"` to lablet-controller dependencies. File:
   `src/lablet-controller/pyproject.toml` under `[tool.poetry.dependencies]`.
   Then run `poetry lock && poetry install` in the lablet-controller directory.

### Sprint B Tasks (PipelineExecutor)

3. **B1**: Create `PipelineContext` dataclass at
   `src/lablet-controller/application/models/pipeline_context.py`

   Fields needed: session (LabletSessionReadModel), definition (LabletDefinitionReadModel),
   worker_ip, worker_cml_username, worker_cml_password, api (ControlPlaneApiClient),
   cml (CmlLabsSpi), lds (LdsSpi | None), steps_data (dict[str, dict])

4. **B2**: Create `PipelineResult` dataclass at
   `src/lablet-controller/application/models/pipeline_result.py`

   Fields: pipeline_name, status ("completed"|"failed"|"partial"), steps_completed,
   steps_failed, steps_skipped, duration_seconds, outputs (dict), error (str | None)

5. **B3**: Create `PipelineExecutor` class at
   `src/lablet-controller/application/services/pipeline_executor.py`

   Key design constraints:
   - Does NOT import LabletReconciler (receives a step_dispatcher callable)
   - Uses simpleeval for skip_when evaluation
   - Kahn's algorithm for DAG topological sort
   - Per-step retry via loop + asyncio.sleep
   - Per-step timeout via asyncio.wait_for()
   - Progress persistence after each step via context.api.update_instantiation_progress()
   - Output resolution via dot-path expressions
   - StepDispatcher = Callable[[str, LabletSessionReadModel, dict], Awaitable[dict]]

   Reference the existing step handler pattern in
   src/lablet-controller/application/hosted_services/lablet_reconciler.py (9 _step_* methods)
   and the pipeline YAML schema in ADR-034 §4.

   Reference the two seed files for real pipeline definitions:
   - src/control-plane-api/data/seeds/lablet_definitions/exam-associate-auto-v1.1-lab-2.5.1.yaml
   - src/control-plane-api/data/seeds/lablet_definitions/exam-professional-enterprise-v1.0-lab-1.1.yaml

6. **B4**: Create comprehensive unit tests at
   `src/lablet-controller/tests/test_pipeline_executor.py`

   Test categories: DAG resolution (linear, diamond, cycle detection), skip_when evaluation,
   retry logic, timeout handling, optional step failure, output resolution, context injection,
   end-to-end 9-step pipeline with mocks.

   Pattern: Follow the test style in tests/test_instantiation_pipeline.py (make_instance fixture,
   AsyncMock for services, pytest-asyncio auto mode).

### Implementation Guidelines

- Use `lcm-senior-architect` mode conventions
- All imports at module level (no inline imports)
- Black formatting (line-length 200)
- Ruff linting (rules E, F, W, I, UP)
- Run `make lint` and `make test` in lablet-controller after changes
- Store architectural decisions for any design choices made
- Register new files with add_file_context

### Validation

After implementation:
- [ ] lablet-controller lint passes (`make lint`)
- [ ] All existing tests still pass (`make test`)
- [ ] New PipelineExecutor unit tests pass (30+ tests)
- [ ] simpleeval imports work in the lablet-controller venv
- [ ] LabletDefinitionReadModel.from_dict() correctly parses pipelines
```

---

## Alternative: Smaller Scope (Sprint A Only)

If you want to do just Sprint A in one session and Sprint B in another:

```
I need to complete ADR-034 Sprint A (Foundation) for the Lablet Cloud Manager project.
Read docs/implementation/ADR-034-next-steps.md for full context.

Two tasks:

1. Add `pipelines: dict | None = None` to `LabletDefinitionReadModel` in
   src/core/lcm_core/domain/entities/read_models/lablet_definition_read_model.py
   — both the dataclass field AND the from_dict() method.

2. Add `simpleeval = "^1.0"` to src/lablet-controller/pyproject.toml dependencies,
   then run poetry lock && poetry install.

Validate: run lablet-controller tests, verify imports work.
```
