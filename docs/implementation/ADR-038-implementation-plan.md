# ADR-038 Implementation Plan: Step Handler Registry & Reconciler Decomposition

**Version:** 2.0.0 — Updated 2026-03-23
**ADR:** [ADR-038](../architecture/adr/ADR-038-step-handler-registry-and-reconciler-decomposition.md)

## Overview

This document details the implementation plan for ADR-038 across 5 phases
plus 5 follow-up tasks identified during the gap analysis.

**Target:** Reduce `lablet_reconciler.py` from ~2988 → ~1200 lines, enable
divergent pipeline definitions, and eliminate pipeline YAML duplication.

**Current state:** Phases 1, 3, 4 are complete. The reconciler is at 2988 lines.
The registry-based dispatch is active but **8 parity gaps** between registry
handlers and the original reconciler `_step_*` methods must be closed before
the dead code can be removed.

---

## Phase 1: Step Handler Registry + Params Support ✅ COMPLETE

**Goal:** Decouple step handlers from the reconciler via a registry pattern.
Add `params` support to the executor so YAML step definitions can pass
parameters to handlers.

### 1.1 New Files ✅

```
application/services/
  step_registry.py                    # Registry, StepResult, @step_handler decorator
  step_handlers/
    __init__.py                       # Import all modules to trigger registration
    instantiation_steps.py            # content_sync, variables, lab_resolve
    port_steps.py                     # ports_alloc, tags_sync
    binding_steps.py                  # lab_binding, lds_provision, mark_ready
    lab_lifecycle_steps.py            # lab_start, stop_lab, wipe_lab
    lds_steps.py                      # deregister_lds
    archive_steps.py                  # archive
    evidence_steps.py                 # capture_configs, screenshots, pcaps, package (stubs)
    grading_steps.py                  # load_rubric, evaluate, record_score (stubs)
```

### 1.2 Step Handler Protocol ✅

```python
@step_handler("content_sync")
async def step_content_sync(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    return StepResult.completed({"key": "value"})
```

### 1.3 Modified Files ✅

| File | Change | Status |
|------|--------|--------|
| `pipeline_executor.py` | `_execute_step()` passes `step.get("params")` and `context` to dispatcher | ✅ |
| `lablet_reconciler.py` | `_build_step_dispatcher()` delegates to registry with `getattr` fallback | ✅ |
| `test_pipeline_executor.py` | Updated 5 mock dispatcher signatures (3→5 args) | ✅ |
| `test_instantiation_pipeline.py` | 3 tests patched with `get_handler` mock, fixture updated | ✅ |

### 1.4 Tests ✅

- `test_step_registry.py` — 14 tests: registration, lookup, params, StepResult
- `test_pipeline_executor.py` — 76 tests: all passing with updated dispatcher mocks
- `test_instantiation_pipeline.py` — 66 tests: all passing

### 1.5 NOT YET DONE from Phase 1

> ⚠️ The original plan called for **removing** all `_step_*` methods from the
> reconciler. This was **intentionally deferred** because the registry handlers
> are simplified copies that lack parity with the reconciler originals. See
> **Task 1 (Parity Gaps)** below.

---

## Phase 2: Reconciler Helpers Extraction ⏳ NOT STARTED

**Goal:** Extract helper method clusters from the reconciler into
focused modules. Pure refactoring — no behavioral changes.

### 2.1 New Files

```
application/services/reconciler_helpers/
  __init__.py                          # Re-exports for convenience
  lab_resolution.py                    # resolve_lab_for_instance, try_reuse, import_fresh (~174 lines)
  lab_record_helpers.py                # find_lab_record_id, register_lab_record, update_status (~130 lines)
  lds_helpers.py                       # provision_lds_session, archive_lds_session, build_device_access (~181 lines)
  worker_helpers.py                    # enrich_with_worker_details, get_cached_worker, extract_host (~83 lines)
  definition_cache.py                  # get_definition with cache (~22 lines)
  observation_helpers.py               # observe_and_report (~43 lines)
  run_history.py                       # record_lab_run_completed (~41 lines)
```

**Total extraction: ~703 lines from reconciler → helper modules.**

> **Note:** This phase is deferred until after Task 1 (parity gaps) and Task 2
> (dead code removal). The helpers will be extracted from the reconciler into
> standalone modules that both the reconciler and step handlers can use.

### 2.2 What Remains in lablet_reconciler.py (~1200 lines)

