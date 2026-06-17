---
title: Glossary
---

# Glossary

> Canonical vocabulary for the whole platform. When a term here conflicts with an older doc,
> **this page wins**. Retired terms are listed at the bottom so you can map old material.

The platform is a **timed-resource management plane**: every operable thing is a
`TimedResource` with a declared _desired_ state and an observed _actual_ state, reconciled
continuously (Kubernetes-style). Concrete sessions, parts, pods, and hosts are all
specialisations of that one pattern. The terms below are grouped: **resource-model
primitives** (the pattern), **runtime resources** (the live tree), **definitions** (the
catalog that resources are instantiated from), then services, infra, and content.

## Resource-model primitives

| Term | Definition |
|---|---|
| **TimedResource** | The base abstraction for anything the platform provisions and tears down on a schedule. Carries a **spec/status** split (`desired_status` vs `status`), a `Timeslot`, a `ManagedLifecycle`, and a `state_history`. **Layer-2** specialisation of `ResourceInstance` that adds a `Timeslot`. `Session`, `SessionPart`, `PodInstance`, and `Host`/`Worker` are all TimedResources (see ADR-036, ADR-050). |
| **ResourceInstance** | **Layer-1** instance base: lifecycle + `desired_status` reconciliation, `owner_id`, children, **no `Timeslot` of its own** (inherits its parent's window). Every runtime resource is a `ResourceInstance`; **untimed** ones (`Job`, `Report`) stop here, **timed** ones become `TimedResource` (ADR-050). |
| **ResourceDefinition** | _Type metadata_ a resource is instantiated from: `type_key`, `version`, `provisioning_source`, optional `authorization_policy_id`, a **lifecycle template**, child **requirements/selectors**, `definition_status`, and (for synced content) `sync_status`. Definitions are the **catalogue**; they do not reconcile against infrastructure (ADR-050). |
| **provisioning_source** | Where a definition comes from \u2014 `seed` (static config loaded by a seeder, **no** lifecycle) or `content_package` (synced from a PAv1 package, with a `draft → published → deprecated` lifecycle + `sync_status`). The one asymmetry in the definition model (ADR-051). |
| **ResourceState** | Layer-1 base state (K8s-like): `id, resource_type, status, desired_status, owner_id, state_history, pipeline_progress`. Records transitions via `_record_transition()`. The state held by a `ResourceInstance`. |
| **TimedResourceState** | Layer-2 base state: adds `timeslot`, `lifecycle`, `started_at/ended_at/duration`. Stored as dicts; accessed as value objects. The state held by a `TimedResource`. |
| **desired_status / status** | The **declared intent** vs the **observed reality** of a resource. Operators and parents set `desired_status`; reconcilers drive `status` toward it. Intent cascades **down** the tree; status bubbles **up**. |
| **Timeslot** | Value object: `start, end, lead_time, teardown_buffer` → computed `provision_at`, `cleanup_deadline`, `duration`. `lead_time` is what distinguishes **JIT** provisioning (short lead, e.g. CML) from **eager** provisioning (long lead / pre-booked, e.g. hardware appliances). |
| **ManagedLifecycle** | Value object: an ordered tuple of `LifecyclePhase` plus the `current_phase`. Each resource type defines its own phase sequence. |
| **LifecyclePhase** | A named stage with an `engine` (`pipeline` = native LCM steps, or `workflow` = SE job), a `trigger_on_status`, and required/optional flag. The binding point between a resource's lifecycle and **automation**. |
| **StateTransition** | An immutable entry in `state_history`: `from_status → to_status`, timestamp, reason, actor. |
| **Reconciliation** | The control loop `observe → diff(desired, actual) → act → record`. Implemented once as a **generic framework** and specialised by a **per-type manager** for each resource kind (see ADR-047). |
| **Per-type manager** | The component that knows how to reconcile one resource kind (e.g. the Session manager in CPA, the Pod/Host managers in the controllers). Registered against the generic reconcile loop. |

## Runtime resources (the tree)

The live resource tree. Intent flows down, status flows up; each node has its own `Timeslot`
and `ManagedLifecycle`.

```text
Session ─┬─ SessionPart ─┬─ PodInstance ─→ (binds) ─→ Host / Worker
         │               └─ PodInstance
         └─ SessionPart ─── PodInstance
```

| Term | Owner | Definition |
|---|---|---|
| **Session** | CPA | The top-level delivery instance, instantiated from a `SessionDefinition` (`session_type`). Has a **simple, timeslot-derived lifecycle** `pending → active → inactive` and owns part **ordering and gating**. A single-part session (`LabletSession`) is the simplest case. |
| **SessionPart** | CPA | A first-class `TimedResource` for one part of a session (e.g. an exam's DES / DOO / AI-DOO parts). Has its own timeslot (**contained** within the session's), a **rich content-driven lifecycle** (`pending → instantiating → waiting → monitoring → collecting → grading → reviewing → submitting → archiving`, defined in the PAv1 package), and 0..N pods. Parts are **sequential and gated**; a later part's pod may provision early to cover eager lead time. |
| **PodInstance** | pod-controller | The concrete running environment for a part, instantiated from a `PodDefinition`. A `TimedResource` of a given **`PodType`** (workload), bound to a `Host` of a given **`HostType`** (platform). `LabRecord` is the `cml_on_aws` variant. |
| **Host / Worker** | host-controller (+ adapters) | A generic infrastructure host `TimedResource` that pods bind to, with a per-platform **adapter**. The generalized `CmlWorker` (EC2 running CML = the `cml_on_aws` variant). |
| **LabletSession** | CPA | **Profile**: a `Session` with exactly one part and one `cml_on_aws` pod. The classic single-lab delivery. |
| **LabRecord** | controllers | **Profile**: the `cml_on_aws` `PodInstance` — a CML lab on an EC2 worker. |
| **PodType** | — | The **workload** axis — _what the pod is_, for pods LCM **provisions**: `cml_on_aws`, `proxmox`, `vmware`. (`roc_radkit` is **not** a PodType — see _ROC / RADkit_.) |
| **HostType** | — | The **platform** axis — _where the pod runs_: `cml_on_aws`, `vmware`, `proxmox`, `native_aws`, `hybrid_hardware`. Split from `PodType` because workload and platform are not the same axis (see ADR-046). |

!!! note "Deferred — `Device` / `DeviceDefinition` (out of scope this round)"
    A first-class **`Device`** runtime resource (and its `DeviceDefinition`) is **deferred**
    (ADR-050 §2.3). Today, **device-based parts** target **pre-existing** devices reached via
    **ROC / RADkit** — they provision **no** `PodInstance` and add no new resource kind. When a
    managed device resource is introduced, it will slot in as another `TimedResource` /
    `ResourceDefinition` pair without changing the pattern.

## Automation (SE)

| Term | Owner | Definition |
|---|---|---|
| **Job** | SE | A single execution of a `JobDefinition` bound to a part's lifecycle phase. The runtime instance of automation — an **untimed `ResourceInstance`** (lifecycle + `desired_status`, no `Timeslot`; inherits the part's window). |
| **JobDefinition** | SE | A named, versioned recipe (`name@version`) describing **what** automation to run for a phase: an **ordered DAG of steps**, each calling a `scenarioFunction`. The **content-defined** layer — authors and LLMs write this declaratively, never code. A `content_package` `ResourceDefinition` referenced from `lifecycle.yaml` and stored in `PAv1/jobs/<name>.yaml` (ADR-057 §2.1). |
| **scenarioFunction** | SE | A **code-defined, versioned, trusted primitive** in the SE registry — an `@scenario(name, version)` class. The set is **closed and orthogonal** (`pause@v1`, `exec@v1`, `copy@v1`, `cml.*@v1`, `collect@v1`, `evaluate.regex@v1`, `report.*@v1`, …). A step's `uses:` names one. Adding one is a code PR + version bump (ADR-057 §2.2). |
| **primitive** | SE | Synonym for a `scenarioFunction` — the smallest reusable unit of work content can invoke. The platform ships one **closed set**; content cannot define new primitives. |
| **CompositeScenario** _(deferred)_ | SE | A **content-defined, parameterised** group of _closed primitives_ (typed `parameters` in, `export` out) callable from any step via `uses: composite:<name>@<ver>` — **indistinguishable from a primitive at the call site**, run in an isolated `vars.*` frame. Pure wiring, never code; the reuse/DRY answer to the flat-DAG model. **Specified but not built** (Model C hybrid) — see ADR-057 §2.8 / ADR-058 §2.5. Distinct from `scenarioFunction` (which is _code_). |
| **for_each** _(deferred)_ | SE | A step/composite **modifier** that runs the step once per element of a list, binding a loop `var` into `vars.*` (dot-notation for object lists). Collapses per-device step duplication. Specified in ADR-057 §2.8 (from SPEC-001 D18); not yet built. |
| **Step** | SE | One node in a `JobDefinition`'s DAG: `{ id, uses, target, with, capture, when, on_error, timeout, stage }`. `uses` selects a `scenarioFunction@version`; `target` selects a connector; `capture` writes outputs into `vars.*` (ADR-057 §2.4). |
| **stage** | SE | A **soft grouping** of steps within a job: `setup` (seed/wipe/run-solution), `collect`, `evaluate`, `report`. Not a rigid template — just metadata that, with the `process_type`, picks which report is assembled. |
| **native step** | CPA / controllers | A **resource-lifecycle** action owned by LCM (e.g. `worker_lab_resolve`, `ports_alloc`, `mark_ready`) — distinct from a `scenarioFunction`. Listed in a phase's `native_steps_by_pod_type`. See _Native LCM steps vs SE jobs_ below. |
| **Report** | SE | The output artifact of a `Job` (readiness / score / change report). An **untimed `ResourceInstance`** created from a `ReportDefinition`. |
| **ReportDefinition** | SE | A `content_package` `ResourceDefinition` describing a report's shape/ruleset. |
| **ScenarioDefinition** | SE | The **Collect** specification inside a job: which devices, which commands, what to capture. |
| **EvaluationRuleset** | SE | The **Evaluate** specification: graded items, checks (parse/regex/comparison), and points. Derived from the author's grading rules. |
| **ProcessReport** | SE | The **Report** output of a job: a readiness report, score report, change report, etc. |
| **Process type** | SE | The intent of a job run: `Initialization`, `Grading`, `Change`, `Submission`, `Archive`. Each maps to a report kind. |

