# ADR-044: ScenarioEngine — Pod Automation as a Separate Service

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed (Rev 2 — supersedes Rev 1 in-process design) |
| **Date** | 2026-06-05 |
| **Deciders** | LCM architects |
| **Related ADRs** | [ADR-034](ADR-034-pipeline-executor.md), [ADR-038](ADR-038-step-handler-registry-and-reconciler-decomposition.md), [ADR-037](ADR-037-timeslot-management.md) |
| **Supersedes** | ADR-044 Rev 1 (in-process ScenarioEngine subsystem) |
| **Sprint** | K+ (platform architecture) |

---

## 1. Context

### 1.1 Current State (Post ADR-038)

ADR-038 introduced the `@step_handler` registry and decomposed the monolithic reconciler
into a package of per-step handler modules. The subsequent refactoring (AD-STEP-001)
completed the one-file-per-step convention, yielding 21 individually testable step
handler modules under `lablet-controller/application/services/step_handlers/`.

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
- No multi-adapter support — only CML-on-AWS is implemented; ROC/Proxmox require different execution paths
- LCM services are tightly coupled to pod automation — scaling them independently is impossible

### 1.2 Vision: Separate Concerns at Service Level

The **Lablet Cloud Manager (LCM)** and the **ScenarioEngine (SE)** consume the same
content package (`PAv1/`) but at different abstraction levels:

