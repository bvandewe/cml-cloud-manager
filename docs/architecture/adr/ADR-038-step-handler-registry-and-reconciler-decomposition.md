# ADR-038: Step Handler Registry, Pipeline Templates, and Reconciler Decomposition

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-23 |
| **Deciders** | LCM architects |
| **Related ADRs** | [ADR-034](adr-034-pipeline-executor.md), [ADR-031](adr-031-lablet-reconciler-architecture.md) |
| **Sprint** | I (lablet-controller) |

## 1. Context

### 1.1 Problem Statement

ADR-034 introduced a sophisticated DAG-based pipeline executor for LabletSession lifecycle
management. The executor supports topological step ordering, `skip_when` expressions,
per-step retry/timeout, and progress persistence. However, the current implementation
suffers from three structural issues:

**A. Hardcoded step dispatcher.** The step dispatcher resolves handlers via
`getattr(reconciler, f"_step_{handler_name}")`, coupling all step implementations
to the 2948-line `LabletReconciler` class. Adding a new step requires modifying the
reconciler directly.

**B. Duplicate pipeline definitions.** Every `LabletDefinition` seed YAML copy-pastes
the same ~100 lines of pipeline steps. The two existing definitions
(`exam_associate_auto_v1.1_lab_lab-2.5.1` and `exam_ccnp_test_v1_lab_lab-1.1`) have
identical `instantiate` and `teardown` pipelines. When a new step is added, every
definition file must be updated.

**C. No support for divergent pipelines.** Real-world labs require definition-specific
steps that don't exist in the standard pipeline. Examples:

- `transfer_archive_to_cml_node` — upload student files to a running lab node
- `extract_archive_on_cml_node` — unpack archives on a CML node
- `shut_cml_node_interface` — fault injection by disabling interfaces

All of these can be generalized as `execute_command_on_cml_node` with parameters,
but the current architecture has no mechanism for passing step parameters from YAML
to handlers.

**D. God object.** The `LabletReconciler` at 2948 lines / 52 methods / 18 logical
sections violates single-responsibility. It contains: reconciliation orchestration,
20 pipeline step implementations, lab resolution logic, LDS provisioning, worker
details caching, lab record management, and service info endpoints.

### 1.2 Current Architecture (ADR-034)

```
LabletDefinition YAML          LabletReconciler (2948 lines)
┌──────────────────────┐       ┌─────────────────────────────────┐
│ pipelines:           │       │ _build_step_dispatcher()        │
│   instantiate:       │──────▶│   getattr(self, f"_step_{name}")│
│     steps:           │       │                                 │
│       - content_sync │       │ _step_content_sync()            │
│       - lab_resolve  │       │ _step_lab_resolve()             │
│       - lab_start    │       │ _step_lab_start()               │
│       - ...          │       │ _step_...()  (20 methods)       │
│                      │       │                                 │
│   teardown:          │       │ + lab resolution (~200 lines)   │
│     steps: ...       │       │ + LDS helpers (~140 lines)      │
└──────────────────────┘       │ + worker cache (~100 lines)     │
                               │ + lab record helpers (~160 lines)│
                               └─────────────────────────────────┘
```

### 1.3 What ADR-034 Got Right

The pipeline executor infrastructure delivers real value:

- **Self-driving execution**: `LifecyclePhaseHandler` wraps `asyncio.Task` — pipelines
  run to completion without reconcile-loop polling
- **Per-step timeout + retry**: Configurable per step via YAML
- **Progress persistence**: Enables resumability across restarts
- **DAG ordering**: `graphlib.TopologicalSorter` handles dependency graphs
- **Observability**: `PipelineExecutionRecord` provides audit trails

These components are retained. This ADR addresses the missing abstractions.

## 2. Decision

### 2.1 Step Handler Registry

Replace `getattr(self, f"_step_{handler_name}")` with a registry pattern.
Step handlers are standalone async functions decorated with `@step_handler`:

```python
# application/services/step_handlers/instantiation_steps.py
from application.services.step_registry import step_handler

@step_handler("content_sync")
async def step_content_sync(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    ...
```

The registry is a module-level dict populated by decorator side-effects at import time:

```python
# application/services/step_registry.py
_HANDLERS: dict[str, StepHandlerFn] = {}

def step_handler(name: str):
    def decorator(fn): _HANDLERS[name] = fn; return fn
    return decorator

def get_handler(name: str) -> StepHandlerFn | None:
    return _HANDLERS.get(name)
```

