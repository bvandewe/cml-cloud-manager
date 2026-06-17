# Pod Artifact Format — `PAv1`

> **Status**: Draft (Phase 0 of CPA↔SE Integration)
> **DSL authority**: [ADR-057 — Content-Driven Lifecycle DSL](../adr/ADR-057-content-driven-lifecycle-dsl.md), [ADR-058 — Data-Flow & Variable Scopes](../adr/ADR-058-lifecycle-data-flow-and-variable-scopes.md)
> **Engine authority**: [ADR-044 — Content-Driven Lifecycle Engine](../adr/ADR-044-content-driven-lifecycle-engine.md)
> **DSL reference**: [DSL-SPECIFICATION.md](../dsl/DSL-SPECIFICATION.md)
> **Living plan**: [cpa-se-integration-plan.md](../../implementation/cpa-se-integration-plan.md) §5
> **JSON schemas**: [`schemas/`](./schemas/)

---

## 1. Purpose

`PAv1` (Pod Artifact format, version 1) is the canonical zip-packaged content layout
consumed by the Scenario Engine (SE) and projected into CPA via `PodDefinition`.

A `PAv1/` archive is the **only contract** between content authoring (Mosaic) and the
runtime engines. Everything the engines need to instantiate, monitor, grade, report
on, and tear down a lab session lives inside the archive.

Authority decisions:

- **AD-CSI-001** — DSL is **not** shared between CPA and SE. The shared contract is the
  content format (this document), not the execution model. CPA runs **native steps**
  (handler pipelines); SE runs **JobDefinitions** (the step DAG of ADR-057).
- **AD-CSI-002** — Pod-type discovery is deterministic and prioritised (see §3).
- **AD-CSI-004** — `PodDefinition` carries first-class typed fields extracted from the
  PAv1 tree (not just an opaque `manifest` blob).

The **job-body DSL** — the unit-of-work vocabulary SE runs — is governed by
[ADR-057](../adr/ADR-057-content-driven-lifecycle-dsl.md) (closed `scenarioFunction`
primitives + flat step DAG) and [ADR-058](../adr/ADR-058-lifecycle-data-flow-and-variable-scopes.md)
(the four data-flow scopes). The full grammar is specified in
[DSL-SPECIFICATION.md](../dsl/DSL-SPECIFICATION.md).

---

## 2. Canonical zip layout

A `PAv1` archive is any zip file containing a top-level `PAv1/` directory
(canonical shape per [ADR-057 §2.6](../adr/ADR-057-content-driven-lifecycle-dsl.md)):

```text
<package>.zip
└── PAv1/
    ├── manifest.yaml              # REQUIRED — version, pod_type, content_id, etc.
    ├── topology/                  # REQUIRED for engines that build infra
    │   ├── cml.yaml               # CML topology — XOR with radkit/proxmox/vmware
    │   ├── radkit.yaml            # OR a RADkit topology
    │   ├── proxmox.yaml           # OR a Proxmox topology
    │   ├── vmware.yaml            # OR a VMware topology
    │   ├── devices.json           # OPTIONAL — device → connection map
    │   └── ports.json             # OPTIONAL — per-device serial/vnc/pat ports
    ├── lifecycle.yaml             # OPTIONAL — phases -> { native_steps_by_pod_type, jobs[] }
    ├── connectors.yaml            # OPTIONAL — connector model (runtime_env binding)
    ├── jobs/                      # OPTIONAL — JobDefinitions (the step DAGs, §4.4)
    │   ├── post_init.yaml
    │   └── grade.yaml
    ├── composites/                # OPTIONAL, DEFERRED — CompositeScenarios (ADR-057 §2.8)
    │   └── check_interface_up_up.yaml
    ├── grading/                   # OPTIONAL — EvaluationRuleset (graded items)
    │   └── rubric.yaml
    ├── reports/                   # OPTIONAL — ProcessReportSpec (report shape)
    │   └── score_report.yaml
    ├── files/                     # OPTIONAL — payloads pushed by copy@v1
    │   └── desktop_package.tgz
    └── restore/                   # OPTIONAL — snapshot/restore directives
        └── restore.yaml
```

