# ADR-044: Content-Driven Lifecycle Engine (Scenario Engine)

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-06-05 |
| **Deciders** | LCM architects |
| **Related ADRs** | [ADR-034](ADR-034-pipeline-executor.md), [ADR-038](ADR-038-step-handler-registry-and-reconciler-decomposition.md), [ADR-037](ADR-037-timeslot-management.md) |
| **Supersedes** | None (extends ADR-038) |
| **Sprint** | J+ (lablet-controller) |

## 1. Context

### 1.1 Current State (Post ADR-038)

ADR-038 introduced the `@step_handler` registry and decomposed the monolithic reconciler
into a package of per-step handler modules. The subsequent refactoring (AD-STEP-001)
completed the one-file-per-step convention, yielding 21 individually testable step
handler modules under `application/services/step_handlers/`.

**What works well:**

- `PipelineExecutor` provides DAG ordering, skip_when, retry, timeout, progress persistence
- `PipelineTemplateResolver` enables `extends`/`overrides`/`remove` composition
- Step handlers are stateless functions registered by name
- Pipeline definitions live in LabletDefinition seed YAML

**What is limiting:**

- All step execution occurs inside the lablet-controller reconciler process
- Step handlers directly import infrastructure clients (`CmlLabsSpiClient`, `LdsSpiClient`)
- No separation between "what the scenario needs" (policy) and "how to accomplish it" (mechanics)
- The `PipelineContext` dataclass has grown to 20+ fields (god context)
- Future content-defined pipelines (PAv1/) have no injection point
- No versioning of step behavior — handler changes affect all definitions simultaneously
- Grading, evidence, and post-init steps are stubs with no execution path yet

### 1.2 Vision: Content-Driven Session Lifecycle

All sessions share the same **overall lifecycle** (the state machine from AD-044):

```
PENDING → SCHEDULED → INSTANTIATING → READY → RUNNING →
    (COLLECTING → GRADING →) STOPPING → ARCHIVED
```

But **what happens at each phase** is unique per session type, defined by the form's
content package rather than hardcoded in the platform. The lifecycle phases are
platform-owned gates; the steps within each phase are content-owned operations.

### 1.3 Content Package Evolution

Currently, content packages use a `RCUv1/` folder structure:

```
exam-ccnp-test-v1-lab-1.1/
├── images/                  # Node definition images
├── resources/               # Student materials
├── content/                 # LDS content.xml, devices.json
├── mosaic_meta.json         # LDS metadata
└── RCUv1/                   # Remote Configuration Unit v1
    ├── cml.yaml             # CML topology definition
    ├── pod.xml              # Pod layout for LDS
    ├── grade.xml            # Grading rules (legacy format)
    └── devices.json         # Device-to-port mapping
```

The proposed `PAv1/` (Platform Automation v1) folder adds lifecycle orchestration:

```
exam-ccnp-test-v1-lab-1.1/
├── ...existing...
├── RCUv1/                   # Retained for backward compat
└── PAv1/                    # Platform Automation v1
    ├── lifecycle.yaml       # Phase definitions + step DAG per phase
    ├── init/                # Initialization steps (post-import setup)
    │   ├── transfer_archive.yaml
    │   └── configure_services.yaml
    ├── grading/             # Grading configuration
    │   ├── rubric.yaml      # Grading rules (structured)
    │   └── evidence_spec.yaml
    ├── restore/             # Restore process (for retakes)
    │   └── restore.yaml
    └── scoring/             # Score report template
        └── report_template.yaml
```

### 1.4 The Execution Question

**Should the lablet-controller execute step handlers directly, or should a
dedicated Scenario Engine service handle execution?**

## 2. Decision

### 2.1 Introduce a Scenario Engine as a logical subsystem WITHIN lablet-controller

We adopt a **logical separation** rather than a physical service split:

