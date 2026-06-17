---
render_macros: false
---

# Scenario Definition Format DRAFT (from older project)

| Attribute | Value |
|-----------|-------|
| **Spec ID** | SPEC-001 |
| **Status** | � Superseded (mined) — see note below |
| **Owner** | WS-030 (Remote Output Collector) |
| **Consumers** | WS-020 (Scenario Engine), WS-070 (Content Pipelines) |
| **Last Updated** | 2026-03-12 |

!!! warning "Status: superseded by ADR-057/058, mined for composition & iteration"
    This draft proposed **Model A** — authors write whole _Scenarios_ (typed, versioned,
    parameterised units with their own `collect`/`parse`/`scenario` task language) and **scenarios
    invoke scenarios** (D16) and iterate (`for_each`, D18). The platform instead adopted
    **Model B** in [ADR-057](../adr/ADR-057-content-driven-lifecycle-dsl.md) /
    [ADR-058](../adr/ADR-058-lifecycle-data-flow-and-variable-scopes.md): a **closed set of trusted
    code primitives** (`scenarioFunction`) wired by a **flat declarative step DAG** (`JobDefinition`),
    with namespaced data-flow scopes — chosen for sandboxing, validatability, and LLM-generatability.

    The **composition (D16)** and **iteration (D18)** ideas from this draft are **not discarded**:
    they are carried forward as the deferred, opt-in **Model C hybrid** — `CompositeScenario`
    (content-defined groups of *closed primitives*, callable like a primitive) plus a `for_each`
    step modifier — recorded in [ADR-057 §2.8](../adr/ADR-057-content-driven-lifecycle-dsl.md) and
    [ADR-058 §2.5](../adr/ADR-058-lifecycle-data-flow-and-variable-scopes.md). Read this document as
    the **source material** for that analysis, not as the current normative format.

---

## Purpose

This specification defines the **Scenario YAML format** — the portable, versioned,
reusable unit of device interaction used by the Remote Output Collector (ROC).
Scenarios encode collect-and-parse logic that is device-agnostic and
platform-aware, replacing the legacy XML `<verify>` format entirely.

## Design Decisions

| # | Decision | Resolution |
|---|---|---|
| D1 | Interface discovery | Prefix-based search via `interface_type` param; actual name discovered via regex capture |
| D2 | Multi-device iteration | SE iterates caller-provided `devices` list; scenario author writes single-device logic |
| D3 | Variable scoping | Auto-scoped `@var` per device (e.g. `@ip_brief` → `R10.ip_brief`); `@device` is reserved |
| D4 | Pre-collection | Not a scenario concern — orchestrator (ScenarioEngine) handles invariant/concurrent collection |
| D5 | Platform variants | Commands and regex support `default` + platform-keyed overrides |
| D6 | Error messages | Scenario defines templated `on_fail`; caller can override per check id via `error_overrides` |
| D7 | Custom filters | Built-in filters (e.g. `to_prefix`) + admin-provisioned custom filters from config/seed |
| D10 | Expected result | Each check declares `expected_result: match` or `expected_result: no_match` |
| D11 | Scenario versioning | Colon syntax `scenario_name:version` (e.g. `check_bgp:1.2.0`); defaults to `:latest` when omitted |
| D16 | Scenario composition | `action: scenario` invokes a sub-scenario from within a parent scenario. Child runs in isolated variable scope; `params` pass data in, optional `export` promotes child `@vars` to parent scope. Max nesting depth 3; circular references detected at registration time |
| D18 | Iteration (`for_each`) | Task-level `for_each` over list parameters. Loop variable is a runtime `@var` with dot-notation for object properties. `for_each.stop_on_fail` defaults to `true`. Execution mode is `sequential` (default); `concurrent` reserved for future use |

## Notation Convention

| Syntax | Scope | Resolved at | Example |
|---|---|---|---|
| `{{ param }}` | Input parameter bound by caller | Task bind time | `{{ ip_address }}` → `1.1.1.11` |
| `{{ param \| filter }}` | Parameter with filter applied | Task bind time | `{{ mask \| to_prefix }}` → `32` |
| `@var` | Runtime variable, auto-scoped per device | Execution time | `@ip_brief` → `R10.ip_brief` on R10 |
| `@device` | Reserved — current device identifier | Execution time | `R10` |
| `@device.platform` | Reserved — current device platform | Execution time | `ios`, `xe`, `xr`, `nxos` |
| `@var.field` | Dot-notation access on `for_each` loop variable | Execution time | `@iface.ip` → `1.1.1.11` |

## Filters

```yaml
# Built-in filters (shipped with ROC service)
filters:
  built_in:
    - to_prefix         # 255.255.255.255 → 32
    - to_dotted_mask    # 32 → 255.255.255.255
    - escape_regex      # Escapes dots, brackets, etc.
    - upper / lower     # Case transforms
    - strip             # Whitespace trim

  # Custom filters: provisioned by admin users via config/seed data.
  # Registered at startup, available to all scenarios.
  # Example entry in seed config:
  #   custom_filters:
  #     - name: to_wildcard
  #       type: python_expression
  #       expression: "'.'.join(str(255 - int(o)) for o in value.split('.'))"
```