Legacy artifacts (e.g. `mosaic_meta.json`, root-level `cml.yml`, `grade.xml`,
`content.xml`) MAY co-exist outside the `PAv1/` tree during the migration window.
When both a legacy file and its `PAv1/` equivalent are present, the `PAv1/` copy
wins.

---

## 3. Pod-type discovery (AD-CSI-002)

`PodTypeDetector.detect(package: Path | ZipFile) -> tuple[PodType, list[str]]`
walks this priority chain; the first matching signal wins. The signal list returned
alongside the chosen type is for audit logging.

| Priority | Signal                                                                  | Resolves to        |
|---------:|-------------------------------------------------------------------------|--------------------|
| 1        | `PAv1/manifest.yaml: { pod_type: <value> }` (explicit)                  | `PodType(value)`   |
| 2        | `PAv1/topology/radkit.yaml` exists                                      | `ROC_RADKIT`       |
| 3        | `PAv1/topology/proxmox.yaml` exists                                     | `PROXMOX`          |
| 4        | `PAv1/topology/vmware.yaml` exists                                      | `VMWARE`           |
| 5        | `PAv1/topology/cml.yaml` (or `.yml`) exists                             | `CML_ON_AWS`       |
| 6        | Root-level `cml.yaml` / `cml.yml` exists (legacy)                       | `CML_ON_AWS`       |
| 7        | Root-level `radkit.yaml` exists (legacy)                                | `ROC_RADKIT`       |
| —        | None of the above                                                       | raises `PodTypeIndeterminate(signals=[...])` |

Authors **SHOULD** declare `pod_type` in `manifest.yaml`. Detection from topology
files is a defensive fallback.

---

## 4. File specifications

### 4.1 `manifest.yaml` — required

The manifest is the only required file in a `PAv1` archive. It declares the
**format version** and the high-level identity of the pod.

JSON Schema: [`schemas/manifest.schema.json`](./schemas/manifest.schema.json)

Required fields:

- `format_version` — MUST be the string `"PAv1"`.
- `name` — Content package name (slug-like). Example: `exam-ccnp-v1-lab-1.1`.
- `version` — Semantic version string. Example: `1.0.0`.
- `content_id` — Stable identifier for this content lineage. Typically the slugified
  form-qualified-name.

Optional fields:

- `pod_type` — One of `cml_on_aws`, `roc_radkit`, `proxmox`, `vmware`. **Strongly
  recommended.** If absent, `PodTypeDetector` falls back to topology signals.
- `description` — Free-text description.
- `authors` — List of `{ name, email? }` records.
- `jobs_used` — List of `name@version` JobDefinition references used by `lifecycle.yaml`.
  Informational; not enforced by the validator.
- `lifecycle_ref` — Relative path to `lifecycle.yaml` (default: `lifecycle.yaml`).

Minimal example:

```yaml
format_version: PAv1
name: exam-ccnp-v1-lab-1.1
version: 1.0.0
content_id: exam-ccnp-v1-lab-1.1
pod_type: cml_on_aws
description: CCNP exam lab — module 1.1
```

### 4.2 `topology/<engine>.yaml` — at least one required for instantiation

Topology files are passed verbatim to the matching adapter. The schema is owned
by the adapter (`cml.yaml` → CML JSON Schema, etc.), not by `PAv1` itself.
`PodTypeDetector` only looks at file presence, not contents.

`topology/devices.json` is an optional device → connection map (telnet/ssh/console
endpoints, credentials handle) used by adapters that need per-device addressing.
`topology/ports.json` supplies the per-device serial/vnc/pat ports that populate
`runtime_env.devices.*` (ADR-058 §2.2) at job submission.

### 4.3 `lifecycle.yaml` — optional

Declares the **phase ordering** and, per phase, the **native steps** (CPA seam) and
**jobs** (SE step DAGs). The canonical shape is
[ADR-057 §2.6](../adr/ADR-057-content-driven-lifecycle-dsl.md): a `kind: Lifecycle`
document whose `spec.phases[]` each carry `native_steps_by_pod_type` and `jobs[]`.
**The step DAG never lives inline** — every job references a `JobDefinition` file by
`definition: <name>@<version>`.

