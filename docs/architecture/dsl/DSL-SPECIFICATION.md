# LCM Pod Automation DSL — Specification v2.0.0

| Attribute | Value |
|-----------|-------|
| **Version** | 2.0.0-draft |
| **Date** | 2026-06-16 |
| **Status** | Draft |
| **Expression Language** | jq (strict mode) |
| **Authority** | [ADR-057 — Content-Driven Lifecycle DSL](../adr/ADR-057-content-driven-lifecycle-dsl.md), [ADR-058 — Data-Flow & Variable Scopes](../adr/ADR-058-lifecycle-data-flow-and-variable-scopes.md) |
| **Related** | [ADR-044](../adr/ADR-044-content-driven-lifecycle-engine.md), [ADR-049](../adr/ADR-049-unified-workflow-dsl.md), [content-format/PAv1.md](../content-format/PAv1.md) |
| **Supersedes** | the ServerlessWorkflow `do`/`call` task model of this spec's v1 (and of ADR-044 §2.8) |

---

## 1. Abstract

This document defines the **LCM Pod Automation DSL** — the declarative language content authors
(and LLMs) use to define pod lifecycle automation for the ScenarioEngine (SE).

The DSL has **two layers** (ADR-057 §2.1):

- **Code layer (trusted).** A closed, versioned set of **`scenarioFunction`** primitives, defined
  as `@scenario(name, version)` classes in `scenario-engine/scenarios/`. Authors never write these.
- **Content layer (sandboxed).** **`JobDefinition`** artifacts (`PAv1/jobs/<name>.yaml`) — each a
  **flat, ordered DAG of steps** that _composes_ scenarioFunctions. Authors write **only declarative
  wiring**; they never add a primitive, never write imperative code.

A job body is therefore **a list of `scenarioFunction` calls**, not a free task language and not a
fixed template. This v2 spec **replaces** the earlier ServerlessWorkflow-inspired model
(`document` / `phases.<name>.do[]` / `call` / `set` / `fork` / `switch` / `try`) with the single
ADR-057 step shape.

---

## 2. Design Principles

1. **Closed vocabulary** — steps `uses:` a primitive from a fixed, orthogonal set (§6). Small enough
   for an LLM to hold in context; adding a verb is a code PR + version bump, never a content change.
2. **Flat ordered DAG** — a `JobDefinition` is a flat `steps[]` list executed in document order.
   No nesting, no `goto`, no inline sub-workflows. Gating is per-step via `when:`.
3. **Scoped data-flow** — every value lives in one of four namespaced scopes (ADR-058): `session.*`,
   `content.*`, `runtime_env.*` (read-only) and `vars.*` (read/write). No secret or port is ever
   literal in content.
4. **Hard sandbox** — authored content is _pure wiring_ over trusted code. Only the code layer
   executes logic.
5. **jq expressions** — all dynamic values use jq in `${ }` (strict mode).
6. **Content-portable** — steps reference primitives by `name@version` and facts by scope, never by
   implementation or baked-in literal.
7. **Sync-time validatable** — every artifact is JSON-Schema-validated at content sync (§12); an
   invalid package fails the sync. This is the precondition for reliable LLM generation.

---

## 3. Artifacts & Envelopes

The DSL spans two content artifacts. Both use the standard PAv1 envelope
(`apiVersion` / `kind` / `metadata` / `spec`).

### 3.1 `JobDefinition` — the step DAG (`PAv1/jobs/<name>.yaml`)

```yaml
apiVersion: pav1
kind: JobDefinition
metadata:
  name: post_init
  version: v1
spec:
  process_type: Initialization   # intent → selects the terminal report.* primitive (§9)
  steps:
    - id: settle
      uses: pause@v1
      with: { seconds: 30 }
    # ... more steps ...
```

### 3.2 `Lifecycle` — phase orchestration (`PAv1/lifecycle.yaml`)

Orchestration only: CPA owns the phase **order**; SE owns each job **body** (in `jobs/`). Every job
references a `JobDefinition` by `definition: <name>@<version>`. The step DAG never lives inline.