| Section | Methods | ~Lines |
|---------|---------|--------|
| Imports + class docstring | — | 98 |
| Constructor + `configure()` | `__init__`, `configure` | 131 |
| Leader lifecycle | `_become_leader`, `_step_down` | 77 |
| Watch overrides | `watch_prefix`, `on_watch_event`, `fetch_resource_by_id` | 115 |
| Resource listing | `list_resources`, `get_resource_id` | 40 |
| Reconcile routing | `reconcile`, `_reconcile_inner` | 117 |
| Simple handlers | `_handle_scheduled`, `_handle_expired`, `_handle_ready`, `_handle_running` | 157 |
| Generic fire-and-check + cleanup | `_handle_pipeline_phase` + 4 delegators | 130 |
| `_handle_observe_resources_event` | — | 38 |
| Pipeline infrastructure | 6 methods | 218 |
| Stats / readiness / info | 3 methods | 79 |

---

## Phase 3: Pipeline Templates ✅ COMPLETE

**Goal:** Define standard pipeline templates once. Definitions reference
templates and customize via insert/override operators.

### 3.1 New Files ✅

```
application/services/
  pipeline_template_resolver.py        # PipelineTemplateResolver + 4 standard templates
```

Templates defined as Python dicts (not external YAML). 4 standard templates:

- `standard-instantiate` — 9 steps from content_sync to mark_ready
- `standard-teardown` — 4 steps from stop_lab to archive
- `standard-collect-evidence` — 4 steps from capture_configs to package_evidence
- `standard-compute-grading` — 3 steps from load_rubric to record_score

### 3.2 Template Operators ✅

| Operator | Purpose |
|----------|---------|
| `extends` | Inherit from a base template |
| `insert_after` | Inject steps after a named anchor |
| `insert_before` | Inject steps before a named anchor |
| `overrides` | Modify fields on existing steps |
| `remove` | Drop steps from the base |

### 3.3 Integration ✅

- Resolver wired into `_get_pipeline_def()` with exception-safe fallback
- `_template_resolver` initialized in reconciler `__init__`
- Backward compatible — pipelines without `extends` pass through unchanged

### 3.4 Tests ✅

- `test_pipeline_template_resolver.py` — 29 tests: all operators, error cases,
  combined operators, real-world DevNet Expert scenario

---

## Phase 4: `execute_command_on_cml_node` ✅ COMPLETE

**Goal:** Build a parameterized step handler for arbitrary CML node
operations, enabling divergent pipeline definitions.

### 4.1 New File ✅

```
application/services/step_handlers/
  cml_command_step.py                  # ~290 lines
```

### 4.2 Supported Actions ✅

| Action | Description |
|--------|-------------|
| `transfer_file` | Upload file to node filesystem |
| `execute_command` | Run CLI command on node |
| `shut_interface` | Admin-down interface |
| `no_shut_interface` | Admin-up interface |
| `extract_configs` | Extract running config |

> **Note:** Some CML SPI methods (`upload_file_to_node`, `execute_node_command`,
> `set_interface_state`, `get_node_config`) may not exist yet on `CmlLabsSpiClient`.
> They need to be added when the CML API supports them.

---

## Phase 5: Divergent Seed Definitions ⏳ NOT STARTED

**Goal:** Migrate existing seed definitions to use `extends` templates
and add divergent definitions with custom CML commands.

### 5.1 Updated Seed Files

Existing definitions migrated from inline pipelines to `extends: standard-instantiate`.

### 5.2 New Divergent Definitions

At least one definition using `insert_after` to inject `execute_command_on_cml_node`
steps (e.g., DevNet Expert lab with file transfer + interface shutdown).

---

## Gap Analysis Tasks (Post-Phase 1 Discovery)

### Task 1: Close Parity Gaps in Registry Handlers 🔴 CRITICAL

**Problem:** The `_build_step_dispatcher()` tries the registry first. Since all 20
step names are registered, the reconciler's `_step_*` methods **never execute** — they
are dead code. But the registry versions are simplified copies missing key behaviors:

| Handler | Missing Behavior | Risk |
|---------|-----------------|------|
| `lab_resolve` | No lab reuse (`_try_reuse_existing_lab`), no `_resolved_lab_ids` tracking, no `_freshly_imported_sessions` | 🔴 Severe |
| `archive` | No `_record_lab_run_completed()`, no `_update_lab_record_status(WIPED)` | 🔴 Severe |
| `lab_start` | No ghost-lab ORPHAN marking via CPA | 🟡 Medium |
| `lab_binding` | No `_find_lab_record_id` / `_register_lab_record` fallback chain | 🟡 Medium |
| `lds_provision` | Simplified `_build_device_access_list` (no multi-tag label suffixing) | 🟡 Medium |
| `content_sync` | No `_content_sync_service.request_sync()` trigger on failure | 🟡 Medium |
| `wipe_lab` | No `_update_lab_record_status(WIPED)` side-effect | 🟡 Medium |
| `mark_ready` | No cleanup of tracking dicts | 🟢 Low |