**Optional file.** When absent, the lablet-controller's `PipelineTemplateResolver`
falls through to the DB-stored `LabletDefinition.pipelines` and finally to the
hardcoded baseline templates — so legacy packages continue to work unchanged
(AD-CSI-022 / AD-CSI-023).

JSON Schema: [`schemas/lifecycle.schema.json`](./schemas/lifecycle.schema.json).

```yaml
apiVersion: pav1
kind: Lifecycle
metadata:
  lablet: exam-ccnp-v1-lab-1.1
spec:
  phases:
    - name: instantiate
      # native LCM steps (resolved to handlers by the controller's template chain)
      native_steps_by_pod_type:
        cml_on_aws: [worker_lab_resolve, pod_locator, ports_alloc, lds_register]
      jobs:
        - definition: cml.lab_start@v1        # resolve + start the CML lab

    - name: post_init
      jobs:
        - definition: post_init@v1            # -> jobs/post_init.yaml
          process_type: Initialization

    - name: grade
      jobs:
        - definition: grade@v1                # -> jobs/grade.yaml
          process_type: Grading
          rubric: rubric                      # -> grading/rubric.yaml   (evaluate stage)
          report: score_report                # -> reports/score_report.yaml

    - name: teardown
      native_steps_by_pod_type:
        cml_on_aws: [archive]
      jobs:
        - definition: cml.wipe@v1
          process_type: Archive
```

**Phase fields:**

| Field                     | Type              | Required | Notes                                                                 |
|---------------------------|-------------------|---------:|-----------------------------------------------------------------------|
| `name`                    | string            | yes      | Phase identity (e.g. `instantiate`, `post_init`, `grade`, `teardown`).|
| `native_steps_by_pod_type`| object            | no       | `{ <pod_type>: [<native step name>, …] }` — CPA-native steps.          |
| `jobs`                    | list[JobRef]      | no       | SE JobDefinitions executed in this phase.                              |

**JobRef fields:**

| Field          | Type   | Required | Notes                                                            |
|----------------|--------|---------:|------------------------------------------------------------------|
| `definition`   | string | yes      | `<name>@<version>` → `jobs/<name>.yaml`.                          |
| `process_type` | string | no       | `Initialization` / `Grading` / `Change` / `Submission` / `Archive` (selects the terminal `report.*` primitive — ADR-057 §2.5). |
| `rubric`       | string | no       | Name under `grading/` supplying the evaluate stage's `items[]`.   |
| `report`       | string | no       | Name under `reports/` supplying the report shape.                 |

**Single-part vs multi-part.** A single-part lablet uses the top level directly. A
multi-part session repeats the per-part subtree under `parts/`, applying the same
`jobs[]` per part via `part_workflow` (ADR-057 §2.6). Both are the same shape at two
scopes.

**Native-step resolution.** `native_steps_by_pod_type` lists native step **names**
only; the lablet-controller's `PipelineTemplateResolver` (AD-CSI-022) resolves each
name to its handler DAG (timeouts, `needs`, retries) from its templates. Content
declares _which_ native steps run and _in what phase_ — not their internal wiring.

### 4.4 `jobs/<name>.yaml` — optional (JobDefinition)

A `JobDefinition` is a **flat, ordered DAG of steps** that composes closed
`scenarioFunction` primitives (ADR-057 §2.4). Authors write **only declarative
wiring** — never imperative code, never a new primitive.

JSON Schema: [`schemas/job-definition.schema.json`](./schemas/job-definition.schema.json)

**Envelope + step shape:**