```
lablet-controller/
├── application/
│   ├── hosted_services/
│   │   └── lablet_reconciler.py      # Lifecycle gate orchestrator
│   └── services/
│       ├── scenario_engine/           # NEW: Scenario Engine subsystem
│       │   ├── __init__.py
│       │   ├── engine.py             # ScenarioEngine class
│       │   ├── step_executor.py      # Replaces pipeline_executor.py
│       │   ├── step_protocol.py      # StepHandler base class + protocol
│       │   ├── step_context.py       # Typed, scoped context (replaces PipelineContext)
│       │   ├── step_discovery.py     # Auto-discovery + registration
│       │   └── content_loader.py     # PAv1/ lifecycle.yaml parser
│       ├── step_handlers/            # Concrete step implementations (unchanged)
│       │   ├── _helpers.py
│       │   ├── lab_resolve_step.py
│       │   ├── lab_start_step.py
│       │   └── ...
│       └── pipeline_template_resolver.py  # Retained for seed YAML compat
```

### 2.2 Rationale: Why NOT a Separate Service

| Factor | Separate Service | Logical Subsystem |
|--------|------------------|-------------------|
| **Latency** | Network hop per step dispatch | In-process, zero overhead |
| **State sharing** | Needs API/cache for progress | Direct dict access |
| **Deployment complexity** | Another container, leader election | Part of existing HA reconciler |
| **CML API access** | Needs its own CML credentials | Already has SPI clients |
| **Failure domain** | Step failure ≠ reconciler failure | Same process — but isolated via asyncio.Task |
| **Future extraction** | Easy if interface is clean | Clean interface enables future extraction |

**Key insight:** The step handlers are I/O-bound (HTTP calls to CML, LDS, CPA). They
don't benefit from separate compute. What they need is **isolation of concerns** —
the reconciler should not know _how_ steps execute, only _that_ they complete.

The `ScenarioEngine` provides this boundary. If a future scale-out requirement emerges
(e.g., 1000 concurrent sessions), the engine interface is the extraction seam.

### 2.3 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ lablet-controller                                               │
│                                                                 │
│  ┌──────────────────────┐       ┌────────────────────────────┐  │
│  │ LabletReconciler     │       │ ScenarioEngine             │  │
│  │                      │       │                            │  │
│  │ • Lifecycle gates    │──────▶│ • Phase → step DAG         │  │
│  │ • Timeslot mgmt     │       │ • Step dispatch + retry    │  │
│  │ • Status transitions │       │ • Progress tracking        │  │
│  │ • Watch handling     │       │ • Content-defined steps    │  │
│  └──────────────────────┘       │ • PAv1/ content loading    │  │
│                                 └───────────┬────────────────┘  │
│                                             │                   │
│                          ┌──────────────────┼──────────────┐    │
│                          │                  │              │    │
│                    ┌─────▼─────┐  ┌────────▼───┐  ┌──────▼──┐ │
│                    │lab_resolve│  │lab_start   │  │lds_prov │ │
│                    │_step.py   │  │_step.py    │  │_step.py │ │
│                    └───────────┘  └────────────┘  └─────────┘ │
│                     StepHandler    StepHandler     StepHandler  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.4 Step Protocol (Typed Base Class)

Replace bare `async def` functions with a protocol-based approach that preserves
backward compatibility:

```python
# application/services/scenario_engine/step_protocol.py

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from application.services.step_registry import StepResult


@dataclass
class StepMetadata:
    """Declarative metadata for a step handler — introspectable by the engine."""
    name: str
    version: int = 1
    description: str = ""
    timeout_seconds: int = 60
    retry_max_attempts: int = 1
    retry_delay_seconds: int = 5
    optional: bool = False
    idempotent: bool = True
    # Declared input/output schemas for compile-time DAG validation
    requires_from: list[str] = field(default_factory=list)  # upstream step names
    produces: list[str] = field(default_factory=list)  # result_data keys


class StepHandler(ABC):
    """Base class for step handlers.

    Subclasses declare metadata as class-level attributes and implement
    ``execute()``. The engine uses metadata for DAG construction, timeout
    enforcement, retry logic, and observability.

    Backward Compatibility:
        Existing @step_handler functions remain supported — the engine wraps
        them in a FunctionStepHandler adapter automatically.
    """
    metadata: ClassVar[StepMetadata]

    @abstractmethod
    async def execute(self, ctx: StepContext) -> StepResult:
        """Execute the step logic.

        Args:
            ctx: Scoped execution context with typed access to dependencies,
                 upstream results, and session state.

        Returns:
            StepResult indicating completed/skipped/failed + result_data.
        """
        ...
```