### Data-flow scopes

Every value a step reads or writes lives in one of **four namespaced scopes** (ADR-058).
References are **jq expressions in `${ }`**.

| Scope | Writable? | Holds |
|---|---|---|
| **`session.*`** | read-only | Candidate / exam / timeslot metadata (from `mosaic_meta.json` + `Session`). |
| **`content.*`** | read-only | Lab-root path, packaged files, form FQN (from the PAv1 package). |
| **`runtime_env.*`** | read-only | POD facts resolved at submit: device ports, prompts, credentials, `cml_password`, worker IP. **Secrets and ports are never literal in content** — they resolve here. |
| **`vars.*`** | **read/write** | Task-captured intermediates written by `step.capture` (e.g. `vars.<step_id>.<name>`). |

## Services

| Service | Role |
|---|---|
| **CPA** (`control-plane-api`) | Single entry point (API + UI). **Session manager**: catalog, sessions, phase ordering, native infra steps. SSOT for catalog = Mosaic. |
| **lablet-controller** | _As-built_ CPA reconciler/worker: content-sync ingester + lifecycle step executor. **Split by [ADR-054](../adr/ADR-054-controller-topology-resource-kind.md) Rev 2** into `session-`/`form-`/`pod-controller`. |
| **resource-scheduler** | Timeslot booking and host/pod allocation. |
| **worker-controller** | _As-built_ EC2 + CML worker provisioning and lifecycle. **Renamed/generalized to `host-controller`** by [ADR-054](../adr/ADR-054-controller-topology-resource-kind.md) Rev 2. |
| **session-controller** _(ADR-054 target)_ | Reconciles `Session` + `SessionPart` (ordering, gating). |
| **form-controller** _(ADR-054 / [ADR-059](../adr/ADR-059-form-as-first-class-synced-resource.md) target)_ | Owns the `Form` **sync** loop: Mosaic → RustFS → LDS + SE fan-out. |
| **pod-controller** _(ADR-054 target)_ | Reconciles `PodInstance` (any `PodType` workload). |
| **host-controller** _(ADR-054 target)_ | Reconciles `Host` (any `HostType` platform) via per-platform adapters; the generalized `CmlWorker`. |
| **SE** (`scenario-engine`) | **Automation engine**: jobs, scenarios, grading, reports. Runs Collect→Evaluate→Report. SSOT for content = blob storage. |
| **ROC / RADkit** | Existing device-access service for live interaction with **pre-existing** devices (any device exposing a text interface). A **collection / execution transport**, _not_ a provisioned resource: SE delegates raw _Collect_ and command-bulk execution to it. A device-based part has **no** `PodInstance` — it is reached via ROC/RADkit. |
| **LDS** | Lab Delivery System — student-facing access (ports, content view). Keeps its own synced view of content. |