```yaml
apiVersion: pav1
kind: JobDefinition
metadata:
  name: post_init
  version: v1
spec:
  process_type: Initialization
  steps:
    - id: <unique-in-job>             # required — stable id; also the capture namespace
      uses: <scenarioFunction>@<ver>  # required — closed primitive (or composite:<name>@<ver>)
      target: <connector-name>        # optional — omitted for pause/report/cml.* (implicit)
      with: { <input>: <value|expr> } # inputs; values may be ${ jq } over the scopes
      capture: { <var>: <output-ref> }# write named outputs into vars.* (ADR-058)
      when: "${ <jq-bool-expr> }"     # optional gating; step skipped if false
      on_error: { action: fail|continue|retry, retries?: <n>, backoff?: <s> }
      timeout: <seconds>              # optional per-step timeout
      stage: setup|collect|evaluate|report   # optional soft grouping (default: setup)
```

The closed primitive set (`pause` / `exec` / `copy` / `cml.*` / `collect` /
`evaluate.regex` / `report.*`), the four data-flow scopes, and the legacy→scoped
reference mapping are specified in [DSL-SPECIFICATION.md](../dsl/DSL-SPECIFICATION.md)
§§6–7. The gate pattern (legacy `tVerify set=…` / `if=…`) becomes `capture:` on an
`evaluate.regex@v1` step feeding a downstream `when:`.

**Example — the gate pattern** (from `jobs/post_init.yaml`):

```yaml
- id: list_tmp
  uses: exec@v1
  target: workstation_22
  with: { command: "ls -la /home/cisco/Desktop/tmp/" }
  capture: { stdout: files, ok: cmd1_ok }

- id: verify_package              # was tVerify (set="file.OK", if="CMD1.OK")
  uses: evaluate.regex@v1
  when: "${ vars.cmd1_ok }"
  with:
    source: "${ vars.files }"
    regex: "desktop_package\\.tgz"
    mode: positive
  capture: { passed: file_ok }    # was set="file.OK"

- id: unpack                      # was tExecute (if="file.OK")
  uses: exec@v1
  target: workstation_22
  when: "${ vars.file_ok }"       # gated on the verify above
  with: { command: "tar -C /home/cisco/Desktop/tasks/ -xzf …/desktop_package.tgz" }
```

> **Open Q-04** (see plan §8): when both a content-defined JobDefinition `post_init@v1`
> and a Python `@scenario` of the same `name@version` exist, the content-defined one
> wins with a warning log. (Note: scenarioFunctions are _primitives_, JobDefinitions
> are _content_; collisions are expected only across content sources.)

### 4.4b `connectors.yaml` — optional (ConnectorModel)

The connector model (ADR-057 §2.3) declares the **named connectors** a step selects
with `target:`. Prompts, ports, and credentials are **resolved from `runtime_env.*`**
(ADR-058) — the file declares the _shape_, the runtime supplies the _facts_. No port
or password is ever literal in content.

JSON Schema: [`schemas/connector-model.schema.json`](./schemas/connector-model.schema.json)

```yaml
apiVersion: pav1
kind: ConnectorModel
metadata:
  name: exam-ccnp-v1-lab-1.1
spec:
  connectors:
    - name: rtr01
      class: cisco_common
      transport: telnet
      prompt: "${ runtime_env.devices.rtr01.prompt }"
      enable_password: "${ runtime_env.devices.rtr01.enable_password }"
      port: "${ runtime_env.devices.rtr01.serial_port }"
    - name: workstation_22
      class: unix
      transport: ssh
      via_port: "${ runtime_env.devices.workstation.pat_port }"   # 5052 -> 22
      username: "${ runtime_env.devices.workstation.username }"
      password: "${ runtime_env.devices.workstation.password }"
    - name: control_node
      class: control                 # used only by cml.* primitives
      transport: telnet
      port: "${ runtime_env.control_node.serial_port }"
```

`cml.*` primitives implicitly target the `control` connector — the author never
targets it by hand.

### 4.5 `grading/rubric.yaml`, `reports/*.yaml`, `restore/restore.yaml` — optional

- **`grading/rubric.yaml`** (`EvaluationRuleset`) — the graded items, their checks, and
  points. **Referenced by** a job's `evaluate` step (it supplies the `items[]` the
  `evaluate.regex@v1` / report assembly consumes).
  Schema: [`schemas/evaluation-ruleset.schema.json`](./schemas/evaluation-ruleset.schema.json)