### 2.5 Scoped Step Context (Replaces PipelineContext God Object)

```python
# application/services/scenario_engine/step_context.py

@dataclass(frozen=True)
class StepContext:
    """Immutable, scoped context for a single step execution.

    Unlike PipelineContext (20+ mutable fields), StepContext provides:
    - Typed access to session and definition
    - Read-only view of upstream step results
    - Service locator for SPI clients (lazy resolution)
    - No mutable shared state (eliminates cross-step coupling)
    """
    session: LabletSessionReadModel
    definition: LabletDefinitionReadModel
    worker: WorkerInfo  # ip, cml_username, cml_password, region
    upstream_results: Mapping[str, StepResultData]  # read-only
    services: ServiceAccessor  # .cml, .lds, .api (lazy-resolved)
    params: Mapping[str, Any]  # step-specific params from YAML
```

### 2.6 Content-Driven Pipeline Loading (PAv1/)

```python
# application/services/scenario_engine/content_loader.py

class ContentLoader:
    """Loads lifecycle definitions from PAv1/ or falls back to seed YAML templates."""

    async def load_phase_pipeline(
        self,
        definition: LabletDefinitionReadModel,
        phase: LifecyclePhase,
    ) -> PipelineDefinition:
        """Resolve the step DAG for a lifecycle phase.

        Resolution order:
        1. PAv1/lifecycle.yaml from content package (if synced)
        2. LabletDefinition.pipelines from seed YAML
        3. Standard template via PipelineTemplateResolver
        """
        ...
```

### 2.7 Lifecycle Phase Mapping

| Phase | Trigger | Engine Responsibility |
|-------|---------|---------------------|
| `instantiate` | Status → INSTANTIATING | Import lab, allocate ports, start, provision LDS |
| `ready_check` | Status → READY | Verify lab convergence (optional health check) |
| `collect` | Status → COLLECTING | Capture configs, screenshots, pcaps |
| `grade` | Status → GRADING | Load rubric, evaluate, record score |
| `teardown` | Status → STOPPING | Stop lab, deregister LDS, wipe, archive |
| `restore` | Retake requested | Wipe lab, re-import, restart (PAv1/ defined) |

### 2.8 Migration Strategy

**Phase 1 (This Sprint):** Structural preparation

- Introduce `scenario_engine/` package with `StepHandler` protocol
- Create `FunctionStepAdapter` to wrap existing `@step_handler` functions
- Move `pipeline_executor.py` logic into `scenario_engine/step_executor.py`
- All existing tests continue to pass (adapter preserves behavior)

**Phase 2:** Typed context migration

- Introduce `StepContext` alongside `PipelineContext`
- Migrate step handlers one-by-one to class-based `StepHandler`
- Add typed result dataclasses per step

**Phase 3:** Content-driven loading

- Implement `ContentLoader` for PAv1/ lifecycle.yaml
- Add `lifecycle.yaml` schema definition
- Implement content-sync extraction of PAv1/ artifacts
- Deprecate inline pipeline definitions in seed YAML

**Phase 4:** Advanced features

- Step versioning (`lab_resolve@v2`)
- Grading engine integration
- Evidence collection subsystem
- Restore process support
- Warm-pool pre-instantiation

## 3. Consequences

### 3.1 Positive

- **Clean boundary:** Reconciler is lifecycle-gate logic only; engine handles step mechanics
- **Content-driven:** Lab authors define their own lifecycle steps without platform changes
- **Testable:** Engine and steps testable in isolation with mock contexts
- **Extractable:** If future scale requires it, ScenarioEngine is the service extraction seam
- **Versioned:** Step implementations can be versioned; definitions pin versions
- **Observable:** StepMetadata enables rich pipeline observability (UI pipeline tab)

### 3.2 Negative

- Migration cost: gradual — adapter pattern ensures no big-bang rewrite
- Learning curve: new StepHandler class vs. previous bare function convention
- Temporary duplication during Phase 1-2 (both patterns coexist)