| Concern | LCM | SE |
|---------|-----|-----|
| **Reads from PAv1/** | Top-level phase ordering, SE job triggers | Low-level task definitions, adapter calls |
| **Owns** | Session lifecycle, resource scheduling, worker assignment | Job execution, report generation, adapter dispatch |
| **Persistence** | LabletSession, LabletDefinition, Worker, LabRecord | PodDefinition, Job progress/results |
| **Communication** | CQRS commands, etcd watches, CPA REST | Fire-and-forget jobs, CloudEvents, SSE streams |

> "LCM consumes the top-level orchestration definition while the SE consumes the
> low-level IO-bound calls to adapters."

### 1.3 Content Package Structure (PAv1/)

```
exam-ccnp-test-v1-lab-1.1/
├── images/                  # Node definition images
├── resources/               # Student materials
├── content/                 # LDS content.xml, devices.json
├── mosaic_meta.json         # LDS metadata
├── RCUv1/                   # Retained for backward compat
│   ├── cml.yaml             # CML topology definition
│   ├── pod.xml              # Pod layout for LDS
│   ├── grade.xml            # Grading rules (legacy format)
│   └── devices.json         # Device-to-port mapping
└── PAv1/                    # POD Automation v1
    ├── manifest.yaml        # Pod type, required adapters, version
    ├── lifecycle.yaml       # Phase → task DAG (DSL)
    ├── scenarios/           # Reusable scenario definitions (DSL)
    │   ├── provision.yaml
    │   └── teardown.yaml
    ├── grading/             # Grading configuration
    │   ├── rubric.yaml      # Per-item grading rules
    │   └── evidence_spec.yaml
    ├── restore/             # Restore process (retakes)
    │   └── restore.yaml
    └── reports/             # Phase report templates
        └── grade_report.yaml
```

### 1.4 The Execution Question (Revised)

The Rev 1 design kept the ScenarioEngine as an in-process subsystem. This is now
**superseded** based on the following realizations:

1. **Multi-adapter future** — CML-on-AWS, ROC/RADkit, Proxmox, VMWare require different
   adapter implementations that should not bloat the lablet-controller
2. **Content lifecycle independence** — PodDefinitions have their own lifecycle
   (DEFINED → SYNCHRONIZING → READY → EXPIRED → SUPERSEDED) separate from sessions
3. **Scaling independence** — SE handles I/O-heavy pod automation that can be scaled
   independently from LCM's lightweight state management
4. **Reusability** — Multiple callers (lablet-controller, manual triggers, CI/CD) can
   submit jobs to SE without coupling to LCM internals
5. **DSL runtime** — A proprietary workflow DSL with jq expressions warrants its own
   execution environment with dedicated testing and versioning

---

## 2. Decision

### 2.1 Introduce a ScenarioEngine as a Separate Microservice

The ScenarioEngine is a **standalone FastAPI microservice** that:

- Owns **pod automation execution** (I/O-bound adapter calls)
- Exposes a **fire-and-forget job API** (submit job → get job_id → CloudEvents callback)
- Maintains an **in-memory scenario registry** (Python packages auto-discovered at boot)
- Persists **PodDefinition entities** (content synced on-demand from BlobStorage)
- Executes a **proprietary DSL** (ServerlessWorkflow-inspired, jq expressions)
- Supports **multiple infrastructure adapters** (CML/AWS, ROC/RADkit, Proxmox, VMWare)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Content Layer (BlobStorage / S3)                                           │
│  LAB.zip → PAv1/ + RCUv1/ + images/ + resources/                           │
└────────────────┬─────────────────────────────────────┬──────────────────────┘
                 │ top-level phase defs                 │ full content package
                 ▼                                     ▼
┌────────────────────────────────────┐  ┌──────────────────────────────────────┐
│  LCM (Resource Orchestration)      │  │  ScenarioEngine (Pod Automation)     │
│                                    │  │                                      │
│  ┌────────────┐ ┌───────────────┐  │  │  ┌────────────────────────────────┐  │
│  │control-    │ │lablet-        │  │  │  │ DSL Runtime                    │  │
│  │plane-api   │ │controller     │──┼──┼─▶│ • Task executor (DAG)          │  │
│  │            │ │               │  │  │  │ • jq expression evaluator      │  │
│  │• Sessions  │ │• Lifecycle    │  │  │  │ • Retry/timeout/skip_when      │  │
│  │• Defs      │ │  gates        │  │  │  │ • Progress tracking            │  │
│  │• Workers   │ │• Watch loop   │  │  │  └────────────────────────────────┘  │
│  │• Timeslots │ │• State trans  │  │  │                                      │
│  └────────────┘ └───────────────┘  │  │  ┌────────────────────────────────┐  │
│                                    │  │  │ Scenario Registry (in-memory)  │  │
│  ┌────────────┐ ┌───────────────┐  │  │  │ • lab_resolve@v1              │  │
│  │resource-   │ │worker-        │  │  │  │ • lab_start@v1               │  │
│  │scheduler   │ │controller     │  │  │  │ • execute_command@v1          │  │
│  │            │ │               │  │  │  │ • collect_evidence@v1         │  │
│  │• Timeslots │ │• EC2/CML      │  │  │  │ • grade_item@v1              │  │
│  │• Compat    │ │  provisioning │  │  │  └────────────────────────────────┘  │
│  │  check     │ │• Worker state │  │  │                                      │
│  └────────────┘ └───────────────┘  │  │  ┌────────────────────────────────┐  │
│                                    │  │  │ Adapters                       │  │
│  State transitions stay HERE:      │  │  │ • CmlOnAwsAdapter             │  │
│  • mark_ready, archive, schedule   │  │  │ • RocRadkitAdapter            │  │
│  • session status updates          │  │  │ • ProxmoxAdapter (future)     │  │
│  • timeslot management             │  │  │ • VMWareAdapter (future)      │  │
│  • LDS registration                │  │  └────────────────────────────────┘  │
│                                    │  │                                      │
│  Local adapters (packages):        │  │  ┌────────────────────────────────┐  │
│  • CPA REST client                 │  │  │ PodDefinition Store           │  │
│  • etcd client                     │  │  │ • Lifecycle: DEFINED →        │  │
│  • S3 client (metadata only)       │  │  │   SYNCHRONIZING → READY →     │  │
│  • LDS client                      │  │  │   EXPIRED → SUPERSEDED        │  │
└────────────────────────────────────┘  │  │ • Content: topology, devices, │  │
                                        │  │   grading rules, scenarios     │  │
         CloudEvents ◀─────────────────┤  └────────────────────────────────┘  │
         (job.started, step.completed,  │                                      │
          job.completed, job.faulted)   └──────────────────────────────────────┘
```

### 2.2 Rationale: Why a Separate Service (Reversing Rev 1)

| Factor | In-Process (Rev 1) | Separate Service (Rev 2) |
|--------|-------------------|--------------------------|
| **Multi-adapter** | Bloats lablet-controller with CML+ROC+Proxmox deps | Each adapter self-contained in SE |
| **Content lifecycle** | PodDefinition lifecycle coupled to session lifecycle | Independent PodDefinition aggregate |
| **Scaling** | I/O-heavy automation scales with lightweight state mgmt | Scale pod automation independently |
| **Reusability** | Only lablet-controller can trigger steps | Any caller (CI/CD, manual, LCM) submits jobs |
| **DSL runtime** | Mixed with CQRS/DDD framework | Dedicated execution environment |
| **Testing** | Steps tested against full LCM DI container | SE testable with mock adapters only |
| **Deployment** | Monolith risk (one crash kills reconciler + automation) | Fault isolation (SE crash ≠ LCM crash) |

**Key insight (updated):** The step handlers are I/O-bound and need **multiple
infrastructure adapters** (CML, ROC, Proxmox). They also need their own **content
lifecycle** (PodDefinition) and a **DSL runtime** with jq expressions. This volume of
responsibility warrants a dedicated service with its own deployment, scaling, and
failure domain.

### 2.3 ScenarioEngine Service Architecture

```
scenario-engine/                      # New microservice
├── main.py                           # FastAPI app, DI, lifespan
├── Makefile
├── pyproject.toml
├── Dockerfile
├── api/
│   ├── controllers/
│   │   ├── jobs_controller.py        # POST/GET/DELETE /api/v1/jobs
│   │   ├── content_controller.py     # POST /api/v1/content/sync
│   │   └── scenarios_controller.py   # GET /api/v1/scenarios
│   └── dependencies.py
├── application/
│   ├── commands/
│   │   ├── submit_job_command.py     # SubmitJob + handler
│   │   ├── cancel_job_command.py
│   │   └── sync_content_command.py   # SyncContent + handler
│   ├── queries/
│   │   ├── get_job_query.py
│   │   └── list_scenarios_query.py
│   ├── services/
│   │   ├── dsl_runtime/              # DSL execution engine
│   │   │   ├── executor.py           # Task DAG executor
│   │   │   ├── jq_evaluator.py       # jq expression evaluation
│   │   │   ├── task_dispatcher.py    # Routes task types to handlers
│   │   │   └── data_flow.py          # Input/output/context transforms
│   │   ├── scenario_registry.py      # In-memory registry (@scenario decorator)
│   │   ├── content_ingestion.py      # LAB.zip download, extract, parse
│   │   └── report_generator.py       # Phase report assembly
│   ├── events/
│   │   └── cloud_event_publisher.py  # Emit job lifecycle CloudEvents
│   └── settings.py
├── domain/
│   ├── entities/
│   │   ├── pod_definition.py         # PodDefinition aggregate
│   │   └── job.py                    # Job aggregate (progress, results)
│   ├── value_objects/
│   │   ├── pod_type.py               # PodType enum
│   │   ├── job_status.py             # JobStatus enum
│   │   └── task_result.py            # TaskResult value object
│   ├── events/
│   │   ├── pod_definition_events.py
│   │   └── job_events.py
│   └── repositories/
│       ├── pod_definition_repository.py
│       └── job_repository.py
├── infrastructure/
│   ├── adapters/                     # Infrastructure adapters
│   │   ├── base_adapter.py           # AdapterProtocol ABC
│   │   ├── cml_on_aws_adapter.py     # CML + AWS EC2
│   │   ├── roc_radkit_adapter.py     # ROC + RADkit (CCIE DMZ)
│   │   ├── proxmox_adapter.py        # Proxmox VE (future)
│   │   └── vmware_adapter.py         # VMWare vSphere (future)
│   └── persistence/
│       └── mongo_pod_definition_repository.py
├── scenarios/                         # Registered scenario packages
│   ├── __init__.py                   # Auto-import for registration
│   ├── lab_resolve.py
│   ├── lab_start.py
│   ├── lab_stop.py
│   ├── execute_command.py
│   ├── collect_evidence.py
│   ├── grade_item.py
│   └── ...
└── tests/
```

### 2.4 SE API Contract

#### Job Submission (Fire-and-Forget)

```http
POST /api/v1/jobs
Content-Type: application/json

{
  "definition_id": "exam-ccnp-test-v1-lab-1.1",
  "version": "1.0.0",
  "session_id": "sess-abc123",
  "phase": "instantiate",
  "worker": {
    "ip": "10.0.1.42",
    "cml_username": "admin",
    "cml_password": "***",
    "region": "us-east-1",
    "adapter": "cml_on_aws"
  },
  "variables": {
    "lab_reuse_enabled": true,
    "port_template": "exam-ccnp-v1"
  },
  "callback_url": "http://lablet-controller:8002/api/cloudevents"
}
```

**Response:**

```json
{
  "job_id": "job-7f3a2b",
  "status": "accepted",
  "stream_url": "/api/v1/jobs/job-7f3a2b/stream"
}
```

#### CloudEvent Callbacks

```json
{
  "specversion": "1.0",
  "type": "io.lcm.scenario-engine.job.completed",
  "source": "/scenario-engine/jobs/job-7f3a2b",
  "subject": "sess-abc123",
  "data": {
    "job_id": "job-7f3a2b",
    "phase": "instantiate",
    "status": "completed",
    "duration_seconds": 142,
    "results": {
      "lab_resolve": { "lab_id": "abc", "lab_title": "CCNP Lab 1.1" },
      "lab_start": { "converged": true },
      "lds_provision": { "url": "https://lds.example.com/pod/123" }
    },
    "report_url": "/api/v1/jobs/job-7f3a2b/report"
  }
}
```

#### Content Sync

```http
POST /api/v1/content/sync
Content-Type: application/json

{
  "definition_id": "exam-ccnp-test-v1-lab-1.1",
  "version": "1.0.0",
  "s3_uri": "s3://content-bucket/labs/exam-ccnp-test-v1-lab-1.1/v1.0.0/LAB.zip",
  "pod_type": "cml_on_aws"
}
```

### 2.5 PodDefinition Domain Model

```python
# domain/entities/pod_definition.py

class PodDefinitionStatus(str, Enum):
    DEFINED = "defined"             # Created, awaiting content sync
    SYNCHRONIZING = "synchronizing" # Downloading/extracting from S3
    READY = "ready"                 # Content synced, scenarios validated
    EXPIRED = "expired"             # Timeslot ended, no longer usable
    SUPERSEDED = "superseded"       # Newer version available

@dataclass
class PodDefinitionState:
    id: str
    definition_id: str              # Matches LCM's LabletDefinition
    version: str                    # Semantic version of content
    pod_type: PodType               # CML_ON_AWS, ROC_RADKIT, etc.
    status: PodDefinitionStatus
    content_hash: str               # SHA256 of extracted PAv1/
    synced_at: Optional[datetime]
    topology: Optional[TopologySpec]     # Parsed CML topology
    devices: list[DeviceSpec]            # Device-to-port mapping
    grading_rules: list[GradingRule]     # Per-item grading config
    scenarios: list[ScenarioRef]         # Required scenarios for lifecycle
    lifecycle_phases: dict[str, PhaseDefinition]  # Parsed PAv1/lifecycle.yaml
```

### 2.6 PodDefinitionRef in LCM

The LCM's `LabletDefinition` references a PodDefinition via a value object:

```python
# lcm_core/domain/value_objects/pod_definition_ref.py

@dataclass(frozen=True)
class PodDefinitionRef:
    """Reference from LCM's LabletDefinition to SE's PodDefinition."""
    definition_id: str          # e.g. "exam-ccnp-test-v1-lab-1.1"
    version: str                # e.g. "1.0.0"
    pod_type: PodType           # Required infrastructure type
    content_hash: Optional[str] # Set after sync confirmation
```

### 2.7 Dual Adapter Selection

Adapter selection is a **dual requirement**:

1. **Content declares** — `PAv1/manifest.yaml` specifies `pod_type: cml_on_aws`
2. **Worker matches** — The assigned worker's capabilities must include the required pod_type

```yaml
# PAv1/manifest.yaml
schema_version: "1.0"
pod_type: cml_on_aws
required_adapter_version: ">=1.0.0"
min_resources:
  vcpus: 16
  memory_gb: 64
  storage_gb: 200
```

The **resource-scheduler** enforces compatibility at scheduling time:

```python
# resource-scheduler validation
if worker.pod_type != definition.pod_definition_ref.pod_type:
    raise IncompatibleWorkerError(
        f"Worker {worker.id} is {worker.pod_type}, "
        f"but definition requires {definition.pod_definition_ref.pod_type}"
    )
```

### 2.8 DSL Overview (Proprietary, ServerlessWorkflow-Inspired)

The SE executes a proprietary DSL that borrows syntax and concepts from the
[ServerlessWorkflow specification](https://github.com/serverlessworkflow/specification/blob/main/dsl.md).

#### Expression Language: jq

All runtime expressions use [jq](https://jqlang.github.io/jq/) syntax with
`${}` delimiters in strict mode:

```yaml
# Runtime expression arguments available:
# $context  — workflow context (accumulated state)
# $input    — current task's transformed input
# $output   — current task's raw output (in output.as only)
# $secrets  — secret store (restricted access)
# $task     — current task descriptor
# $workflow  — workflow descriptor
```

#### Task Types

| Type | Purpose | Example |
|------|---------|---------|
| `call` | Invoke a registered scenario | `call: lab_resolve@v1` |
| `do` | Sequential sub-tasks | `do: [step1, step2]` |
| `for` | Iterate over collection | `for: { each: item, in: ${ .devices } }` |
| `fork` | Parallel execution | `fork: { branches: [a, b] }` |
| `set` | Set context variables | `set: { lab_id: ${ .result.id } }` |
| `switch` | Conditional branching | `switch: [{ when: ..., then: ... }]` |
| `try` | Error handling + retry | `try: { ... } catch: { retry: ... }` |
| `raise` | Signal failure | `raise: { error: "device unreachable" }` |
| `wait` | Pause execution | `wait: { seconds: 30 }` |
| `emit` | Publish CloudEvent | `emit: { type: step.completed }` |
| `run` | Execute shell/script | `run: { shell: "show ip route" }` |

#### Data Flow Model

```
Raw Input → input.schema (validate) → input.from (transform) → Task Execution
    → output.as (transform) → output.schema (validate) → export.as (update $context)
    → Next Task (transformed output as raw input)
```

#### Example: PAv1/lifecycle.yaml

```yaml
# PAv1/lifecycle.yaml — Content-defined session lifecycle
document:
  dsl: "1.0.0"
  namespace: lcm
  name: exam-ccnp-test-v1-lab-1.1
  version: "1.0.0"

phases:
  instantiate:
    do:
      - resolveTopology:
          call: lab_resolve@v1
          with:
            definition_id: ${ $context.definition_id }
          output:
            as: ${ { lab_id: .lab_id, lab_title: .title } }

      - allocatePorts:
          call: ports_alloc@v1
          input:
            from: ${ { lab_id: $context.lab_id, template: $context.port_template } }
          if: ${ $context.port_template != null }

      - startLab:
          call: lab_start@v1
          with:
            lab_id: ${ $context.lab_id }
          output:
            as: ${ { converged: .converged, nodes: .nodes } }

      - provisionLds:
          call: lds_provision@v1
          with:
            lab_id: ${ $context.lab_id }
            devices: ${ $context.devices }
          if: ${ ($context.devices | length) > 0 }

  collect:
    do:
      - gatherEvidence:
          for:
            each: item
            in: ${ $context.grading_rules }
          do:
            - collectItem:
                call: collect_evidence@v1
                with:
                  item_id: ${ $item.id }
                  device: ${ $item.target_device }
                  command: ${ $item.collect_command }
                output:
                  as: ${ { [$item.id]: .output } }
                  export:
                    as: ${ $context | .evidence[$item.id] = $output }

  grade:
    do:
      - gradeItems:
          for:
            each: item
            in: ${ $context.grading_rules }
          do:
            - gradeItem:
                call: grade_item@v1
                with:
                  item_id: ${ $item.id }
                  evidence: ${ $context.evidence[$item.id] }
                  expected: ${ $item.expected }
                  scoring: ${ $item.scoring }
                output:
                  as: ${ { score: .score, max: .max, feedback: .feedback } }
                  export:
                    as: ${ $context | .scores[$item.id] = $output }

      - generateReport:
          call: generate_phase_report@v1
          with:
            phase: grade
            scores: ${ $context.scores }
            template: "PAv1/reports/grade_report.yaml"

  teardown:
    do:
      - stopLab:
          call: lab_stop@v1
          with:
            lab_id: ${ $context.lab_id }

      - deregisterLds:
          call: lds_deregister@v1
          with:
            lab_id: ${ $context.lab_id }
          if: ${ $context.lds_registered == true }

      - wipeLab:
          call: lab_wipe@v1
          with:
            lab_id: ${ $context.lab_id }
```

### 2.9 Scenario Registry (In-Memory)

Scenarios are Python modules auto-discovered at SE boot via a decorator pattern:

```python
# scenarios/lab_resolve.py

from scenario_engine.registry import scenario

@scenario(name="lab_resolve", version="v1")
async def lab_resolve(input: dict, adapter: AdapterProtocol, ctx: ExecutionContext) -> dict:
    """Resolve lab topology from CML worker.

    Input:
      definition_id: str — The content definition to resolve

    Output:
      lab_id: str — Resolved CML lab ID
      title: str — Lab title
      nodes: list[dict] — Node list with state
    """
    labs = await adapter.list_labs()
    lab = next((l for l in labs if l["title"] == ctx.expected_title), None)
    if not lab:
        lab = await adapter.import_lab(ctx.topology_file)
    return {"lab_id": lab["id"], "title": lab["title"], "nodes": lab.get("nodes", [])}
```

The registry is **not persisted** — it's the set of `@scenario`-decorated functions
discovered from `scenarios/` package at import time. This is analogous to the existing
`@step_handler` pattern in lablet-controller.

### 2.10 Content Sync Flow

```
Content Owner → CPA: POST /api/definitions/{id}/publish
    CPA: Update LabletDefinition (status=SYNCING, pod_definition_ref populated)
    CPA → SE: POST /api/v1/content/sync {definition_id, version, s3_uri, pod_type}
        SE: Create PodDefinition (status=SYNCHRONIZING)
        SE → S3: Download LAB.zip
        SE: Extract PAv1/, parse lifecycle.yaml, validate scenarios
        SE: Parse devices.json, topology, grading rules
        SE: Update PodDefinition (status=READY, content_hash=sha256)
    SE → CPA: CloudEvent io.lcm.scenario-engine.pod-definition.ready
    CPA: RecordContentSyncResult (status=SYNCED, content_hash confirmed)
```

### 2.11 Step Handler Migration (Option C)

| Stays in LCM (state transitions) | Moves to SE (I/O automation) |
|-----------------------------------|------------------------------|
| `mark_ready_step.py` | `lab_resolve_step.py` |
| `archive_step.py` | `lab_start_step.py` |
| `session_status_update` | `lab_stop_step.py` |
| `timeslot_validation` | `lab_wipe_step.py` |
| `lds_register_step.py` (state) | `execute_command_on_cml_node_step.py` |
| | `ports_alloc_step.py` |
| | `tags_sync_step.py` |
| | `transfer_file_step.py` |
| | `collect_evidence` (new) |
| | `grade_item` (new) |

**Shared capabilities** (in `lcm_core`):

- `lcm_core.infrastructure.content_store` — S3 pull, zip extraction
- `lcm_core.domain.dsl` — DSL parser, task model
- `lcm_core.domain.value_objects.pod_type` — PodType enum, compat checks

### 2.12 Lifecycle Phase Mapping (LCM → SE)

| LCM Phase | LCM Responsibility | SE Job Phase |
|-----------|-------------------|--------------|
| INSTANTIATING | Trigger SE job, await CloudEvent | `instantiate` |
| READY | Mark session ready (after SE confirms) | — |
| RUNNING | Monitor timeslot, handle extensions | — |
| COLLECTING | Trigger SE job, await CloudEvent | `collect` |
| GRADING | Trigger SE job, store results | `grade` |
| STOPPING | Trigger SE job, await CloudEvent | `teardown` |
| ARCHIVED | Archive artifacts (LCM local) | `archive` |

### 2.13 Migration Strategy

**Phase 1: Foundation** (Current sprint + 1)

- Create `scenario-engine/` service scaffold (FastAPI, Neuroglia, Makefile)
- Implement PodDefinition aggregate + MongoDB persistence
- Implement content sync endpoint (S3 download, extraction, PAv1/ parsing)
- Implement basic job submission API (accept + return job_id)
- CloudEvent publisher skeleton
- Port `lab_resolve` and `lab_start` as first two scenarios

**Phase 2: DSL Runtime**

- Implement DSL executor (task types: call, do, for, set, switch, try)
- Implement jq expression evaluator (via `pyjq` or `jq.py` binding)
- Implement data flow pipeline (input.from → execute → output.as → export.as)
- Job progress tracking + SSE stream endpoint
- Port remaining I/O step handlers as scenarios

**Phase 3: Adapter Abstraction**

- Define `AdapterProtocol` ABC
- Implement `CmlOnAwsAdapter` (extract from current CML SPI clients)
- Stub `RocRadkitAdapter` interface
- Adapter selection from PodDefinition.pod_type

**Phase 4: Advanced Features**

- Per-item grading engine (`for` + `grade_item@v1`)
- Phase report generation
- Evidence collection subsystem
- Restore/retake scenario support
- `fork` task type (parallel execution)
- `listen` task type (convergence callbacks)
- Warm-pool pre-instantiation via SE

**Phase 5: Multi-Adapter**

- Implement ROC/RADkit adapter
- Proxmox adapter
- VMWare adapter
- Adapter capability negotiation

---

## 3. Consequences

### 3.1 Positive

- **Clean service boundary:** LCM owns resource state, SE owns pod automation execution
- **Multi-adapter ready:** SE encapsulates adapter complexity; adding Proxmox/ROC doesn't touch LCM
- **Content-driven:** Lab authors define lifecycle steps via DSL without platform code changes
- **Independent scaling:** SE scales with pod automation load; LCM scales with session volume
- **Fault isolation:** SE crash doesn't kill LCM reconciler; jobs can be retried
- **Reusable:** CI/CD, manual triggers, and future services can submit SE jobs
- **Observable:** CloudEvents + SSE streams give LCM real-time progress without polling
- **Testable:** SE testable against mock adapters; LCM testable against mock SE API
- **DSL-first:** jq expressions and ServerlessWorkflow-inspired syntax enable powerful content authoring

### 3.2 Negative

- **New service deployment:** Additional container, health checks, monitoring
- **Network latency:** Job dispatch crosses service boundary (mitigated by fire-and-forget pattern)
- **Credential management:** SE needs its own CML/AWS credentials (via Kubernetes secrets)
- **Migration cost:** Gradual — lablet-controller step handlers remain functional during transition
- **Shared code coordination:** `lcm_core` changes affect both LCM and SE deployments

### 3.3 Neutral

- Existing seed YAML format remains valid (PipelineTemplateResolver preserved in LCM)
- PAv1/ is additive — RCUv1/ continues to work as-is
- Current lablet-controller tests remain passing throughout migration
- The SE can be developed in parallel with ongoing LCM feature work

---

## 4. Implementation Notes

### 4.1 Shared Package Strategy

```
lcm_core/                             # Shared between LCM services AND SE
├── domain/
│   ├── value_objects/
│   │   ├── pod_type.py               # PodType enum (CML_ON_AWS, ROC_RADKIT, ...)
│   │   ├── pod_definition_ref.py     # PodDefinitionRef value object
│   │   └── content_manifest.py       # Parsed PAv1/manifest.yaml model
│   └── dsl/                          # DSL model (shared between parser + runtime)
│       ├── __init__.py
│       ├── task_types.py             # CallTask, DoTask, ForTask, SetTask, etc.
│       ├── expressions.py            # RuntimeExpression, JqExpression
│       └── lifecycle_definition.py   # PhaseDefinition, TaskDefinition
├── infrastructure/
│   └── content_store/                # S3 pull + zip extraction
│       ├── __init__.py
│       ├── s3_content_client.py      # Download LAB.zip
│       └── content_extractor.py      # Extract + parse PAv1/ artifacts
```

### 4.2 Communication Patterns

```
LCM → SE:  HTTP POST (fire-and-forget job submission)
SE → LCM:  CloudEvents via HTTP POST to callback_url
SE → Any:  SSE stream at /api/v1/jobs/{id}/stream (optional real-time)
```

**CloudEvent Types:**

| Type | When | Data |
|------|------|------|
| `io.lcm.se.job.accepted` | Job queued | `{job_id, phase}` |
| `io.lcm.se.task.started` | Task begins | `{job_id, task_name}` |
| `io.lcm.se.task.completed` | Task succeeds | `{job_id, task_name, output}` |
| `io.lcm.se.task.faulted` | Task fails | `{job_id, task_name, error}` |
| `io.lcm.se.job.completed` | All tasks done | `{job_id, results, report_url}` |
| `io.lcm.se.job.faulted` | Job failed | `{job_id, error, partial_results}` |
| `io.lcm.se.pod-definition.ready` | Content synced | `{definition_id, version, hash}` |

### 4.3 Adapter Protocol

```python
# infrastructure/adapters/base_adapter.py

class AdapterProtocol(Protocol):
    """Infrastructure adapter for pod automation.

    Each adapter encapsulates all interactions with a specific
    infrastructure type (CML-on-AWS, ROC/RADkit, Proxmox, VMWare).
    """

    @property
    def pod_type(self) -> PodType: ...

    # Lab management
    async def list_labs(self) -> list[LabInfo]: ...
    async def import_lab(self, topology: bytes) -> LabInfo: ...
    async def start_lab(self, lab_id: str) -> LabStatus: ...
    async def stop_lab(self, lab_id: str) -> LabStatus: ...
    async def wipe_lab(self, lab_id: str) -> None: ...
    async def delete_lab(self, lab_id: str) -> None: ...
    async def get_lab_status(self, lab_id: str) -> LabStatus: ...

    # Node operations
    async def execute_command(self, lab_id: str, node: str, cmd: str) -> CommandResult: ...
    async def transfer_file(self, lab_id: str, node: str, src: str, dst: str) -> None: ...

    # Telemetry
    async def get_system_stats(self) -> SystemStats: ...
    async def get_node_telemetry(self, lab_id: str, node: str) -> NodeTelemetry: ...
```

### 4.4 Testing Strategy

| Layer | Approach |
|-------|----------|
| Scenarios | Unit test each `@scenario` with mock adapter |
| DSL Runtime | Integration test executor with sample lifecycle.yaml |
| Adapters | Contract tests against recorded responses (VCR pattern) |
| API | FastAPI TestClient, mock command/query handlers |
| Content Sync | Integration test with local S3 (MinIO) |
| End-to-End | LCM submits job → SE executes → CloudEvent received |

### 4.5 Backward Compatibility During Migration

1. **lablet-controller keeps existing step_handlers** — they continue to work for
   definitions without PAv1/ content
2. **Dual execution path** — lablet-controller checks if SE is available + definition
   has PAv1/ → delegates to SE; otherwise → executes locally via PipelineExecutor
3. **Feature flag** — `SE_ENABLED=true` enables SE delegation; false = local execution
4. **Gradual rollover** — individual definitions can opt-in to SE by including PAv1/

### 4.6 Deployment

```yaml
# docker-compose addition
scenario-engine:
  build:
    context: ./src/scenario-engine
  environment:
    - MONGODB_URI=mongodb://mongo:27017/scenario_engine
    - S3_ENDPOINT=http://minio:9000
    - S3_BUCKET=content
    - CLOUD_EVENT_SINK=http://lablet-controller:8002/api/cloudevents
  depends_on:
    - mongo
    - minio
  ports:
    - "8004:8000"
```

---

## 5. References

- ADR-034: Pipeline Executor (DAG execution, progress persistence)
- ADR-038: Step Handler Registry (decorator-based registration, reconciler decomposition)
- AD-STEP-001: One step per file convention
- AD-SE-01: PodDefinition entity with lifecycle persistence
- AD-SE-02: DSL expression language is jq
- AD-SE-03: Step handler split — state transitions in LCM, I/O automation in SE
- AD-SE-04: Adapter selection — dual requirement (definition declares + worker matches)
- AD-044: LabletSession lifecycle state machine
- [ServerlessWorkflow DSL Specification](https://github.com/serverlessworkflow/specification/blob/main/dsl.md)

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| **ScenarioEngine (SE)** | Separate microservice that executes pod automation jobs |
| **PodDefinition** | SE-owned entity representing synced content with lifecycle |
| **Scenario** | A registered Python function that performs a specific automation task |
| **Adapter** | Infrastructure-specific implementation of pod operations |
| **PodType** | Enum declaring infrastructure requirement (CML_ON_AWS, ROC_RADKIT, etc.) |
| **Job** | A single execution of a lifecycle phase by the SE |
| **DSL** | The proprietary workflow definition language (ServerlessWorkflow-inspired) |
| **PAv1/** | POD Automation v1 — content folder containing lifecycle definitions |

## Appendix B: Decision Log

| Code | Decision | Date |
|------|----------|------|
| AD-SE-01 | SE persists PodDefinition; registry is in-memory | 2026-06-05 |
| AD-SE-02 | Expression language = jq | 2026-06-05 |
| AD-SE-03 | Option C: state in LCM, I/O in SE, shared LAB.zip handling | 2026-06-05 |
| AD-SE-04 | Dual adapter selection (content declares + worker matches) | 2026-06-05 |