- **`reports/*.yaml`** (`ProcessReportSpec`) — the report shape/class. **Referenced by**
  the job's terminal `report.*` step (selected by `process_type`, ADR-057 §2.5).
  Schema: [`schemas/process-report-spec.schema.json`](./schemas/process-report-spec.schema.json)
- **`restore/restore.yaml`** — snapshot/restore directives. Preserved verbatim on
  `PodDefinition.restore_rules` until the consuming primitives land.

### 4.6 `composites/<name>.yaml` — optional, DEFERRED

`CompositeScenario` (ADR-057 §2.8) is a **deferred, opt-in** content-defined,
parameterised group of _closed primitives only_, invoked via
`uses: composite:<name>@<ver>`. It runs in an isolated `vars.*` frame (ADR-058 §2.5).
**Not implemented in PAv1 v1** — documented here for forward reference only.

---

## 5. Validation

Validation runs at **content sync** (ADR-023): both CPA and SE load the schema set
published from `lcm_core`. A step's `with:` is validated against the referenced
scenarioFunction's `input_schema`, and its `capture:` keys against the `output_schema`,
from `scenario-functions.catalog.json`. An invalid package **fails the sync** (no
partial ingestion).

| Schema file | Validates |
|---|---|
| `manifest.schema.json` | `PAv1/manifest.yaml` |
| `lifecycle.schema.json` | `PAv1/lifecycle.yaml` (phases, native steps, job refs) |
| `job-definition.schema.json` | `PAv1/jobs/*.yaml` (the step DAG) |
| `connector-model.schema.json` | `PAv1/connectors.yaml` |
| `evaluation-ruleset.schema.json` | `PAv1/grading/rubric.yaml` |
| `process-report-spec.schema.json` | `PAv1/reports/*.yaml` |
| `scenario-functions.catalog.json` | **generated** from the SE `@scenario` registry — each primitive's I/O schema |

`lcm_core.infrastructure.content_store.PAv1Validator` exposes per-artifact entry points
(`validate_manifest`, `validate_lifecycle`, `validate_job_definition`, …), each raising
`PAv1ValidationError(path, errors)` on failure.

Schemas are **vendored** under `src/core/lcm_core/` so the runtime has no dependency on
the documentation tree. The copies in `docs/architecture/content-format/schemas/` are
illustrative; keep both in sync when amending.

> **Schema migration pending.** The schema set above reflects the ADR-057 §2.7 target.
> The currently-vendored `lifecycle.schema.json` / `scenario.schema.json` still describe
> the superseded `name`/`handler` and `do`/`call` shapes; aligning them is tracked as a
> follow-up (schemas-later).

---

## 6. Versioning

`format_version: PAv1` is a closed enum; any future breaking change ships as
`PAv2` with its own schema set. The validator refuses unknown `format_version`
values with an explicit diagnostic.

Non-breaking additions (new optional fields, additional `scenarioFunction` primitives)
MAY land in `PAv1` without a version bump; track them in the changelog at the top of
each `*.schema.json` file. Adding a primitive is a code PR + version bump in the SE
registry (ADR-057 §2.2), surfaced to content via `scenario-functions.catalog.json`.

---

## 7. Cross-references

- [ADR-057](../adr/ADR-057-content-driven-lifecycle-dsl.md) — Content-Driven Lifecycle DSL (primitives, step DAG)
- [ADR-058](../adr/ADR-058-lifecycle-data-flow-and-variable-scopes.md) — Data-Flow & Variable Scopes
- [ADR-044](../adr/ADR-044-content-driven-lifecycle-engine.md) — Content-Driven Lifecycle Engine (engine origin)
- [DSL-SPECIFICATION.md](../dsl/DSL-SPECIFICATION.md) — the full job-body DSL grammar
- [CPA↔SE Integration Plan](../../implementation/cpa-se-integration-plan.md) — §5 PAv1/ spec, §6 phased delivery
- [`schemas/manifest.schema.json`](./schemas/manifest.schema.json)
- [`schemas/lifecycle.schema.json`](./schemas/lifecycle.schema.json)
- [`schemas/job-definition.schema.json`](./schemas/job-definition.schema.json)