### 3.3 Neutral

- No new deployment artifact (stays in lablet-controller)
- Existing seed YAML format remains valid indefinitely (template resolver preserved)
- PAv1/ is additive — RCUv1/ continues to work as-is

## 4. Implementation Notes

### 4.1 File Layout (Phase 1 Target)

```
application/services/scenario_engine/
├── __init__.py              # Public API: ScenarioEngine, StepHandler, StepContext
├── engine.py                # ScenarioEngine — dispatches phase pipelines
├── step_executor.py         # DAG executor (migrated from pipeline_executor.py)
├── step_protocol.py         # StepHandler ABC + StepMetadata + FunctionStepAdapter
├── step_context.py          # StepContext (typed, scoped, immutable)
├── step_discovery.py        # Auto-imports step_handlers/, builds registry
├── content_loader.py        # PAv1/ lifecycle.yaml parser + fallback chain
└── models/
    ├── __init__.py
    ├── pipeline_definition.py  # PipelineDefinition, StepDefinition dataclasses
    ├── lifecycle_phase.py      # LifecyclePhase enum
    └── worker_info.py          # WorkerInfo value object
```

### 4.2 PAv1/lifecycle.yaml Schema (Draft)

```yaml
# PAv1/lifecycle.yaml — Content-defined session lifecycle
schema_version: "1.0"

phases:
  instantiate:
    steps:
      - name: lab_resolve
        handler: lab_resolve@v1
        timeout_seconds: 120
        retry: { max_attempts: 2, delay_seconds: 10 }

      - name: ports_alloc
        handler: ports_alloc@v1
        needs: [lab_resolve]
        skip_when: "not $DEFINITION.port_template"

      - name: transfer_student_files
        handler: execute_command_on_cml_node
        needs: [lab_start]
        params:
          action: transfer_file
          target_node: ubuntu-desktop
          source_url: "${CONTENT_BASE_URL}/resources/student-archive.tar.gz"
          target_path: /tmp/lab-files.tar.gz

      - name: lab_start
        handler: lab_start@v1
        needs: [ports_alloc, tags_sync]

      - name: mark_ready
        handler: mark_ready@v1
        needs: [lab_start, lds_provision]

  grade:
    steps:
      - name: load_rubric
        handler: load_rubric@v1
        params:
          rubric_source: "PAv1/grading/rubric.yaml"

      - name: evaluate
        handler: evaluate@v1
        needs: [load_rubric, capture_configs]

      - name: record_score
        handler: record_score@v1
        needs: [evaluate]

  restore:
    description: "Reset lab for student retake"
    steps:
      - name: wipe_lab
        handler: wipe_lab@v1
      - name: lab_start
        handler: lab_start@v1
        needs: [wipe_lab]
      - name: reconfigure
        handler: execute_command_on_cml_node
        needs: [lab_start]
        params:
          action: transfer_file
          target_node: ubuntu-desktop
          source_url: "${CONTENT_BASE_URL}/resources/student-archive.tar.gz"
          target_path: /tmp/lab-files.tar.gz
```

### 4.3 Backward Compatibility Contract

1. Existing `@step_handler("name")` decorated functions continue to work — the engine
   wraps them via `FunctionStepAdapter`
2. Existing seed YAML `extends: standard-instantiate` continues to resolve via
   `PipelineTemplateResolver`
3. Existing `PipelineContext` passed to adapted functions as before
4. No change to etcd keys, CPA API, or SSE event schema

### 4.4 Testing Strategy

- Unit: Each StepHandler tested with mock StepContext
- Integration: ScenarioEngine with real step registry, mock SPI clients
- Contract: PAv1/lifecycle.yaml validated against JSON Schema
- Regression: All existing 505+ tests pass without modification (Phase 1)

## 5. References

- ADR-034: Pipeline Executor (DAG execution, progress persistence)
- ADR-038: Step Handler Registry (decorator-based registration, reconciler decomposition)
- AD-STEP-001: One step per file convention
- AD-PIPELINE-012: Pipeline template resolver with extends/overrides
- AD-044: LabletSession lifecycle state machine
