# Pod Artifact Format — `PAv1`

> **Status**: Draft (Phase 0 of CPA↔SE Integration)
> **Authority**: [ADR-044 — Content-Driven Lifecycle Engine](../adr/ADR-044-content-driven-lifecycle-engine.md)
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
  content format (this document), not the execution model.
- **AD-CSI-002** — Pod-type discovery is deterministic and prioritised (see §3).
- **AD-CSI-004** — `PodDefinition` carries first-class typed fields extracted from the
  PAv1 tree (not just an opaque `manifest` blob).

---

## 2. Canonical zip layout

A `PAv1` archive is any zip file containing a top-level `PAv1/` directory:

```text
<package>.zip
└── PAv1/
    ├── manifest.yaml              # REQUIRED — version, pod_type, content_id, etc.
    ├── topology/                  # REQUIRED for engines that build infra
    │   ├── cml.yaml               # CML topology — XOR with radkit/proxmox/vmware
    │   ├── radkit.yaml            # OR a RADkit topology
    │   ├── proxmox.yaml           # OR a Proxmox topology
    │   ├── vmware.yaml            # OR a VMware topology
    │   └── devices.json           # OPTIONAL — device → connection map
    ├── lifecycle.yaml             # OPTIONAL — phase DAGs (instantiate, teardown, …)
    ├── scenarios/                 # OPTIONAL — content-defined scenarios
    │   ├── lab_resolve.v1.yaml
    │   ├── lab_start.v1.yaml
    │   └── ...
    ├── grading/                   # OPTIONAL — grading rubric(s)
    │   └── rubric.yaml
    ├── reports/                   # OPTIONAL — report templates
    │   └── summary.yaml
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
- `scenarios_used` — List of `name@version` strings referenced by `lifecycle.yaml`.
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

### 4.3 `lifecycle.yaml` — optional

Defines one or more **phases**. Each phase is a DAG of steps executed by the
CPA `PipelineExecutor` (in `lablet-controller`).

JSON Schema: [`schemas/lifecycle.schema.json`](./schemas/lifecycle.schema.json)

Top-level shape:

```yaml
phases:
  instantiate:
    steps:
      - name: lab_resolve
        handler: scenario_engine/lab_resolve@v1
        retry: { attempts: 3, backoff_seconds: 5 }
        timeout: { seconds: 120 }
      - name: ports_alloc
        handler: built_in/ports_alloc
        depends_on: [lab_resolve]
      - name: lab_start
        handler: scenario_engine/lab_start@v1
        depends_on: [ports_alloc]
        skip_when: "$session.skip_start == true"
  teardown:
    steps:
      - name: lab_wipe
        handler: scenario_engine/lab_wipe@v1
```

Per-step fields:

| Field         | Type                  | Required | Notes                                                                                      |
|---------------|-----------------------|---------:|--------------------------------------------------------------------------------------------|
| `name`        | string                | yes      | Unique within the phase.                                                                   |
| `handler`     | string                | yes      | Either `scenario_engine/<scenario>@<version>` (Tier-B) or `built_in/<handler>` (Tier-A).   |
| `depends_on`  | list[string]          | no       | Names of preceding steps; default empty.                                                   |
| `skip_when`   | string (expression)   | no       | `simpleeval` expression evaluated against the pipeline context.                            |
| `retry`       | object                | no       | `{ attempts: int, backoff_seconds: number }`.                                              |
| `timeout`     | object                | no       | `{ seconds: number }`.                                                                     |
| `inputs`      | object                | no       | Static or context-templated inputs forwarded to the handler.                               |

If a phase is **absent** in `lifecycle.yaml`, the `PipelineTemplateResolver` falls
back to the hardcoded Python template for that phase (preserves today's behaviour).

### 4.4 `scenarios/<name>.<version>.yaml` — optional

Content-defined scenarios that the SE loads alongside its Python `@scenario`
registry. The DSL inside a scenario file is SE's jq-flavoured DSL — `call`, `do`,
`set`, `try` (Phase 2). Additional task types (`for`, `fork`, `switch`, `wait`,
`emit`, `run`, `raise`, `listen`) are reserved for Phase 3+ and validated as
known keys.

JSON Schema: [`schemas/scenario.schema.json`](./schemas/scenario.schema.json)

Top-level shape:

```yaml
name: lab_resolve
version: v1
description: Resolve or create a lab on the target worker.
do:
  - resolve:
      call: cml.lab.resolve@v1
      with:
        topology: $context.topology
        worker_id: $input.worker_id
      output:
        as: { lab_id: .lab_id, lab_url: .url }
```

Each task object has **exactly one** primary key from the set `call / do / set /
try / for / fork / switch / wait / emit / run / raise / listen` plus optional
modifiers (`with`, `input`, `output`, `export`, `if`, `timeout`, `retry`, `then`).

**Open Q-04** (see plan §8): when both a content-defined `lab_resolve@v1` and a
Python `@scenario("lab_resolve", "v1")` exist, the content-defined one wins with
a warning log.

### 4.5 `grading/rubric.yaml`, `reports/summary.yaml`, `restore/restore.yaml` — optional

Reserved for Phase 5. Their schemas will be published as `grading.schema.json` /
`report.schema.json` / `restore.schema.json` once the scenarios that consume them
(`collect_grade@v1`, `score_report@v1`) land. Until then, the contents are
preserved verbatim on `PodDefinition.grading_rules` / `.reports` / `.restore_rules`.

---

## 5. Validation

`lcm_core.infrastructure.content_store.PAv1Validator` exposes three entry points:

- `validate_manifest(data: dict) -> None`
- `validate_lifecycle(data: dict) -> None`
- `validate_scenario(data: dict) -> None`

All raise `PAv1ValidationError(path, errors)` on failure, where `errors` is the
list of `jsonschema` validation messages.

Schemas are **vendored** under
`src/core/lcm_core/infrastructure/content_store/schemas/` so the runtime has no
dependency on the documentation tree. The copies in `docs/architecture/content-format/schemas/`
are illustrative; keep both in sync when amending.

---

## 6. Versioning

`format_version: PAv1` is a closed enum; any future breaking change ships as
`PAv2` with its own schema set. The validator refuses unknown `format_version`
values with an explicit diagnostic.

Non-breaking additions (new optional fields, additional task types) MAY land in
`PAv1` without a version bump; track them in the changelog at the top of each
`*.schema.json` file.

---

## 7. Cross-references

- [ADR-044](../adr/ADR-044-content-driven-lifecycle-engine.md) — Content-Driven Lifecycle Engine (authority)
- [CPA↔SE Integration Plan](../../implementation/cpa-se-integration-plan.md) — §5 PAv1/ spec, §6 phased delivery
- [`schemas/manifest.schema.json`](./schemas/manifest.schema.json)
- [`schemas/lifecycle.schema.json`](./schemas/lifecycle.schema.json)
- [`schemas/scenario.schema.json`](./schemas/scenario.schema.json)