**Key change:** The `StepDispatcher` signature gains a `params` argument:

```python
# Old: step_dispatcher(handler_name, session, progress) → result_data
# New: step_dispatcher(handler_name, session, progress, context, params) → result_data
```

And `PipelineExecutor._execute_step()` passes `step.get("params")` to the dispatcher.

### 2.2 Pipeline Templates

Introduce `PipelineTemplateResolver` that resolves `extends` references before
the executor sees the pipeline definition. Templates are standard pipelines
defined once; definitions customize via `insert_after`, `insert_before`, and
`overrides`.

```yaml
# In a definition:
pipelines:
  instantiate:
    extends: standard-instantiate    # base template name
    insert_after:
      lab_start:
        - name: transfer_archive
          handler: execute_command_on_cml_node
          params: { action: transfer_file, target_node: ubuntu-desktop, ... }
    overrides:
      lab_start:
        timeout_seconds: 600
  teardown:
    extends: standard-teardown       # use as-is, no customization
```

Resolution algorithm:

1. Load base template by name
2. Apply `insert_after` — inject steps after the named step
3. Apply `insert_before` — inject steps before the named step
4. Apply `overrides` — merge overridden fields into existing steps
5. Return the resolved pipeline definition (same schema as today)

Templates are YAML files in `lcm_core` or a well-known path, loaded once at startup.

### 2.3 Reconciler Decomposition

Split the reconciler into focused modules along its natural section boundaries:

```
application/
  hosted_services/
    lablet_reconciler.py           # ~500 lines — orchestration shell

  services/
    pipeline_executor.py           # (unchanged, 631 lines)
    lifecycle_phase_handler.py     # (unchanged, 211 lines)
    step_registry.py               # NEW ~80 lines — handler registry + protocol
    pipeline_template_resolver.py  # NEW ~150 lines — template merging

    step_handlers/                 # NEW — all step implementations
      __init__.py                  # imports all modules to trigger registration
      instantiation_steps.py       # content_sync, variables, lab_resolve
      port_steps.py                # ports_alloc, tags_sync
      binding_steps.py             # lab_binding, lds_provision, mark_ready
      lab_lifecycle_steps.py       # lab_start, stop_lab, wipe_lab
      lds_steps.py                 # deregister_lds
      archive_steps.py             # archive
      evidence_steps.py            # capture_configs, screenshots, pcaps, package
      grading_steps.py             # load_rubric, evaluate, record_score
      cml_command_step.py          # execute_command_on_cml_node (parameterized)

    reconciler_helpers/            # NEW — extracted helper clusters
      __init__.py
      lab_resolution.py            # resolve, reuse, import (~210 lines)
      lab_record_helpers.py        # find, register, update records (~160 lines)
      lds_helpers.py               # provision, archive, device mapping (~140 lines)
      worker_helpers.py            # enrich, cache, extract host (~100 lines)
      definition_cache.py          # get_definition with cache (~40 lines)
```

What remains in `lablet_reconciler.py`:

- Constructor and DI configuration
- Leader lifecycle (`_become_leader`, `_step_down`)
- Watch + resource listing overrides
- Reconcile router (`_reconcile_inner` status dispatch)
- Pipeline handler management (fire-and-check pattern)
- Service info properties

### 2.4 Step Result Protocol

Standardize the return type for step handlers:

```python
@dataclass
class StepResult:
    status: str          # "completed" | "skipped" | "failed"
    result_data: dict    # payload for downstream steps
    error: str | None    # error message (when status="failed")
    reason: str | None   # reason for skip (when status="skipped")
```

Step handlers return `StepResult` instead of ad-hoc dicts. The executor
unwraps this into the existing progress format.

## 3. Step Handler Protocol

### 3.1 Handler Signature

All step handlers follow a uniform protocol:

```python
async def handler(
    instance: LabletSessionReadModel,   # session being reconciled
    progress: dict[str, Any],           # current pipeline progress
    context: PipelineContext,           # services + accumulated step data
    params: dict[str, Any] | None,     # per-step YAML params (new)
) -> StepResult
```

### 3.2 Accessing Services

Step handlers access SPI clients through `PipelineContext`:

- `context.api` — Control Plane API client
- `context.cml` — CML Labs SPI client
- `context.lds` — LDS SPI client
- `context.definition` — LabletDefinition read model
- `context.steps_data` — accumulated results from prior steps