## Definitions (the catalog)

What resources are instantiated _from_. Definitions are **content-driven** and shipped in
seed content; runtime resources are created from them at schedule time.

| Term | Owner | Definition |
|---|---|---|
| **SessionDefinition** | CPA | The umbrella catalog entry, identified by a **`session_type`** (not universally an FQN). Declares `session_parts: list[PartDefinition]`, a **session lifecycle**, and metadata. **Single-part** types (`lablet`, `practicelab`) are addressed by **FQN**; **multi-part** types (`expertlab` = CCIE / 2 parts, `expertdesign` = CCDE / 4 parts) by **`session_type`**, each part selecting a separate `Form` by **pattern + requirements**. A `lablet` is just the single-part case. |
| **session_type** | — | The stable identity/template of a `SessionDefinition` (`lablet`, `practicelab`, `expertlab` = CCIE, `expertdesign` = CCDE, …). Selects the **session lifecycle** and how the session is addressed (FQN for single-part, `session_type` for multi-part). |
| **PartDefinition** | CPA | One entry in `SessionDefinition.session_parts`. Selects a **`Form`** via a **selector pattern** on form-qualified name (e.g. `"Exam CCIE * * DES*"`, `"* CCDE * COR"`) plus optional **`requirements`** (declarative filters), resolved at schedule time. The resolved **`Form`** carries the optional `PodDefinition` ref (ADR-059) and the part declares the **part lifecycle** (from the PAv1 package). |
| **PodDefinition** | CPA | The **canonical pod spec** — declares a pod's `PodType`, target `HostType`, topology, and synced-content pointer. Reinstated as a first-class definition (see ADR-046). `PodInstance`s are created from it. Referenced by the `Form`, not the part (ADR-059). |
| **LabletDefinition** _(retired)_ | — | **Generalised into `Form`** ([ADR-059](../adr/ADR-059-form-as-first-class-synced-resource.md)). Was: a single-part synced catalogue entry. A Lablet is now just a single-part session whose one `Form` references a `cml_on_aws` `PodDefinition`. |
| **form-qualified name** | — | The stable key (e.g. `LAB-1.1.1`) and selector vocabulary used to resolve definitions, content, and environment. |