```yaml
apiVersion: pav1
kind: Lifecycle
metadata:
  lablet: LAB-0.1
spec:
  phases:
    - name: instantiate
      native_steps_by_pod_type:
        cml_on_aws: [worker_lab_resolve, pod_locator, ports_alloc, lds_register]
      jobs:
        - definition: cml.lab_start@v1

    - name: post_init
      jobs:
        - definition: post_init@v1        # -> jobs/post_init.yaml
          process_type: Initialization

    - name: grade
      jobs:
        - definition: grade@v1            # -> jobs/grade.yaml
          process_type: Grading
          rubric: rubric                  # -> grading/rubric.yaml  (evaluate stage)
          report: score_report            # -> reports/score_report.yaml
```

`phases[].native_steps_by_pod_type` are LCM-native steps (the CPA seam); `phases[].jobs[]` are SE
JobDefinitions. See [PAv1.md](../content-format/PAv1.md) for the full archive layout.

---

## 4. Expression Language & Scopes

### 4.1 jq in `${ }` (strict mode)

All runtime expressions use [jq](https://jqlang.github.io/jq/) enclosed in `${ }`. In **strict
mode** (the only mode), bare strings are literal values — only `${ }`-delimited strings are
evaluated.

```yaml
with:
  command: "show ip interface brief"            # literal
  serial_port: "${ runtime_env.devices.rtr01.serial_port }"   # jq over a scope
when: "${ vars.file_ok }"                        # jq boolean gate
```

### 4.2 The four scopes (ADR-058 §2.1)

Expressions evaluate against a single merged object whose top-level keys are the scope names:
`{ session, content, runtime_env, vars }`.

| Scope | Writable by content? | Source | Holds |
|---|---|---|---|
| `session.*` | No (read-only) | `mosaic_meta.json` + `Session` | candidate / exam / timeslot metadata |
| `content.*` | No (read-only) | the synced PAv1 package | lab-root path, packaged file handles, form FQN |
| `runtime_env.*` | No (read-only) | `PodInstance` + `Host` + secret store | device ports, prompts, credentials, `cml_password`, worker IP |
| `vars.*` | **Yes** | `step.capture` | task-captured intermediate values |

`session.*`, `content.*`, and `runtime_env.*` are **resolved at job submission and frozen** — the
trusted, validated inputs content reads but cannot forge. Only `vars.*` is writable, and only via
`capture:`. See [ADR-058 §2.2](../adr/ADR-058-lifecycle-data-flow-and-variable-scopes.md) for the
full declared namespace the validator checks expressions against.

> **No `$context` blob.** Unlike the v1 model, there is no single mutable workflow context threaded
> through `output`/`export`. State is the **scoped `vars.*`**, written by `capture:` and namespaced
> by step id.

---

## 5. The Step Shape

A `JobDefinition.spec.steps[]` entry is the **single, canonical step shape** (ADR-057 §2.4):

```yaml
- id: <unique-in-job>             # required — stable id; also the capture namespace
  uses: <scenarioFunction>@<ver>  # required — must exist in the SE registry (or a composite, §11)
  target: <connector-name>        # optional — omitted for pause/report/cml.* (implicit)
  with: { <input>: <value|expr> } # inputs; values may be ${ jq } over the scopes
  capture: { <var>: <output-ref> }# write named outputs into vars.* (§7)
  when: "${ <jq-bool-expr> }"     # optional gating; step is skipped if false
  on_error: { action: fail|continue|retry, retries?: <n>, backoff?: <s> }
  timeout: <seconds>              # optional per-step timeout
  stage: setup|collect|evaluate|report   # optional grouping (default: setup)
```

| Field | Required | Description |
|---|---|---|
| `id` | ✅ | Unique within the job. Stable identity and the `vars.<id>.*` capture namespace. |
| `uses` | ✅ | `scenarioFunction@version` (§6) or `composite:<name>@<ver>` (§11). |
| `target` | ❌ | Named connector (§8). Omitted for `pause`/`report.*`/`cml.*` (implicit). |
| `with` | ❌ | Inputs to the primitive. Values may be literals or `${ jq }`. |
| `capture` | ❌ | Maps primitive outputs into `vars.*` (§7). |
| `when` | ❌ | jq boolean. The step is skipped when it evaluates falsey. |
| `on_error` | ❌ | Failure policy (§10). |
| `timeout` | ❌ | Per-step timeout in seconds. |
| `stage` | ❌ | **Soft grouping** for report assembly (`setup`/`collect`/`evaluate`/`report`), not a control structure. Default `setup`. |

**Execution model.** SE executes steps **in document order**, honouring `when` and `on_error`. A
step may read any `vars.*` captured by an **earlier** step (sequential data-flow). There is no
nesting, no parallelism (deferred), and no flow jumps — the DAG is linear.

`stage` documents the Collect → Evaluate → Report intent and labels steps for report assembly; it is
enforced _softly_ by the schema (a `Grading` job SHOULD order `collect` → `evaluate.*` →
`report.score`), never as a rigid template.

---

## 6. The Closed `scenarioFunction` Catalog

The vocabulary is **closed and orthogonal** (ADR-057 §2.2). Each primitive declares an
`input_schema` / `output_schema`, published to `scenario-functions.catalog.json` from the SE
registry (§12). A step's `with:` is validated against `input_schema`, its `capture:` keys against
`output_schema`.

| `uses:` | Stage | Purpose | Key `with:` inputs | `capture:` outputs | Legacy origin |
|---|---|---|---|---|---|
| `pause@v1` | setup | Wait/settle | `seconds` | — | `tPause` |
| `exec@v1` | setup | Run command/script on a connector, capture output, gate | `command` \| `script`, `suppress_error?` | `stdout`, `ok`, `error` | `tExecute`, `tExecuteBatch` |
| `copy@v1` | setup | Push a content file to the POD host | `source` (content ref), `dest`, `via_port?` | `ok` | `tScp` |
| `cml.bounce_interface@v1` | setup | Bounce an interface via the control node | `device`, `interface`, `serial_port` | `ok` | `bounce_interface` |
| `cml.wipe@v1` | setup | Wipe devices via the control node | `devices[]` | `ok` | `cmlctl --action wipe` |
| `cml.power@v1` | setup | Start/stop a node or ext-conn | `node`, `action` (`start`\|`stop`) | `ok` | `cmlctl --action stop` |
| `cml.lab_resolve@v1` | setup | Resolve/import the lab topology | `definition_id` | `lab_id`, `title`, `nodes` | (native) |
| `cml.lab_start@v1` | setup | Start the lab and poll to convergence | `lab_id` | `lab_state`, `poll_count` | (native) |
| `cml.lab_stop@v1` | setup | Stop the lab | `lab_id` | `ok` | (native) |
| `collect@v1` | collect | Run a `show` command on a device, capture output | `command`, `match?` | `output` | `verify subject='commandOutput'` |
| `evaluate.regex@v1` | evaluate | Regex-check a captured var → pass/fail + issue | `source`, `regex`, `mode` (`positive`\|`negative`), `flags[]?`, `issue?` | `passed`, `issue?` | `verify subject='parse'`, `tVerify` |
| `report.score@v1` | report | Assemble a ScoreReport from graded items | `items[]`, `report_class?` | `report_ref` | `reportClass='LabletReport'` |
| `report.readiness@v1` | report | Assemble a ReadinessReport | `checks[]` | `report_ref` | (Initialization) |

Notes:

- **`evaluate.regex@v1` is the single check primitive**, serving two roles: a **gate** in a `setup`
  stage (its captured `passed` flag drives a later `when:`) and a **graded check** in an `evaluate`
  stage (it feeds `report.score`). This absorbs the legacy `tVerify … set='file.OK'` → `if='file.OK'`
  pattern.
- **Control-node operations are first-class `cml.*` primitives**, not raw shell on a magic device.
  SE owns the mechanics and the `cml_password` (resolved from `runtime_env.*`).
- **Candidate-solution execution** (`py_deploy.py`, `run-playbook.sh`) is just `exec@v1` with a
  `script` on a serial connector — no special primitive.

---

## 7. Data Flow & Capture

There is **no mutable context blob**. State flows through the scoped `vars.*` namespace:

- **Capture.** `capture: { <name>: <output-key> }` writes the named scenarioFunction output into
  `vars.<step_id>.<name>` (namespaced by step id to prevent collisions), and also as a flat
  `vars.<name>` alias when unambiguous.

  ```yaml
  - id: list_tmp
    uses: exec@v1
    target: workstation_22
    with: { command: "ls -la /home/cisco/Desktop/tmp/" }
    capture: { stdout: files, ok: cmd1_ok }   # -> vars.list_tmp.files / vars.files, vars.list_tmp.ok / vars.cmd1_ok
  ```

- **Read.** Any later step's `with`, `when`, or connector field may reference an earlier capture:
  `"${ vars.files }"`.

- **Gate.** `when: "${ vars.file_ok }"` skips the step when false — the direct replacement for the
  legacy `if='file.OK'` after a `tVerify … set='file.OK'`.

### 7.1 Legacy → scoped reference mapping (ADR-058 §2.4)

| Legacy reference | Scoped reference |
|---|---|
| `${config.core.paths.lab_root}/desktop_package.tgz` | `${ content.files.desktop_package }` |
| `port="5052"` (tScp PAT) | `${ runtime_env.devices.workstation.pat_port }` |
| `--serial-port 5048` | `${ runtime_env.devices.sw01.serial_port }` |
| `--cml-password trackNMC50` | `${ runtime_env.cml_password }` |
| `prompt='rtr01#'` | `${ runtime_env.devices.rtr01.prompt }` |
| `enablepassword='cisco'` | `${ runtime_env.devices.rtr01.enable_password }` |
| `string="{files}"` | `${ vars.files }` |
| `string='$(rtr01.show_int_loop0)'` | `${ vars.rtr01.show_int_loop0 }` |
| `set="file.OK"` / `if="file.OK"` | `capture: { passed: file_ok }` / `when: "${ vars.file_ok }"` |

---

## 8. Connectors & Targets

`pod.xml`'s `unit-template`/`connector` becomes a declarative `PAv1/connectors.yaml`
(ADR-057 §2.3). Each entry is a **named connector** a step selects with `target:`. Prompts,
timeouts, transports, serial/PAT ports, and credentials are **resolved from `runtime_env.*`** — the
file declares the _shape_, the runtime supplies the _facts_.

```yaml
apiVersion: pav1
kind: ConnectorModel
metadata:
  name: LAB-1.1.1
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
      class: control                # used only by cml.* primitives
      transport: telnet
      port: "${ runtime_env.control_node.serial_port }"
```

`cml.*` primitives implicitly target the `control` connector — the author never targets it by hand.

---

## 9. `process_type` ↔ Report

`process_type` is the job's **intent**; it selects the terminal `report.*` primitive and the report
class (ADR-057 §2.5).

| `process_type` | Typical stages | Terminal primitive | Report |
|---|---|---|---|
| `Initialization` | setup → collect → evaluate | `report.readiness@v1` | ReadinessReport |
| `Grading` | setup → collect → evaluate | `report.score@v1` | ScoreReport |
| `Change` | setup → collect → evaluate | `report.change@v1` | ChangeReport |
| `Submission` | setup → collect | `report.submission@v1` | SubmissionReport |
| `Archive` | setup | — | ArchiveReport |

**Legacy phase → new phase + `process_type`:**

| Legacy RCUv1 phase | New `lifecycle.yaml` phase | JobDefinition | `process_type` |
|---|---|---|---|
| `init` (implicit) | `instantiate` | native steps + `cml.lab_resolve`/`cml.lab_start` | `Initialization` |
| `post_init` (`sb_post_init.xml`) | `post_init` | `jobs/post_init.yaml` | `Initialization` |
| `pre_collect` (`sb_pre_collect.xml`) | `grade` (setup stage) | `jobs/grade.yaml` steps `stage: setup` | `Grading` |
| `grade.xml` `verify commandOutput` | `grade` (collect stage) | `jobs/grade.yaml` steps `stage: collect` | `Grading` |
| `grade.xml` `verify parse` + report | `grade` (evaluate+report) | `jobs/grade.yaml` steps `stage: evaluate`/`report` | `Grading` |

`pre_collect` is **not a separate phase** — it is the **setup stage of the `grade` job**.

---

## 10. Fault Tolerance

### 10.1 `on_error`

Per-step failure policy. There is no `try`/`catch` wrapper — error handling is a field on the step.

```yaml
- id: stop_lab
  uses: cml.lab_stop@v1
  with: { lab_id: "${ runtime_env.lab_id }" }
  on_error: { action: retry, retries: 3, backoff: 30 }
```

| `action` | Behavior |
|---|---|
| `fail` (default) | The step faults; the job stops. |
| `continue` | The error is recorded; execution proceeds to the next step. |
| `retry` | Retry up to `retries` times with `backoff` seconds between attempts; then `fail`. |

### 10.2 `timeout`

`timeout: <seconds>` bounds a single step. On expiry the runtime raises an `errors/timeout` fault,
subject to the step's `on_error` policy.

### 10.3 Error types

| Error Type | Status | Description |
|---|---|---|
| `errors/expression` | 400 | jq expression evaluation failure |
| `errors/validation` | 422 | Schema validation failure |
| `errors/timeout` | 408 | Step timeout exceeded |
| `errors/communication` | 503 | Connector/adapter communication failure |
| `errors/authentication` | 401 | Credential/auth failure |
| `errors/not-found` | 404 | Resource not found (lab, node, scenarioFunction) |
| `errors/conflict` | 409 | Resource state conflict |
| `errors/cancelled` | 499 | Job cancelled by caller |

All error types are prefixed with `https://lcm.cisco.com/dsl/2.0.0/`.

---

## 11. Deferred: `CompositeScenario` & `for_each`

Model B (closed primitives + flat DAG) is the normative v2. ADR-057 §2.8 **specifies but defers**
two opt-in extensions that recover reuse/iteration without re-opening the sandbox:

- **`CompositeScenario`** (`PAv1/composites/<name>.yaml`) — a content-defined, parameterised group
  of _closed primitives only_, invoked from any step via a uniform call site:

  ```yaml
  - id: check_lo0
    uses: composite:check_interface_up_up@v1
    target: rtr01
    with:  { interface: Loopback0, ip: "${ runtime_env.devices.rtr01.lo0_ip }" }
    capture: { interface_name: rtr01_lo_name }   # promoted from the composite's `export`
  ```

  A composite runs in an **isolated `vars.*` frame** (ADR-058 §2.5): trusted scopes pass through;
  `vars.*` is fresh, seeded only from `parameters`; only `export` keys return. Guardrails: composes
  only the closed set (+ other composites), **max depth 3**, circular references rejected at sync.

- **`for_each`** — a step/composite modifier that runs a step once per list element, binding a loop
  `var` into `vars.*`. It collapses per-device duplication (`c_rtr01_*` / `c_rtr02_*`) into one
  iterated step.

These are **not implemented in v2**. Until then, iteration is either spelled out per device or
driven by the ruleset (a single `evaluate` step expands `grading/rubric.yaml` into N checks).

---

## 12. AI-Generation Contract & Sync-Time Validation

A JSON Schema set is published from `lcm_core` at `src/core/lcm_core/schemas/` (ADR-057 §2.7):

| Schema file | Validates |
|---|---|
| `lifecycle.schema.json` | `PAv1/lifecycle.yaml` (phases, native steps, job refs, gating) |
| `job-definition.schema.json` | `PAv1/jobs/*.yaml` (the step DAG: `id`/`uses`/`target`/`with`/`capture`/`when`/`on_error`/`timeout`/`stage`) |
| `connector-model.schema.json` | `PAv1/connectors.yaml` |
| `evaluation-ruleset.schema.json` | `PAv1/grading/rubric.yaml` |
| `process-report-spec.schema.json` | `PAv1/reports/*.yaml` |
| `scenario-functions.catalog.json` | **generated** from the SE `@scenario` registry — each primitive's `input_schema`/`output_schema` |

Validation runs at **content sync** (ADR-023): a step's `with:` is validated against the referenced
primitive's `input_schema`, and its `capture:` keys against the `output_schema`. An invalid package
**fails the sync** (no partial ingestion). The LLM **selects** from the closed catalogue and
**wires** scopes; it never invents a primitive or writes code.

---

## 13. Complete Example

A two-part view of a CCNP exam lab: orchestration in `lifecycle.yaml`, bodies in `jobs/`.

### 13.1 `PAv1/lifecycle.yaml`

```yaml
apiVersion: pav1
kind: Lifecycle
metadata:
  lablet: exam-ccnp-enarsi-v1-lab-1.1
spec:
  phases:
    - name: instantiate
      native_steps_by_pod_type:
        cml_on_aws: [worker_lab_resolve, pod_locator, ports_alloc, lds_register]
      jobs:
        - definition: cml.lab_start@v1

    - name: post_init
      jobs:
        - definition: post_init@v1
          process_type: Initialization

    - name: grade
      jobs:
        - definition: grade@v1
          process_type: Grading
          rubric: rubric
          report: score_report

    - name: teardown
      native_steps_by_pod_type:
        cml_on_aws: [archive]
      jobs:
        - definition: cml.wipe@v1
          process_type: Archive
```

### 13.2 `PAv1/jobs/grade.yaml` (collect → evaluate → report)

```yaml
apiVersion: pav1
kind: JobDefinition
metadata:
  name: grade
  version: v1
spec:
  process_type: Grading
  steps:
    # --- setup stage (was sb_pre_collect.xml) ---
    - id: settle
      uses: pause@v1
      with: { seconds: 10 }

    # --- collect stage (was grade.xml verify commandOutput) ---
    - id: c_rtr01_lo
      uses: collect@v1
      target: rtr01
      stage: collect
      with: { command: "show ip interface brief | include Loopback0" }
      capture: { output: rtr01_lo }

    - id: c_rtr02_lo
      uses: collect@v1
      target: rtr02
      stage: collect
      with: { command: "show ip interface brief | include Loopback0" }
      capture: { output: rtr02_lo }

    # --- evaluate stage: ruleset-driven (one step expands grading/rubric.yaml into N checks) ---
    - id: evaluate_rubric
      uses: evaluate.regex@v1
      stage: evaluate
      with:
        source: "${ vars }"                 # captured collect outputs
        rubric: "${ content.files.rubric }" # grading/rubric.yaml supplies items + checks
      capture: { items: graded_items }

    # --- report stage: process_type Grading -> report.score@v1 ---
    - id: emit_score
      uses: report.score@v1
      stage: report
      with:
        items: "${ vars.graded_items }"
        report_class: "${ content.files.score_report }"
      capture: { report_ref: score_report_ref }
```

> **Iteration note.** The `c_rtr01_lo` / `c_rtr02_lo` duplication is the documented cost of the flat
> DAG (ADR-057 §2.8). Once `for_each` (§11) ships, these collapse into one iterated step over a
> device list. Until then, spell them out or drive expansion from the rubric.

---

## 14. Mapping to Current Step Handlers

How existing lablet-controller step handlers map onto SE scenarioFunctions:

| Current Step Handler | scenarioFunction | Notes |
|---|---|---|
| `lab_resolve_step.py` | `cml.lab_resolve@v1` | Direct port |
| `lab_start_step.py` | `cml.lab_start@v1` | Adds convergence poll |
| `lab_stop_step.py` | `cml.lab_stop@v1` | — |
| `lab_wipe_step.py` | `cml.wipe@v1` | — |
| `execute_command_on_cml_node_step.py` | `exec@v1` / `collect@v1` | command vs `show` capture |
| `transfer_file_step.py` | `copy@v1` | content-ref source |
| — (new) | `evaluate.regex@v1` | single check primitive |
| — (new) | `report.score@v1` / `report.readiness@v1` | report assembly |

---

## 15. Future Extensions

### 15.1 Python SDK

A typed builder for constructing `JobDefinition` documents:

```python
from lcm_dsl import JobDefinition, Step

job = JobDefinition(name="post_init", version="v1", process_type="Initialization")
job.add(Step(id="settle", uses="pause@v1", with_={"seconds": 30}))
job.add(Step(id="mkdir_tmp", uses="exec@v1", target="workstation_22",
             with_={"command": "mkdir -p /home/cisco/Desktop/tmp/"}, capture={"ok": "cmd0_ok"}))
job.to_yaml()  # -> PAv1/jobs/post_init.yaml
```

### 15.2 Visual Editor

A browser-based step-DAG editor for content authors that emits `jobs/*.yaml` and validates against
`scenario-functions.catalog.json` live.

### 15.3 Dry-Run Mode

Execute a JobDefinition in validation mode (no connector calls), returning the resolved step order
and interpolated expressions without side effects:

```http
POST /api/v1/jobs
{ ..., "dry_run": true }
```
