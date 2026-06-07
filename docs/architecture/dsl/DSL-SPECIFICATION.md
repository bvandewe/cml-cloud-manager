# LCM Pod Automation DSL — Specification v1.0.0

| Attribute | Value |
|-----------|-------|
| **Version** | 1.0.0-draft |
| **Date** | 2026-06-05 |
| **Status** | Draft |
| **Expression Language** | jq (strict mode) |
| **Reference** | [ServerlessWorkflow DSL](https://github.com/serverlessworkflow/specification/blob/main/dsl.md) |
| **Related** | [ADR-044](../adr/ADR-044-content-driven-lifecycle-engine.md) |

---

## 1. Abstract

This document defines the **LCM Pod Automation DSL** — a proprietary domain-specific
language for defining pod lifecycle automation within the ScenarioEngine. The DSL is
inspired by the ServerlessWorkflow specification but tailored for lab pod orchestration,
infrastructure adapter dispatch, and content-driven grading.

The DSL is used in `PAv1/lifecycle.yaml` files within content packages to declare
what tasks execute during each session lifecycle phase.

---

## 2. Design Principles

1. **Imperative verbs** — Task types use action verbs: `call`, `do`, `set`, `raise`
2. **Implicit defaults** — Omitted properties use sensible defaults (no verbose boilerplate)
3. **Inline + reusable** — Tasks can be defined inline or reference named scenarios
4. **jq expressions** — All dynamic values use jq with `${ }` delimiters (strict mode)
5. **Data flow pipeline** — Each task has typed input/output/context transformations
6. **Content-portable** — Definitions reference scenarios by name@version, not implementation

---

## 3. Document Structure

Every DSL document begins with a `document` header:

```yaml
document:
  dsl: "1.0.0"              # DSL version (semver)
  namespace: lcm             # Logical namespace
  name: my-lab-lifecycle     # Unique name within namespace
  version: "1.0.0"          # Document version (semver)
```

---

## 4. Expression Language: jq

### 4.1 Syntax

All runtime expressions use [jq](https://jqlang.github.io/jq/) enclosed in `${ }`:

```yaml
# Simple property access
value: ${ .lab_id }

# Conditional
if: ${ .port_template != null }

# Transformation
output:
  as: ${ { lab_id: .lab_id, title: .title } }

# Array operations
in: ${ .devices | map(select(.type == "router")) }

# String interpolation (jq string interpolation)
message: ${ "Lab \(.lab_id) started with \(.nodes | length) nodes" }
```

### 4.2 Runtime Arguments

The following arguments are available in jq expressions depending on context:

| Argument | Type | Available In | Description |
|----------|------|-------------|-------------|
| `$context` | object | All expressions | Accumulated workflow context (mutable via `export.as`) |
| `$input` | any | Task definition, `output.as` | Current task's transformed input |
| `$output` | any | `output.as`, `export.as` | Current task's raw output |
| `$secrets` | object | `input.from` only | Secret store (restricted access) |
| `$task` | object | Task definition | Current task descriptor (name, reference) |
| `$workflow` | object | All expressions | Workflow descriptor (definition, startedAt) |
| `$item` | any | Inside `for` loops | Current iteration item |
| `$index` | integer | Inside `for` loops | Current iteration index (0-based) |

### 4.3 Evaluation Modes

| Mode | Delimiter | Behavior |
|------|-----------|----------|
| **Strict** (default) | `${ expr }` | Only `${ }` delimited strings are evaluated as jq |
| **Loose** | Any string | All string values are attempted as jq expressions |

The DSL uses **strict mode** exclusively. Bare strings are literal values.

### 4.4 Error Handling

When a jq expression evaluation fails, the runtime raises:

```yaml
type: https://lcm.cisco.com/dsl/1.0.0/errors/expression
status: 400
detail: "jq evaluation failed: .nonexistent_field"
instance: /phases/instantiate/do/2/resolveTopology
```

---

## 5. Task Types

### 5.1 `call` — Invoke a Registered Scenario

Calls a named scenario from the SE registry. This is the primary task type for
pod automation operations.

```yaml
- resolveTopology:
    call: lab_resolve@v1
    with:
      definition_id: ${ $context.definition_id }
      worker_ip: ${ $context.worker.ip }
    input:
      from: ${ { definition_id: $context.definition_id } }
    output:
      as: ${ { lab_id: .lab_id, title: .title, nodes: .nodes } }
    timeout:
      seconds: 120
    retry:
      when: ${ .error.status == 503 }
      limit:
        attempt:
          count: 3
      delay:
        seconds: 10
      backoff:
        exponential: {}
```

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `call` | string | ✅ | Scenario reference: `{name}@{version}` |
| `with` | object | ❌ | Arguments passed directly to scenario function |
| `if` | expression | ❌ | Condition — skip task if evaluates to false/null |
| `input` | object | ❌ | Input transformation (`.from`, `.schema`) |
| `output` | object | ❌ | Output transformation (`.as`, `.schema`) |
| `export` | object | ❌ | Context update (`.as`, `.schema`) |
| `timeout` | object | ❌ | Max execution time |
| `retry` | object | ❌ | Retry policy |
| `then` | string | ❌ | Flow directive: `continue` (default), `end`, or task name |

### 5.2 `do` — Sequential Sub-Tasks

Executes a list of tasks in sequence. Output of each task flows as input to the next.

```yaml
- setupPhase:
    do:
      - step1:
          call: lab_resolve@v1
          with:
            definition_id: ${ $context.definition_id }
      - step2:
          call: lab_start@v1
          with:
            lab_id: ${ $context.lab_id }
      - step3:
          set:
            setup_complete: true
```

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `do` | list[task] | ✅ | Ordered list of sub-tasks |
| `if` | expression | ❌ | Condition to skip entire block |
| `input` | object | ❌ | Input transformation for the block |
| `output` | object | ❌ | Output transformation (result = last task's output) |

### 5.3 `for` — Iterate Over Collection

Iterates over a collection, executing a task block for each item. Supports
conditional filtering and context accumulation.

```yaml
- gradeAllItems:
    for:
      each: item
      in: ${ $context.grading_rules }
      while: ${ $item.enabled != false }
    do:
      - gradeItem:
          call: grade_item@v1
          with:
            item_id: ${ $item.id }
            device: ${ $item.target_device }
            command: ${ $item.command }
            expected: ${ $item.expected }
          output:
            as: ${ { score: .score, max: .max, feedback: .feedback } }
          export:
            as: ${ $context | .scores[$item.id] = $output }
```

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `for.each` | string | ✅ | Variable name bound to current item (`$item`) |
| `for.in` | expression | ✅ | Collection to iterate over |
| `for.while` | expression | ❌ | Continue condition (checked before each iteration) |
| `do` | list[task] | ✅ | Tasks to execute per item |
| `output` | object | ❌ | Aggregated output transformation |

**Iteration context:** Inside the `for` body, `$item` and `$index` are available
in addition to standard runtime arguments.

### 5.4 `fork` — Parallel Execution

Executes multiple branches in parallel. All branches must complete (or one must
fault, depending on `compete` mode).

```yaml
- parallelSetup:
    fork:
      branches:
        - resolveTopology:
            call: lab_resolve@v1
            with:
              definition_id: ${ $context.definition_id }
        - allocatePorts:
            call: ports_alloc@v1
            with:
              template: ${ $context.port_template }
      compete: false   # Wait for ALL branches (default)
```

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `fork.branches` | list[task] | ✅ | Tasks to execute in parallel |
| `fork.compete` | boolean | ❌ | If true, first completion cancels others (default: false) |
| `output` | object | ❌ | Transformation on merged branch outputs |

**Output merging:** Branch outputs are merged into a single object keyed by task name:

```json
{ "resolveTopology": { "lab_id": "..." }, "allocatePorts": { "ports": [...] } }
```

### 5.5 `set` — Set Context Variables

Updates the workflow context with new values. This is the simplest way to
manipulate state between tasks.

```yaml
- initContext:
    set:
      lab_id: ${ $input.lab_id }
      phase: instantiate
      started_at: ${ now | todate }
      items_to_grade: ${ $context.grading_rules | length }
```

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `set` | object | ✅ | Key-value pairs to merge into `$context` |

Values can be literals or jq expressions. The resulting object is **merged** into
the current context (not replaced).

### 5.6 `switch` — Conditional Branching

Selects one execution path from multiple alternatives based on conditions.

```yaml
- checkLabState:
    switch:
      - case: labExists
        when: ${ $context.existing_lab != null }
        then: startExistingLab

      - case: noLab
        when: ${ $context.existing_lab == null }
        then: importAndStart

      - default:
        then: raise_unknown_state
```

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `switch` | list[case] | ✅ | Ordered list of case conditions |
| `switch[].case` | string | ❌ | Case label (for readability) |
| `switch[].when` | expression | ❌ | Condition (omit for `default`) |
| `switch[].then` | string | ✅ | Flow directive: task name, `continue`, or `end` |

Cases are evaluated **in order**. First matching case wins. A case without `when`
is the default (must be last).

### 5.7 `try` — Error Handling and Retry

Attempts a task and handles errors gracefully.

```yaml
- robustLabStart:
    try:
      call: lab_start@v1
      with:
        lab_id: ${ $context.lab_id }
    catch:
      errors:
        with:
          status: 503
      retry:
        delay:
          seconds: 10
        backoff:
          exponential: {}
        limit:
          attempt:
            count: 3
      do:
        - logFailure:
            emit:
              event:
                type: io.lcm.se.task.retry-exhausted
                data: ${ { lab_id: $context.lab_id, error: $error } }
        - fallback:
            set:
              lab_start_failed: true
```

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `try` | task | ✅ | The task to attempt |
| `catch.errors.with` | object | ❌ | Error filter (match by status, type) |
| `catch.retry` | object | ❌ | Retry policy (delay, backoff, limit) |
| `catch.do` | list[task] | ❌ | Fallback tasks if retries exhausted |

**Error object (`$error`):** Available in `catch` scope:

```json
{
  "type": "https://lcm.cisco.com/dsl/1.0.0/errors/communication",
  "status": 503,
  "title": "Service Unavailable",
  "detail": "CML API returned 503",
  "instance": "/phases/instantiate/do/3/robustLabStart"
}
```

### 5.8 `raise` — Signal Failure

Explicitly raises an error, causing the current task (and potentially the workflow)
to fault.

```yaml
- validatePrereqs:
    switch:
      - case: missing_topology
        when: ${ $context.topology == null }
        then: failMissingTopology
      - default:
        then: continue

- failMissingTopology:
    raise:
      error:
        type: https://lcm.cisco.com/dsl/1.0.0/errors/validation
        status: 422
        title: Missing Topology
        detail: ${ "No topology found for definition \($context.definition_id)" }
```

### 5.9 `wait` — Pause Execution

Pauses execution for a specified duration.

```yaml
- waitForConvergence:
    wait:
      seconds: 30
```

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `wait.seconds` | integer | ❌* | Wait duration in seconds |
| `wait.minutes` | integer | ❌* | Wait duration in minutes |
| `wait.hours` | integer | ❌* | Wait duration in hours |

*At least one duration property required.

### 5.10 `emit` — Publish CloudEvent

Emits a CloudEvent to the configured event sink.

```yaml
- notifyPhaseComplete:
    emit:
      event:
        type: io.lcm.se.phase.completed
        source: /scenario-engine/jobs/${ $workflow.id }
        subject: ${ $context.session_id }
        data:
          phase: ${ $context.phase }
          duration: ${ now - $workflow.startedAt.epoch.seconds }
          results: ${ $context }
```

### 5.11 `run` — Execute Shell/Script

Executes a command on a target node via the infrastructure adapter. Used for
CML node operations (show commands, file transfers, configuration).

```yaml
- captureRoutes:
    run:
      adapter: ${ $context.worker.adapter }
      target:
        lab_id: ${ $context.lab_id }
        node: ${ $item.target_device }
      command: ${ $item.collect_command }
    output:
      as: ${ { raw_output: .stdout, exit_code: .exit_code } }
    timeout:
      seconds: 60
```

**Properties:**

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `run.adapter` | string/expression | ❌ | Adapter override (defaults to job's adapter) |
| `run.target.lab_id` | string/expression | ✅ | Target lab |
| `run.target.node` | string/expression | ✅ | Target node within lab |
| `run.command` | string/expression | ✅ | Command to execute |
| `run.timeout` | object | ❌ | Command-level timeout |

### 5.12 `listen` — Wait for External Event (Future)

Waits for an external CloudEvent before proceeding. Planned for future convergence
callback patterns.

```yaml
- waitForConvergence:
    listen:
      to:
        one:
          with:
            type: io.lcm.worker.lab.converged
            subject: ${ $context.lab_id }
      timeout:
        minutes: 5
```

---

## 6. Data Flow

### 6.1 Pipeline

Each task processes data through a transformation pipeline:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Task Data Flow                                                          │
│                                                                         │
│  Raw Input ──→ input.schema ──→ input.from ──→ [Task Execution]         │
│                (validate)        (transform)                            │
│                                                                         │
│  [Task Execution] ──→ output.as ──→ output.schema ──→ export.as         │
│                       (transform)    (validate)       (update $context)  │
│                                                                         │
│  Transformed output ──→ Next Task (as raw input)                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Input Transformation

```yaml
input:
  schema:                    # JSON Schema to validate raw input
    type: object
    required: [lab_id]
  from: ${ { lab_id: .lab_id, title: .title } }  # Transform raw → task input
```

- `input.schema` — Optional JSON Schema validation (fails with `ValidationError`)
- `input.from` — jq expression evaluated on raw input; result becomes `$input`
- Default: identity (raw input passed through unchanged)

### 6.3 Output Transformation

```yaml
output:
  as: ${ { lab_id: .id, converged: .state == "STARTED" } }
  schema:                    # JSON Schema to validate transformed output
    type: object
    required: [lab_id, converged]
```

- `output.as` — jq expression evaluated on raw task output; result becomes transformed output
- `output.schema` — Optional validation of transformed output
- Default: identity (raw output passed through unchanged)

### 6.4 Context Export

```yaml
export:
  as: ${ $context | .lab_id = $output.lab_id | .converged = $output.converged }
  schema:
    type: object
    required: [lab_id]
```

- `export.as` — jq expression that produces new `$context` value
- Evaluated with access to `$context`, `$output`, `$input`
- Default: existing context unchanged
- The `|` pipe operator enables functional context updates without mutation

### 6.5 Workflow-Level Input/Output

```yaml
document:
  dsl: "1.0.0"
  name: my-workflow

input:
  from: ${ { definition_id: .definition_id, worker: .worker } }
  schema:
    type: object
    required: [definition_id, worker]

output:
  as: ${ { results: $context, duration: now - $workflow.startedAt.epoch.seconds } }
  schema:
    type: object

phases:
  instantiate:
    do: [...]
```

---

## 7. Flow Directives

Tasks can control execution flow via the `then` property:

| Directive | Behavior |
|-----------|----------|
| `continue` | Execute next task in declaration order (default) |
| `end` | Gracefully end the workflow/phase |
| `{taskName}` | Jump to named task (within same scope only) |

```yaml
- checkStatus:
    switch:
      - case: alreadyRunning
        when: ${ $context.lab_state == "STARTED" }
        then: skipToReady           # Jump to named task
      - default:
        then: continue              # Normal sequential flow

- startLab:
    call: lab_start@v1
    with:
      lab_id: ${ $context.lab_id }

- skipToReady:
    set:
      converged: true
```

**Scope restriction:** Flow directives can only target tasks at the same nesting
depth. You cannot jump from inside a `for` loop to a task outside it.

---

## 8. Fault Tolerance

### 8.1 Timeouts

```yaml
timeout:
  seconds: 120          # Task-level timeout
  # OR
  minutes: 5
  # OR
  after:
    seconds: 300        # Alternative syntax
```

When a timeout occurs, the runtime raises:

```yaml
type: https://lcm.cisco.com/dsl/1.0.0/errors/timeout
status: 408
detail: "Task 'lab_start' exceeded timeout of 120s"
```

### 8.2 Retry Policies

```yaml
retry:
  when: ${ .error.status >= 500 }   # Condition to retry (default: any error)
  delay:
    seconds: 5                       # Initial delay
  backoff:
    exponential:                     # Exponential backoff
      exponent: 2
    # OR
    linear: {}                       # Linear backoff
    # OR
    constant: {}                     # No backoff (constant delay)
  limit:
    attempt:
      count: 3                       # Max retry attempts
    duration:
      minutes: 5                     # Max total retry duration
  jitter:
    from:
      seconds: 0
    to:
      seconds: 5
```

### 8.3 Error Types

| Error Type | Status | Description |
|------------|--------|-------------|
| `errors/expression` | 400 | jq expression evaluation failure |
| `errors/validation` | 422 | Schema validation failure |
| `errors/timeout` | 408 | Task/workflow timeout exceeded |
| `errors/communication` | 503 | Adapter communication failure |
| `errors/authentication` | 401 | Credential/auth failure |
| `errors/not-found` | 404 | Resource not found (lab, node, scenario) |
| `errors/conflict` | 409 | Resource state conflict |
| `errors/cancelled` | 499 | Job cancelled by caller |

All error types are prefixed with `https://lcm.cisco.com/dsl/1.0.0/`.

---

## 9. Scenario Catalog

### 9.1 Reference Format

Scenarios are referenced by `{name}@{version}`:

```yaml
call: lab_resolve@v1        # Call lab_resolve version 1
call: grade_item@v2         # Call grade_item version 2
```

### 9.2 Scenario Definition (Python)

```python
@scenario(name="lab_resolve", version="v1")
async def lab_resolve(input: dict, adapter: AdapterProtocol, ctx: ExecutionContext) -> dict:
    """Resolve or import a lab topology on the target worker.

    Input Schema:
      definition_id: str (required)

    Output Schema:
      lab_id: str
      title: str
      nodes: list[{name: str, state: str}]
    """
    ...
```

### 9.3 Schema Introspection

The SE exposes scenario schemas for validation:

```http
GET /api/v1/scenarios/lab_resolve/v1

{
  "name": "lab_resolve",
  "version": "v1",
  "description": "Resolve or import a lab topology...",
  "input_schema": {
    "type": "object",
    "required": ["definition_id"],
    "properties": { "definition_id": { "type": "string" } }
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "lab_id": { "type": "string" },
      "title": { "type": "string" },
      "nodes": { "type": "array" }
    }
  }
}
```

---

## 10. Lifecycle Definition Example (Complete)

This is a complete `PAv1/lifecycle.yaml` for a CCNP exam lab:

```yaml
document:
  dsl: "1.0.0"
  namespace: lcm
  name: exam-ccnp-enarsi-v1-lab-1.1
  version: "1.2.0"

input:
  schema:
    type: object
    required: [definition_id, session_id, worker]
    properties:
      definition_id: { type: string }
      session_id: { type: string }
      worker:
        type: object
        required: [ip, cml_username, cml_password, adapter]
  from: |
    ${
      {
        definition_id: .definition_id,
        session_id: .session_id,
        worker: .worker,
        variables: (.variables // {}),
        evidence: {},
        scores: {}
      }
    }

phases:
  instantiate:
    description: "Import lab, configure networking, start, provision LDS"
    do:
      - resolveTopology:
          call: lab_resolve@v1
          with:
            definition_id: ${ $context.definition_id }
          output:
            as: ${ { lab_id: .lab_id, title: .title } }
          export:
            as: ${ $context | .lab_id = $output.lab_id | .lab_title = $output.title }
          timeout:
            seconds: 120
          retry:
            limit:
              attempt:
                count: 2
            delay:
              seconds: 15

      - allocatePorts:
          call: ports_alloc@v1
          if: ${ $context.variables.port_template != null }
          with:
            lab_id: ${ $context.lab_id }
            template: ${ $context.variables.port_template }
          export:
            as: ${ $context | .ports = $output.ports }

      - syncTags:
          call: tags_sync@v1
          with:
            lab_id: ${ $context.lab_id }
            session_id: ${ $context.session_id }

      - startLab:
          call: lab_start@v1
          with:
            lab_id: ${ $context.lab_id }
          output:
            as: ${ { converged: .converged, nodes: .nodes } }
          export:
            as: ${ $context | .converged = $output.converged | .nodes = $output.nodes }
          timeout:
            minutes: 10
          retry:
            when: ${ .error.status == 503 or .error.status == 504 }
            limit:
              attempt:
                count: 3
            delay:
              seconds: 30
            backoff:
              exponential: {}

      - waitForConvergence:
          if: ${ $context.converged != true }
          wait:
            seconds: 60

      - verifyConvergence:
          if: ${ $context.converged != true }
          call: lab_check_convergence@v1
          with:
            lab_id: ${ $context.lab_id }
          export:
            as: ${ $context | .converged = $output.converged }

      - provisionLds:
          call: lds_provision@v1
          if: ${ ($context.devices | length) > 0 }
          with:
            lab_id: ${ $context.lab_id }
            devices: ${ $context.devices }
            session_id: ${ $context.session_id }
          export:
            as: ${ $context | .lds_registered = true | .lds_url = $output.url }

      - transferStudentFiles:
          call: transfer_file@v1
          if: ${ $context.variables.student_archive != null }
          with:
            lab_id: ${ $context.lab_id }
            node: ubuntu-desktop
            source: ${ $context.variables.student_archive }
            destination: /tmp/lab-files.tar.gz

  collect:
    description: "Gather evidence from each grading item"
    do:
      - gatherEvidence:
          for:
            each: item
            in: ${ $context.grading_rules }
          do:
            - collectFromDevice:
                try:
                  run:
                    target:
                      lab_id: ${ $context.lab_id }
                      node: ${ $item.target_device }
                    command: ${ $item.collect_command }
                  output:
                    as: ${ { output: .stdout, collected_at: now | todate } }
                  export:
                    as: ${ $context | .evidence[$item.id] = $output }
                catch:
                  errors:
                    with:
                      status: 408   # Timeout on device
                  do:
                    - markTimeout:
                        set:
                          evidence_error: ${ "Timeout collecting \($item.id) from \($item.target_device)" }
                        export:
                          as: |
                            ${
                              $context | .evidence[$item.id] = {
                                output: null,
                                error: "timeout",
                                collected_at: (now | todate)
                              }
                            }

  grade:
    description: "Evaluate each item against expected results"
    do:
      - gradeItems:
          for:
            each: item
            in: ${ $context.grading_rules }
          do:
            - evaluateItem:
                call: grade_item@v1
                with:
                  item_id: ${ $item.id }
                  evidence: ${ $context.evidence[$item.id] }
                  expected: ${ $item.expected }
                  scoring: ${ $item.scoring }
                output:
                  as: |
                    ${
                      {
                        score: .score,
                        max_score: .max_score,
                        passed: (.score >= .max_score * .pass_threshold),
                        feedback: .feedback
                      }
                    }
                export:
                  as: ${ $context | .scores[$item.id] = $output }

      - computeTotals:
          set:
            total_score: ${ $context.scores | to_entries | map(.value.score) | add }
            max_possible: ${ $context.scores | to_entries | map(.value.max_score) | add }
            percentage: |
              ${
                (($context.scores | to_entries | map(.value.score) | add) /
                 ($context.scores | to_entries | map(.value.max_score) | add) * 100)
                | floor
              }

      - generateReport:
          call: generate_phase_report@v1
          with:
            phase: grade
            scores: ${ $context.scores }
            total: ${ $context.total_score }
            max: ${ $context.max_possible }
            percentage: ${ $context.percentage }
            template: "PAv1/reports/grade_report.yaml"

  teardown:
    description: "Stop lab, clean up resources"
    do:
      - stopLab:
          try:
            call: lab_stop@v1
            with:
              lab_id: ${ $context.lab_id }
          catch:
            do:
              - forceStop:
                  call: lab_stop@v1
                  with:
                    lab_id: ${ $context.lab_id }
                    force: true

      - deregisterLds:
          call: lds_deregister@v1
          if: ${ $context.lds_registered == true }
          with:
            lab_id: ${ $context.lab_id }
            session_id: ${ $context.session_id }

      - wipeLab:
          call: lab_wipe@v1
          with:
            lab_id: ${ $context.lab_id }

      - releasePorts:
          call: ports_release@v1
          if: ${ $context.ports != null }
          with:
            ports: ${ $context.ports }

  restore:
    description: "Reset lab for student retake"
    do:
      - wipeLab:
          call: lab_wipe@v1
          with:
            lab_id: ${ $context.lab_id }

      - reimportLab:
          call: lab_resolve@v1
          with:
            definition_id: ${ $context.definition_id }
            force_import: true
          export:
            as: ${ $context | .lab_id = $output.lab_id }

      - startLab:
          call: lab_start@v1
          with:
            lab_id: ${ $context.lab_id }
          timeout:
            minutes: 10

      - resetEvidence:
          set:
            evidence: {}
            scores: {}
            total_score: null
            percentage: null

output:
  as: |
    ${
      {
        session_id: $context.session_id,
        lab_id: $context.lab_id,
        converged: $context.converged,
        scores: $context.scores,
        total_score: $context.total_score,
        percentage: $context.percentage,
        lds_url: $context.lds_url
      }
    }
```

---

## 11. PAv1/manifest.yaml Schema

```yaml
# PAv1/manifest.yaml — Pod infrastructure requirements
schema_version: "1.0"
pod_type: cml_on_aws                # Required adapter type
required_adapter_version: ">=1.0.0" # Minimum adapter version
min_resources:
  vcpus: 16
  memory_gb: 64
  storage_gb: 200
features:
  - nested_virtualization
  - serial_console
node_definitions:
  - iosv
  - iosvl2
  - ubuntu-desktop
  - asav
```

---

## 12. Mapping to Current Step Handlers

This table shows how existing lablet-controller step handlers map to SE scenarios:

| Current Step Handler | SE Scenario | Notes |
|---------------------|-------------|-------|
| `lab_resolve_step.py` | `lab_resolve@v1` | Direct port |
| `lab_start_step.py` | `lab_start@v1` | Add convergence check |
| `lab_stop_step.py` | `lab_stop@v1` | Add force option |
| `lab_wipe_step.py` | `lab_wipe@v1` | Direct port |
| `ports_alloc_step.py` | `ports_alloc@v1` | Direct port |
| `ports_release_step.py` | `ports_release@v1` | Direct port |
| `tags_sync_step.py` | `tags_sync@v1` | Direct port |
| `execute_command_on_cml_node_step.py` | `run` task type | Uses adapter directly |
| `transfer_file_step.py` | `transfer_file@v1` | Direct port |
| `lds_provision_step.py` | `lds_provision@v1` | Direct port |
| `lds_deregister_step.py` | `lds_deregister@v1` | Direct port |
| — (new) | `collect_evidence@v1` | New: per-item evidence |
| — (new) | `grade_item@v1` | New: per-item grading |
| — (new) | `generate_phase_report@v1` | New: report assembly |
| — (new) | `lab_check_convergence@v1` | New: health check |

---

## 13. Future Extensions

### 13.1 Python SDK

A Python SDK for programmatically constructing DSL documents:

```python
from lcm_dsl import Workflow, Phase, Call, For, Set

wf = Workflow(name="my-lab", version="1.0.0")
wf.phase("instantiate").do(
    Call("lab_resolve@v1", with_={"definition_id": "${ $context.definition_id }"}),
    Call("lab_start@v1", with_={"lab_id": "${ $context.lab_id }"}),
)
wf.to_yaml()  # Serialize to PAv1/lifecycle.yaml
```

### 13.2 Visual Editor

A browser-based DAG editor for content authors (generates lifecycle.yaml).

### 13.3 Dry-Run Mode

Execute lifecycle definitions in validation mode (no actual adapter calls):

```http
POST /api/v1/jobs
{ ..., "dry_run": true }
```

Returns the execution plan (task order, resolved expressions) without side effects.