## Content-authoring taxonomy & catalogue

The authored-content definitions (`provisioning_source = content_package`) and static reference
data (`provisioning_source = seed`) generalised from the legacy _Track / Session / Pod_ managers.
See [definition-catalog-model.md](definition-catalog-model.md).

| Term | Source | Definition |
|---|---|---|
| **Track** | content_package | A certification line (e.g. _Exam CCIE DEMO_). Owns the canonical item catalogue and one or more versioned exams. |
| **TrackItem** | content_package | A canonical, auto-numbered catalogue entry — the stable task/question a `FormItem` realises. |
| **Exam** | content_package | A versioned realisation of a track with a publication lifecycle (`Draft → Released → Retired`). |
| **Blueprint / BlueprintNode** | content_package | The weighted topic taxonomy an exam is measured against — a revisioned, self-referential tree. |
| **Module** | content_package | A section of an exam (a lab or written section). Groups formsets. |
| **Formset** | content_package | A versioned family of forms (e.g. _DOO-1.x_). |
| **Form** | content_package | A concrete deliverable version (e.g. _DOO 1.1_) — the **single synced** `content_package` resource ([ADR-059](../adr/ADR-059-form-as-first-class-synced-resource.md)): owns `sync_status`, synced bytes, and an **optional `PodDefinition` ref**. Generalises `LabletDefinition`. **Delivered** by a `SessionPart` by FQN — **no timed instance**. |
| **FormItem** | content_package | An item as placed on a form: references its `TrackItem`, carries placement + type-driven scoring, tagged with `BlueprintNode`s. |
| **FQN (Form Qualified Name)** | — | The six-token path through the taxonomy (`{Type} {Level} {Acronym} v{version} {module} {form}`) that a `PartDefinition` selects by pattern. |
| **DeliveryEnvironment** | seed | Catalogue/config: which session types are deliverable in an environment. |
| **LabLocation** | seed | Catalogue/config: a logical lab location (capacity / placement target). |
| **HostingSiteLocation** | seed | Catalogue/config: a physical hosting site / rack a host belongs to. |
| **AuthorizationPolicy** | seed | A named, reusable guard referenced by any definition/resource via `authorization_policy_id`. Composed of `AuthorizationRequirement`s. |
| **AuthorizationRequirement** | — | One guard rule: a **Claim** (`claim_type` + optional JQ-evaluated `claim_value`) or a **Composite** (`All`/`Any` over nested requirements). Filters results per-user; **admin bypasses** (ADR-053). |