## Scenario Structure

A scenario definition contains:

- **`name`** + **`version`** — unique identity in the ScenarioRegistry
- **`description`** — human-readable purpose
- **`platforms`** — supported platform drivers
- **`parameters`** — typed input schema (bound by the caller at invocation)
- **`export`** — optional map of internal variables/outputs exposed to the caller
- **`tasks`** — ordered list of `ScenarioTask` entries

### Task Actions

| Action | Purpose |
|--------|---------|
| `collect` | Send a command to a device via RADkit HTTP; optionally `store` the output |
| `parse` | Evaluate regex `checks` against a stored output (`input: "@var"`) |
| `scenario` | Invoke a sub-scenario (see [Scenario Composition](#scenario-composition)) |

### Scenario Definition Example

```yaml
scenario:
  name: check_interface_up_up_with_ip_and_mask
  version: "1.0.0"
  description: >
    Verify that a device has an interface matching a given type prefix
    with a specific IP address and subnet mask, in up/up state.
    The interface number is not prescribed — only the type prefix, IP,
    and mask are checked. The actual interface name is discovered.
  platforms: [ios, xe, xr, nxos]

  parameters:
    interface_type:
      type: string
      description: "Interface type prefix (e.g. Loopback, GigabitEthernet)"
      required: true
    ip_address:
      type: ip_address
      description: "Expected IP address on the interface"
      required: true
    mask:
      type: network_mask
      description: "Expected subnet mask in dotted notation (e.g. 255.255.255.255)"
      required: true

  export:
    interface_name: interface_name
    my_sh_ip_int_br: my_collected_output_for_task_1

  tasks:

    # ── Task 1: Collect "show ip interface brief" ────────────
    - id: collect_ip_brief
      action: collect
      command:
        default: "show ip interface brief"
        xr: "show ipv4 interface brief"
        nxos: "show ip interface brief vrf all"
      store: my_collected_output_for_task_1

    # ── Task 2: Parse the collected output ───────────────────
    - id: find_interface
      action: parse
      input: "@my_collected_output_for_task_1"
      checks:

        - id: exists
          description: "{{ interface_type }} with {{ ip_address }} exists"
          regex:
            default: '^{{ interface_type }}\S*\s+{{ ip_address }}\s'
          flags: mi
          expected_result: match
          set: interface_found
          on_fail: "{{ interface_type }} with {{ ip_address }} is not found on @device."

        - id: not_down
          when: "@interface_found"
          description: "{{ interface_type }} with {{ ip_address }} is not down"
          regex:
            default: '^{{ interface_type }}\S*\s+{{ ip_address }}\s+.*(?:down|administratively)'
          flags: mi
          expected_result: no_match
          on_fail: "{{ interface_type }} with {{ ip_address }} was down on @device."

        - id: up_up_capture_name
          when: "@interface_found"
          description: "{{ interface_type }} with {{ ip_address }} is up/up; capture name"
          regex:
            default: '^({{ interface_type }}\d+)\s+{{ ip_address }}\s+.*up\s+up'
            xr: '^({{ interface_type }}\d+(?:/\d+)*)\s+{{ ip_address }}\s+.*Up\s+Up'
          flags: mi
          expected_result: match
          capture:
            interface_name: 1
          on_fail: "{{ interface_type }} with {{ ip_address }} in UP/UP state not found on @device."

    # ── Task 3: Collect detailed interface output ────────────
    - id: collect_interface_detail
      when: "@interface_found"
      action: collect
      command:
        default: "show ip interface @interface_name"
        xr: "show ipv4 interface @interface_name"
      store: interface_detail
      on_fail: "Could not collect detailed interface output for @interface_name on @device."

    # ── Task 4: Verify IP and mask from detailed output ──────
    - id: verify_ip_and_mask
      when: "@interface_found"
      action: parse
      input: "@interface_detail"
      checks:

        - id: verify_ip
          description: "Internet address contains {{ ip_address }}"
          regex:
            default: 'Internet address is {{ ip_address }}'
            xr: 'Internet address is {{ ip_address }}/\d+'
          flags: mi
          expected_result: match
          on_fail: "Internet address {{ ip_address }} not found on @interface_name (@device)."

        - id: verify_mask
          description: "Subnet mask is {{ mask }}"
          regex:
            default: 'Broadcast address is {{ mask }}'
            xr: 'Internet address is {{ ip_address }}/{{ mask | to_prefix }}'
          flags: mi
          expected_result: match
          on_fail: "Subnet mask {{ mask }} not set on @interface_name (@device)."
```

## Scenario Composition

Scenarios can invoke other scenarios via `action: scenario`, enabling composition
of complex verification logic from smaller, reusable building blocks (see D16).

### Syntax

```yaml
tasks:
  # Regular task
  - id: collect_routing_table
    action: collect
    command:
      default: "show ip route"
    store: routing_table

  # Invoke a sub-scenario
  - id: verify_loopback
    action: scenario
    scenario: check_interface_up_up_with_ip_and_mask:1.0.0
    params:
      interface_type: Loopback
      ip_address: "{{ loopback_ip }}"
      mask: "{{ loopback_mask }}"
    export:
      loopback_name: interface_name
    on_fail: "Loopback verification failed on @device."
```

### Composition Rules

| Aspect | Rule |
|---|---|
| **Variable isolation** | Child scenario runs in its own variable scope. Parent `@vars` are NOT visible to the child — only `params` are passed in |
| **Variable export** | Optional `export` map promotes specific child `@variables` to the parent scope (with optional rename). Without `export`, child state is discarded |
| **Failure propagation** | If any child check fails, the parent task fails. `on_fail` on the parent task overrides child error messages |
| **Nesting depth** | Max depth of 3. Circular references detected at registration time via dependency graph |
| **Scoring** (TBD if needed in Scenario!!!)| A `scenario` task can carry `points` like any other task. Child check results contribute to the parent task's pass/fail determination |
| **`when` guards** | `when:` on a `scenario` task skips the entire sub-scenario if the condition is false |
| **Platform resolution** | Child inherits the current `@device` and resolved platform from the parent execution context |

### Composition Example

```yaml
scenario:
  name: verify_full_interface_with_ospf
  version: "1.0.0"
  description: >
    Verify interface exists, is up/up, has correct IP/mask,
    and OSPF is enabled on it.
  platforms: [ios, xe, xr, nxos]

  parameters:
    interface_type: { type: string, required: true }
    ip_address:     { type: ip_address, required: true }
    mask:           { type: network_mask, required: true }
    ospf_process:   { type: string, required: true }

  tasks:
    - id: check_interface
      action: scenario
      scenario: check_interface_up_up_with_ip_and_mask:1.0.0
      params:
        interface_type: "{{ interface_type }}"
        ip_address: "{{ ip_address }}"
        mask: "{{ mask }}"
      export:
        if_name: interface_name

    - id: collect_ospf
      when: "@if_name"
      action: collect
      command:
        default: "show ip ospf interface @if_name"
      store: ospf_detail

    - id: verify_ospf
      when: "@if_name"
      action: parse
      input: "@ospf_detail"
      checks:
        - id: ospf_enabled
          description: "OSPF process {{ ospf_process }} is enabled on @if_name"
          regex:
            default: 'Process ID {{ ospf_process }}'
          flags: mi
          expected_result: match
          on_fail: "OSPF process {{ ospf_process }} not found on @if_name (@device)."
```

## Iteration (`for_each`)

Tasks can iterate over list parameters via `for_each`, executing their logic
once per element (see D18).

### Task-Level `for_each`

A scenario task iterates over a list parameter — e.g., "check that each expected
neighbor is in FULL state":

```yaml
parameters:
  expected_neighbors:
    type: list
    description: "List of expected OSPF neighbor router IDs"
    required: true

tasks:
  - id: check_each_neighbor
    action: parse
    input: "@ospf_output"
    for_each:
      var: neighbor
      in: "{{ expected_neighbors }}"
      stop_on_fail: true               # default — break on first iteration failure
      # mode: sequential              # default (concurrent reserved for future use)
    checks:
      - id: neighbor_full
        description: "Neighbor @neighbor is in FULL state"
        regex:
          default: '@neighbor\s+\d+\s+FULL'
        flags: mi
        expected_result: match
        on_fail: "OSPF neighbor @neighbor not in FULL state on @device."
```

For **object lists** (items with properties), dot-notation access on the loop
variable is supported:

```yaml
tasks:
  - id: check_each_interface
    action: scenario
    scenario: check_interface_up_up_with_ip_and_mask:1.0.0
    for_each:
      var: iface
      in: "{{ interfaces }}"
    params:
      interface_type: "@iface.type"
      ip_address: "@iface.ip"
      mask: "@iface.mask"
```

### Iteration Semantics

| Aspect | Rule |
|---|---|
| **Loop variable** | Runtime variable (`@var`), consistent with `@device`. Supports dot-notation for object properties (`@var.field`) |
| **Scope** | `@var` is scoped to the current iteration. Previous iteration values are not accessible |
| **Failure: `stop_on_fail`** | `for_each.stop_on_fail: true` (default) — break the loop on first iteration failure. Set to `false` to continue through all iterations and collect all failures |
| **Scoring** | Dichotomous per step (D14): ALL iterations across ALL devices must pass for the step to earn its points. ANY failure in any iteration → step earns 0 |
| **Empty list** | If `in` resolves to an empty list, the task is skipped — no failure emitted |
| **Execution mode** | `mode: sequential` (default) — iterations execute in list order. `mode: concurrent` is reserved for future use |

---

## Open Questions

- Define how scenario return data (`export` map) surfaces to callers beyond sub-scenario composition
- Define timeout, retry, and fallback strategies for `collect` tasks

---

_See also: [SPEC-002: Grading Execution Model](grading-execution-model.md) for invocation scripts, scoring, and the SE↔ROC orchestration protocol._