### 3.3 Accessing Prior Step Results

```python
# In a step handler:
resolve_data = context.steps_data.get("lab_resolve", {})
cml_lab_id = resolve_data.get("cml_lab_id")
```

### 3.4 Parameterized Steps

The `params` dict comes directly from the step definition YAML:

```yaml
- name: transfer_archive
  handler: execute_command_on_cml_node
  params:
    action: transfer_file
    target_node: ubuntu-desktop
    source_url: "$STEPS.content_sync.archive_url"
    target_path: /tmp/lab-files.tar.gz
```

The executor resolves `$STEPS.*` expressions in param values before passing
them to the handler (same resolution logic as `outputs`).

## 4. Pipeline Template Schema

### 4.1 Base Templates

Standard templates are defined as YAML and registered by name:

| Template Name | Trigger | Steps |
|---|---|---|
| `standard-instantiate` | `on_status:instantiating` | content_sync → variables → lab_resolve → ports_alloc → tags_sync → lab_binding → lab_start → lds_provision → mark_ready |
| `standard-teardown` | `on_status:stopping` | stop_lab → deregister_lds + wipe_lab → archive |
| `standard-collect-evidence` | `on_status:collecting` | capture_configs → capture_screenshots + export_pcaps → package_evidence |
| `standard-compute-grading` | `on_status:grading` | load_rubric → evaluate → record_score |

### 4.2 Customization Operators

| Operator | Effect |
|---|---|
| `extends` | Names the base template to start from |
| `insert_after.<step>` | Injects a list of steps after the named step |
| `insert_before.<step>` | Injects a list of steps before the named step |
| `overrides.<step>` | Merges fields into the named step definition |
| `remove` | List of step names to remove from the base |

### 4.3 Full Override

If `extends` is omitted, the pipeline is treated as a complete inline
definition (backward compatible with current behavior).

## 5. Backward Compatibility

- Definitions with inline `pipelines` (no `extends`) continue to work unchanged
- The `StepDispatcher` type alias becomes more specific but existing
  `_build_step_dispatcher()` call sites are updated in the same PR
- `PipelineExecutor.execute()` signature is unchanged
- Existing tests for `PipelineExecutor` and `LifecyclePhaseHandler` remain valid

## 6. Implementation Phases

| Phase | Scope | Risk | Lines Changed |
|---|---|---|---|
| **1. Step Handler Registry** | `step_registry.py`, `step_handlers/`, executor `params`, `StepResult` | Medium — touches dispatcher | ~1200 new, ~100 modified |
| **2. Reconciler Helpers** | `reconciler_helpers/` extraction | Low — pure move-and-import | ~650 moved, ~50 modified |
| **3. Pipeline Templates** | `PipelineTemplateResolver`, standard template YAMLs | Low — additive | ~300 new |
| **4. CML Command Step** | `cml_command_step.py` | Low — new handler | ~120 new |
| **5. Divergent Seeds** | 2-3 new definition YAMLs | Low — data only | ~300 new |

## 7. Alternatives Considered

### 7.1 Remove Pipelines From Definitions (Option B from review)

**Rejected.** With divergent pipelines as a confirmed requirement, removing
YAML pipeline definitions would force all workflow variations into code.
This defeats the purpose of definition-driven customization.

### 7.2 Full Plugin Architecture via DI (Option C from review)

**Deferred.** Registering step handlers as DI services adds complexity without
clear benefit given that handlers are stateless functions. The decorator-based
registry achieves the same decoupling with less ceremony. Can be revisited if
handlers need stateful dependencies beyond `PipelineContext`.

### 7.3 Keep Status Quo

**Rejected.** The 2948-line reconciler with copy-pasted pipelines is
unmaintainable. New step types (CML node commands) cannot be added without
the registry + params pattern.

## 8. Consequences

### Positive

- New step handlers can be added without touching the reconciler
- Divergent pipelines are expressed declaratively in definition YAML
- Pipeline duplication eliminated via templates
- Reconciler reduced from ~2948 to ~500 lines
- Step handlers are independently testable

### Negative

- Template resolution adds a resolution layer (debugging requires understanding merge)
- Registry relies on import side-effects (all handler modules must be imported)
- Migration of 20 step methods requires careful testing

### Risks

- Template merge conflicts (mitigated by validation at resolve time)
- Circular import potential in step handlers (mitigated by `PipelineContext` carrying all deps)