**Solution: Enrich `PipelineContext`** with reconciler helper references so registry
handlers can call the same logic:

```python
@dataclass
class PipelineContext:
    # ... existing fields ...

    # ADR-038 Task 1: Helper callables for parity with reconciler
    resolve_lab: Callable | None = None           # wraps _resolve_lab_for_instance
    find_lab_record_id: Callable | None = None    # wraps _find_lab_record_id
    register_lab_record: Callable | None = None   # wraps _register_lab_record
    update_lab_record_status: Callable | None = None
    build_device_access_list: Callable | None = None
    record_lab_run_completed: Callable | None = None
    content_sync_service: Any | None = None

    # Tracking dicts (reconciler instance state, passed by reference)
    resolved_lab_ids: dict | None = None
    freshly_imported_sessions: set | None = None
```

Then update each handler to use the enriched context instead of inline logic.

**Files:**

- `application/models/pipeline_context.py` — add fields
- `application/hosted_services/lablet_reconciler.py` — populate fields in `_build_pipeline_context()`
- `application/services/step_handlers/instantiation_steps.py` — `lab_resolve`, `content_sync`
- `application/services/step_handlers/binding_steps.py` — `lab_binding`, `lds_provision`, `mark_ready`
- `application/services/step_handlers/lab_lifecycle_steps.py` — `lab_start`, `wipe_lab`
- `application/services/step_handlers/archive_steps.py` — `archive`

### Task 2: Delete Dead `_step_*` Methods

**Prerequisite:** Task 1 complete (parity gaps closed).

Remove all 20 `_step_*` methods (~727 lines) and 2 stale no-ops
(`_bind_lab_to_instance`, `_release_lab_binding`, ~29 lines) from the reconciler.
The `getattr` fallback path in `_build_step_dispatcher()` becomes unreachable but
is kept for safety (zero-cost).

### Task 3: Extract Reconciler Helpers (Phase 2)

Extract helper method groups into `reconciler_helpers/` modules as described in
Phase 2 above. The reconciler delegates to these modules via the enriched
`PipelineContext` or direct imports.

### Task 4: Deduplicate Fire-and-Check Handlers

The four handlers (`_handle_instantiating`, `_handle_collecting`, `_handle_grading`,
`_handle_stopping`) share identical structure. Extract to a generic method:

```python
async def _handle_pipeline_phase(
    self, instance, pipeline_name, on_max_retry_exhausted=None
) -> ReconciliationResult:
```

**Savings:** 398 lines → ~130 lines (~270 lines saved).

### Task 5: Update Seed Definitions (Phase 5)

Migrate existing YAML seed definitions to use `extends: standard-instantiate`
and create divergent definitions.

---

## Execution Order

```
Task 1 (parity gaps) ──▶ Task 2 (delete dead code) ──▶ Task 3 (extract helpers)
         │                        │                           │
         ▼                        ▼                           ▼
    ~0 line Δ             −756 lines               −703 lines (moved)
                                                          │
                                              Task 4 (dedup handlers)
                                                          │
                                                          ▼
                                                   −270 lines
                                                          │
                                              Task 5 (seed definitions)
```

**Projected final size:** 2988 → ~1229 lines (59% reduction).

---

## Test Strategy

| Phase/Task | Test Files | Status |
|-----------|-----------|--------|
| Phase 1 | `test_step_registry.py` (14 tests) | ✅ 14 passed |
| Phase 1 | `test_pipeline_executor.py` (76 tests) | ✅ 76 passed |
| Phase 1 | `test_instantiation_pipeline.py` (66 tests) | ✅ 66 passed |
| Phase 3 | `test_pipeline_template_resolver.py` (29 tests) | ✅ 29 passed |
| Task 1 | Update existing step handler tests for enriched context | ⏳ |
| Task 2 | Run full suite — verify no regressions after dead code removal | ⏳ |
| Task 3 | `test_lab_resolution.py`, `test_lab_record_helpers.py` (new) | ⏳ |
| Task 4 | Update `_handle_*` tests for generic method | ⏳ |
| Phase 5 | Verify seed loading with templates | ⏳ |

**Full suite baseline: 503 passed, 27 skipped, 0 failures.**