## Infrastructure & external systems

| Term | Definition |
|---|---|
| **Mosaic** | External content authoring/publishing system. **CPA's source of truth** for the catalog. Resolved dynamically per Lablet via the form-environment-resolver. |
| **Form-environment-resolver** | Service that maps a **form-qualified name** → a set of environment variables (including the `MOSAIC_BASE_URL`) for that content. |
| **RustFS / S3** | Internal shared **blob storage** (S3-compatible). Holds the canonical bytes of synced content. **SE's source of truth** for content. |
| **etcd** | Watch/coordination store used between CPA and lablet-controller for reconciliation. |
| **CloudEvents** | The event envelope for cross-service integration (e.g. SE → CPA job results). |
| **Keycloak** | OAuth2/OIDC identity provider for both UI (cookie/BFF) and API (JWT). |

## Content packages

| Term | Definition |
|---|---|
| **PAv1** | **Pod-Automation v1** — the canonical content package format. Contains everything CPA, SE, and ROC need: `manifest.yaml`, `lifecycle.yaml`, topology, scenarios, grading, reports. Authors ship this. |
| **RCUv1** | The **legacy** content format (XML grading rules, scriptblocks, `devices.json`, `cml.yaml`). May coexist with `PAv1/` but is not auto-converted — authors supply each format explicitly. |
| **Lifecycle phase** | A named stage in a resource's `ManagedLifecycle` (`instantiate`, `ready`, `grade`, …). A phase binds to a **native LCM step** (pipeline engine) and/or an **SE JobDefinition** (workflow engine). |

## Native LCM steps vs SE jobs

The line between the two engines. Native steps are **resource-lifecycle** plumbing owned by
LCM; SE jobs are **content-driven automation** — any job run (collect / evaluate / report) of
any step (`sync` / `init` / `collect` / `grade` / `archive` / …).

| Native LCM step (CPA / controllers) | SE job (content-driven automation) |
|---|---|
| `worker_lab_resolve` | `lab_resolve` / `lab_start` / `lab_stop` / `lab_wipe` |
| `pod_locator` | `collect_evidence` |
| `ports_alloc` | `grade_item` |
| `lds_register` | `score_report` |
| `mark_ready` | generate reports (readiness / change / archive) |
| `archive`, `schedule` | |

## Retired terms

| Retired | Use instead | Note |
|---|---|---|
| **"thin/stateless SE"** | SE as **stateful automation engine** | SE owns its jobs, scenarios, grading, and reports. |
| **"SE owns the session"** | CPA owns `Session`; SE owns `Job` | Session vs Job split is firm. |
| **Pod (as a vague runtime term)** | `PodInstance` (runtime) + `PodDefinition` (spec) | The spec/runtime split is now explicit; `PodDefinition` is **un-retired** as the canonical pod spec. |
| **LabletDefinition** | `Form` (synced resource) | The single-part synced catalogue entry is generalised into the `Form` ([ADR-059](../adr/ADR-059-form-as-first-class-synced-resource.md)); a Lablet is a single-part session. |
| **content-controller** | `form-controller` | The content-sync owner is the `form-controller` ([ADR-054](../adr/ADR-054-controller-topology-resource-kind.md) Rev 2) — the `Form` is the synced unit. |
