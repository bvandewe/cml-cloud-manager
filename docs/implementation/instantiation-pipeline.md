# Instantiation Pipeline — Architecture & Implementation Plan

**Status**: ✅ Complete — All 7 phases delivered (2026-03-02)
**Created**: 2026-03-01
**Author**: AI Architect (lcm-senior-architect)
**ADR**: ADR-031 (Checkpoint-Based Instantiation Pipeline)
**Depends On**: ADR-020 (Session Consolidation), ADR-029 (Port Template), ADR-030 (Resource Observation), AD-DRAIN-001 (Watch Drain-Loop Fix)
**Scope**: Cross-service refactor of LabletSession instantiation lifecycle (lablet-controller, control-plane-api, resource-scheduler, worker-controller, lcm-core)

---

## Executive Summary

The current `_handle_instantiating()` in `lablet_reconciler.py` is a **monolithic waterfall** — a single async method that sequentially performs lab resolution, lab import, lab start, LDS provisioning, device mapping, and READY transition. If any step fails, the entire instantiation restarts from zero. There is no checkpoint tracking, no partial recovery, and no visibility into progress.

This document designs a **checkpoint-based instantiation pipeline** — a dependency-ordered sequence of idempotent, resumable steps where progress is persisted to the LabletSession aggregate after each step. Combined with the drain-loop fix (AD-DRAIN-001), this ensures that self-induced watch events from each step's API call are processed in the same reconciliation cycle, enabling reliable multi-step state advancement.

### Key Design Principles

1. **Step dependencies form a DAG, not a flat list** — `lab_binding` requires `tags_sync`, which requires `ports_alloc`, which requires `lab_resolve`. Steps declare their prerequisites explicitly.
2. **Ports are a LabRecord topology concern** — ports are allocated to a **LabRecord** when it is created/imported, and stored as `allocated_ports` on the LabRecord aggregate. They are part of the topology graph (nodes, edges, tags) and persist across start/stop/wipe. LabRunRecord tracks _runtime_ (start/stop/duration) but does NOT own ports. The LabletSession gets a denormalized copy via binding.
3. **CML node tags must be synced with allocated ports** — after allocating real port numbers, the `tags_sync` step writes them back to CML node tags via `PATCH /api/v0/labs/{lab_id}/nodes/{node_id}`. Tags encode `protocol:port` pairs and are consumed by CML for port-forwarding when the lab starts. Stop/wipe do NOT modify tags.
4. **Timeslot-centric lifecycle** — a LabletSession maps 1:1 to a timeslot. The timeslot can be extended/started/stopped/cancelled. Expired session sync triggers downstream cleanup (UserSession terminated, LabRecord unbound, reports published).
5. **Option A (inline) for now** — pipeline steps are inline methods in the reconciler. Future: configurable per LabletDefinition.

### User Requirements Addressed

| # | Requirement | Section |
|---|------------|---------|
| 1 | Port allocation at LabRecord creation (not scheduling), scheduler only considers availability | §3 |
| 2 | LabRecord as port owner; CML node tags synced with allocated ports | §3, §4 |
| 3 | Lab binding after lab resolution and tag sync; LabRunRecord tracks runtime only | §4 |
| 4 | Variables as placeholder step | §5 |
| 5 | Content sync as fail-fast prerequisite | §6 |
| 6 | Timeslot-centric lifecycle with downstream cleanup | §7 |
| 7 | Cross-service refactor (all 4 services) | §9 |
| 8 | Fix drain-loop first, then design pipeline | §1, §2 |

---

## Table of Contents

1. [Prerequisites & Low-Hanging Fruit](#1-prerequisites--low-hanging-fruit)
2. [Pipeline Architecture](#2-pipeline-architecture)
3. [Port Allocation — LabRecord-Level Concern](#3-port-allocation--labrecord-level-concern)
4. [Lab Binding & LabRunRecord](#4-lab-binding--labrunrecord)
5. [Variables Step](#5-variables-step)
6. [Content Sync Prerequisite](#6-content-sync-prerequisite)
7. [Timeslot Lifecycle & Downstream Cleanup](#7-timeslot-lifecycle--downstream-cleanup)
8. [Pipeline UI (Phase 5)](#8-pipeline-ui-phase-5)
9. [Cross-Service Implementation Plan](#9-cross-service-implementation-plan)
10. [Migration & Backward Compatibility](#10-migration--backward-compatibility)

---

## 1. Prerequisites & Low-Hanging Fruit

### 1.1 Drain-Loop Fix (AD-DRAIN-001) ✅ DONE

**Problem**: In watch-only mode (polling disabled), when `_handle_instantiating()` makes an API call that changes session state (e.g., SCHEDULED → INSTANTIATING), the resulting etcd watch event arrives during execution. The old `_debounced_reconcile()` checked `if not self._pending_reconciles: return` — discarding the self-induced event. The session would be stuck until the next polling cycle (disabled in production).

**Fix**: Replaced single-pass drain with `while self._pending_reconciles:` drain loop in `WatchTriggeredHostedService._debounced_reconcile()`. Self-induced events are now re-drained and processed within the same debounce cycle.

**Status**: ✅ Implemented, 10 tests passing, all 103 core tests green.

### 1.2 Why Checkpoint-Based Design

The drain-loop fix enables multi-step advancement per reconciliation cycle. Combined with checkpoint persistence, each step becomes:

```
reconcile(session) →
  read checkpoint →
  skip completed steps →
  execute next step →
  persist checkpoint →
  return requeue →
  [drain-loop picks up self-induced event] →
  reconcile(session) →
  read checkpoint →
  skip completed steps →
  execute next step →
  ...until READY
```

This gives us **resilience** (restart from last checkpoint), **visibility** (frontend can show step progress), and **flexibility** (pipeline steps can be customized per LabletDefinition).

---

## 2. Pipeline Architecture

### 2.1 Step Dependency Graph

The pipeline is **not a flat list** — steps have explicit prerequisites. The reconciler evaluates which step to execute next by checking whether all prerequisites are satisfied (completed or skipped).

```
                    INSTANTIATING entered
                           │
              ┌────────────┼────────────┐
              ▼            ▼            │
        ┌───────────┐ ┌──────────┐     │
        │content_sync│ │variables │     │
        │ §6         │ │ §5       │     │
        └─────┬─────┘ └────┬─────┘     │
              │             │           │
              └──────┬──────┘           │
                     ▼                  │
              ┌─────────────┐           │
              │ lab_resolve  │           │
              │ reuse/import │           │
              └──────┬──────┘           │
                     ▼                  │
              ┌─────────────┐           │
              │ ports_alloc  │ §3       │
              │ allocate on  │           │
              │ LabRecord    │           │
              └──────┬──────┘           │
                     ▼                  │
              ┌─────────────┐           │
              │ tags_sync    │ §3       │
              │ write tags   │           │
              │ to CML nodes │           │
              └──────┬──────┘           │
                     ▼                  │
              ┌─────────────┐           │
              │ lab_binding  │ §4       │
              │ bind record  │           │
              │ to session   │           │
              └──────┬──────┘           │
                     ▼                  │
              ┌─────────────┐           │
              │ lab_start    │           │
              │ CML start    │           │
              │ → BOOTED     │           │
              └──────┬──────┘           │
                     ▼                  │
              ┌──────────────┐          │
              │ lds_provision │          │
              │ LDS session   │          │
              │ + device map  │          │
              └──────┬───────┘          │
                     ▼                  │
              ┌─────────────┐           │
              │ mark_ready   │           │
              └─────────────┘           │
```

### 2.2 Step Definitions with Prerequisites

| Step | Prerequisites | Gate Condition | Action | Skip Condition |
|------|--------------|----------------|--------|----------------|
| `content_sync` | — (root) | Definition exists | Verify `sync_status == "synced"` | `content_sync_enabled == False` |
| `variables` | — (root) | Definition exists | Resolve variables from definition defaults | No variables defined (placeholder) |
| `lab_resolve` | `content_sync`, `variables` | Topology YAML available | Find reusable lab or import fresh → yields `cml_lab_id` | — |
| `ports_alloc` | `lab_resolve` | `cml_lab_id` resolved, `port_template` exists | Allocate ports from worker pool via `PortAllocationService` → stored on **LabRecord** | No `port_template` on definition |
| `tags_sync` | `ports_alloc` | Ports allocated (or skipped) | Write allocated port numbers to CML node tags via `PATCH` API | No `port_template` (no ports to sync) |
| `lab_binding` | `lab_resolve`, `tags_sync` | Lab resolved, tags synced (or skipped) | Bind LabRecord to session, create LabRunRecord | — |
| `lab_start` | `lab_binding` | LabRecord bound to session | Start CML lab, poll until BOOTED | Lab already BOOTED (reuse case) |
| `lds_provision` | `lab_start` | Lab BOOTED | Create LDS session, map devices, get launch URL | No `form_qualified_name` (no LDS) |
| `mark_ready` | `lds_provision` | LDS provisioned (or skipped) | Atomic transition to READY | — (always runs) |

### 2.3 InstantiationProgress Model

A new `instantiation_progress` field on `LabletSessionState` tracks pipeline state:

```python
# domain/value_objects/instantiation_progress.py (NEW — control-plane-api)

@dataclass
class StepResult:
    """Result of a single pipeline step."""
    step: str                        # Step name (e.g., "content_sync", "ports_alloc")
    status: str                      # "pending" | "completed" | "failed" | "skipped"
    requires: list[str]              # Prerequisite step names
    completed_at: datetime | None    # When step completed
    result_data: dict | None         # Step-specific evidence (e.g., {"cml_lab_id": "..."})
    error: str | None                # Error message if failed
    attempt_count: int               # Number of attempts (for retry tracking)

@dataclass
class InstantiationProgress:
    """Tracks the instantiation pipeline state."""
    steps: list[StepResult]          # All step results (dependency-ordered)
    started_at: datetime             # When pipeline started
    current_step: str | None         # Currently executing step
    completed_at: datetime | None    # When pipeline completed (all steps done)
    pipeline_version: str            # Pipeline definition version (for migration)

    @property
    def is_complete(self) -> bool:
        return all(s.status in ("completed", "skipped") for s in self.steps)

    def next_executable_step(self) -> StepResult | None:
        """Find next step whose prerequisites are all satisfied."""
        completed = {s.step for s in self.steps if s.status in ("completed", "skipped")}
        for step in self.steps:
            if step.status == "pending" and all(r in completed for r in step.requires):
                return step
        return None

    def get_step(self, name: str) -> StepResult | None:
        return next((s for s in self.steps if s.step == name), None)

    def complete_step(self, name: str, result_data: dict | None = None) -> None:
        step = self.get_step(name)
        if step:
            step.status = "completed"
            step.completed_at = datetime.now(timezone.utc)
            step.result_data = result_data
            step.attempt_count += 1

    def fail_step(self, name: str, error: str) -> None:
        step = self.get_step(name)
        if step:
            step.status = "failed"
            step.error = error
            step.attempt_count += 1
```

The `next_executable_step()` method is the key difference from v1 — instead of iterating a flat list, it checks the dependency graph to find the next step whose prerequisites are all satisfied.

### 2.4 Default Pipeline Factory

```python
def build_default_pipeline(definition: LabletDefinitionReadModel) -> InstantiationProgress:
    """Build the default pipeline for a definition.

    Future: LabletDefinition can override steps / skip conditions.
    """
    has_ports = bool(definition.port_template)
    return InstantiationProgress(
        steps=[
            StepResult(step="content_sync", requires=[],
                       status="skipped" if not definition.content_sync_enabled else "pending"),
            StepResult(step="variables", requires=[], status="skipped"),  # placeholder
            StepResult(step="lab_resolve", requires=["content_sync", "variables"], status="pending"),
            StepResult(step="ports_alloc", requires=["lab_resolve"],
                       status="skipped" if not has_ports else "pending"),
            StepResult(step="tags_sync", requires=["ports_alloc"],
                       status="skipped" if not has_ports else "pending"),
            StepResult(step="lab_binding", requires=["lab_resolve", "tags_sync"], status="pending"),
            StepResult(step="lab_start", requires=["lab_binding"], status="pending"),
            StepResult(step="lds_provision", requires=["lab_start"],
                       status="skipped" if not definition.form_qualified_name else "pending"),
            StepResult(step="mark_ready", requires=["lds_provision"], status="pending"),
        ],
        started_at=datetime.now(timezone.utc),
        current_step=None,
        completed_at=None,
        pipeline_version="1.0",
    )
```

### 2.5 Domain Event: InstantiationProgressUpdated

```python
# domain/events/lablet_session_events.py (MODIFY)

@dataclass
class LabletSessionInstantiationProgressUpdatedDomainEvent(LabletSessionDomainEventBase):
    """Published when a pipeline step completes."""
    type: str = "com.cisco.lcm.lablet-session.instantiation-progress-updated.v1"
    step_name: str = ""
    step_status: str = ""  # "completed" | "failed" | "skipped"
    progress_data: dict = field(default_factory=dict)
```

### 2.6 New CPA Internal Endpoint

```python
# api/controllers/internal/lablet_session_internal_controller.py (MODIFY)

# POST /api/internal/lablet-sessions/{session_id}/instantiation-progress
# Body: { "step_name": "ports_alloc", "step_status": "completed", "result_data": {...} }
# Called by: lablet-controller after each pipeline step
```

### 2.7 Reconciler Integration (Option A — Inline)

```python
# lablet_reconciler.py — _handle_instantiating (revised)

async def _handle_instantiating(self, instance: LabletSessionReadModel) -> ReconciliationResult:
    """Handle INSTANTIATING — execute next pipeline step."""
    # Build or resume progress
    progress = self._parse_progress(instance) or self._build_default_progress(instance)

    if progress.is_complete:
        return ReconciliationResult.success()

    # Find next executable step (prerequisites satisfied)
    next_step = progress.next_executable_step()
    if not next_step:
        # All pending steps have unsatisfied prerequisites — likely a failed dependency
        failed = [s for s in progress.steps if s.status == "failed"]
        if failed:
            return ReconciliationResult.failed(
                f"Pipeline blocked: {failed[0].step} failed — {failed[0].error}"
            )
        return ReconciliationResult.requeue("Waiting for prerequisites")

    # Dispatch to step handler
    handler = getattr(self, f"_step_{next_step.step}", None)
    if not handler:
        return ReconciliationResult.failed(f"Unknown pipeline step: {next_step.step}")

    try:
        result = await handler(instance, progress)
    except Exception as e:
        result = StepResult(step=next_step.step, status="failed", error=str(e))

    # Persist progress to CPA
    await self._api.update_instantiation_progress(
        session_id=instance.id,
        step_name=result.step,
        step_status=result.status,
        result_data=result.result_data,
        error=result.error,
    )

    if result.status == "failed":
        return ReconciliationResult.requeue(f"Step {result.step} failed: {result.error}")

    return ReconciliationResult.requeue(f"Step {result.step} {result.status}")
```

The step handler naming convention `_step_{step_name}` means adding `tags_sync` simply requires adding a `_step_tags_sync(self, instance, progress)` method to the reconciler. No dispatch map changes needed.

---

## 3. Port Allocation & Tag Sync — LabRecord Topology Concern

### 3.1 Fundamental Insight

Ports are **not a LabletSession concern** and **not a LabRunRecord concern** — they are a **LabRecord topology concern**. CML node tags encode `protocol:port` pairs that are part of the lab graph (nodes, edges, tags). Tags persist across start/stop/wipe cycles — they are set once when the lab is created/imported and only updated when ports are re-allocated.

**Port lifecycle**:

1. **LabRecord created/imported** → ports allocated from worker pool → stored as `LabRecord.allocated_ports`
2. **Tags synced to CML nodes** → `PATCH /api/v0/labs/{lab_id}/nodes/{node_id}` writes `["protocol:port", ...]`
3. **Lab started** → CML reads tags for port-forwarding → ports are active
4. **Lab stopped / wiped** → tags **unchanged** (topology-level, persist)
5. **Lab reused** (next session) → same LabRecord, same ports, same tags → **no re-allocation**
6. **LabRecord deleted** → ports released from etcd → available for reuse

### 3.2 Current State (Problems)

| Component | Current Behavior | Problem |
|-----------|-----------------|---------|
| **resource-scheduler** `_handle_assign()` | Builds `allocated_ports` from static `port_template.port_entries` | Static template values ≠ dynamically allocated ports |
| **resource-scheduler** `PlacementEngine` | Only **counts** available ports (filter: need N, have M) | ✅ Correct — this is scheduling, not allocation |
| **control-plane-api** `PortAllocationService` | Full etcd-based allocation with atomic guarantees | **Exists but never called during scheduling!** |
| **LabletSession.allocated_ports** | Stores whatever dict is passed at schedule time | Stores static template values; should be denormalized from LabRecord |
| **LabRunRecord** | Has `lablet_session_id` but no port mapping | ✅ Correct — LabRunRecord tracks runtime (start/stop/duration), not topology |
| **CML node tags** | Contain placeholder port numbers from YAML authoring time | **Never updated with allocated ports** — critical gap |
| **CML SPI client** | Only reads nodes | **No `PATCH` node endpoint** — cannot write tags |
| **Lab discovery** | Discovers labs, extracts `ExternalInterface` VOs | No port allocation tracking for non-session labs |

### 3.3 Port Ownership Model

```
                              ┌─────────────────────┐
                              │   LabletDefinition   │
                              │   port_template:     │
                              │     [{name, protocol}]│
                              └──────────┬──────────┘
                                         │ "what ports are needed"
                                         ▼
                              ┌─────────────────────┐
                              │ PortAllocationService│
                              │ (etcd-backed, atomic)│
                              │ allocate(worker,     │
                              │   lab_record_id,     │
                              │   port_template)     │
                              │ → {name: port_num}   │
                              └──────────┬──────────┘
                                         │ "actual port numbers"
                                         ▼
                              ┌─────────────────────┐
                              │   LabRecord          │
                              │   allocated_ports:   │◄── canonical owner
                              │     {name: port_num} │
                              │   external_interfaces│◄── derived from allocated_ports
                              └──────────┬──────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    │                    ▼
          ┌─────────────────┐            │          ┌─────────────────┐
          │   CML Nodes     │            │          │ LabletSession   │
          │   tags: [       │            │          │ allocated_ports: │◄── denormalized
          │     "serial:3001│            │          │   (from LabRecord)│    copy via
          │     "vnc:3002"  │            │          └─────────────────┘    binding
          │   ]             │            │
          └─────────────────┘            │
                                         ▼
                              ┌─────────────────────┐
                              │   LabRunRecord       │
                              │   (runtime only)     │
                              │   started_at         │
                              │   stopped_at         │
                              │   lablet_session_id  │
                              │   final_state        │
                              │   (NO port fields)   │
                              └─────────────────────┘
```

### 3.4 LabRecord Gains `allocated_ports`

```python
# domain/entities/lab_record.py (MODIFY — LabRecordState)

# Add field:
allocated_ports: dict[str, int] | None  # {port_name: port_number} e.g. {"PC_serial": 3001, "PC_vnc": 3002}

# New domain event:
@dataclass
class LabRecordPortsAllocatedDomainEvent(LabRecordDomainEventBase):
    """Published when ports are allocated to a LabRecord."""
    type: str = "com.cisco.lcm.lab-record.ports-allocated.v1"
    allocated_ports: dict = field(default_factory=dict)

# New method on LabRecord aggregate:
def allocate_ports(self, allocated_ports: dict[str, int]) -> None:
    """Record port allocation on this lab record."""
    self.record_event(LabRecordPortsAllocatedDomainEvent(
        aggregate_id=self.id(),
        allocated_ports=allocated_ports,
    ))

# @dispatch handler:
@dispatch(LabRecordPortsAllocatedDomainEvent)
def on(self, event: LabRecordPortsAllocatedDomainEvent) -> None:
    self.allocated_ports = dict(event.allocated_ports)
```

### 3.5 LabRunRecord: NO Port Fields

`LabRunRecord` tracks **runtime** only — when a lab ran, for how long, for which session. It does NOT own ports. This is unchanged from the current codebase:

```python
# domain/value_objects/lab_run_record.py — NO CHANGES to fields

@dataclass(frozen=True)
class LabRunRecord:
    run_id: str
    started_at: datetime
    stopped_at: datetime | None = None
    duration_seconds: int | None = None
    started_by: str = "system"
    stop_reason: str | None = None
    lablet_session_id: str | None = None
    final_state: str | None = None
    # NO allocated_ports field — ports belong to LabRecord
```

### 3.6 Pipeline Step: `ports_alloc`

This step runs **after** `lab_resolve` (we need the resolved lab to know the worker and topology). It allocates ports from the worker pool and stores them on the **LabRecord**.

```python
async def _step_ports_alloc(self, instance, progress) -> StepResult:
    """Allocate real ports from worker pool via CPA PortAllocationService."""
    definition = await self._get_definition(instance.definition_id)
    if not definition or not definition.port_template:
        return StepResult(step="ports_alloc", status="skipped")

    # Get lab_resolve result (contains lab_record_id)
    resolve_result = progress.get_step("lab_resolve")
    lab_record_id = resolve_result.result_data.get("lab_record_id") if resolve_result else None
    if not lab_record_id:
        return StepResult(step="ports_alloc", status="failed", error="No lab_record_id from lab_resolve")

    # Call CPA internal endpoint — allocates via PortAllocationService (etcd)
    # Ports are stored on the LabRecord, keyed by lab_record_id in etcd
    result = await self._api.allocate_lab_record_ports(
        lab_record_id=lab_record_id,
        worker_id=instance.worker_id,
    )
    # result = {"allocated_ports": {"PC_serial": 3001, "PC_vnc": 3002}}
    return StepResult(
        step="ports_alloc", status="completed",
        result_data=result,
    )
```

#### 3.6.1 CPA Command: AllocateLabRecordPortsCommand

```python
# application/commands/lab_record/allocate_lab_record_ports_command.py (NEW)

@dataclass
class AllocateLabRecordPortsCommand(Command[OperationResult[dict]]):
    """Allocate ports from worker pool and store on LabRecord."""
    lab_record_id: str
    worker_id: str

class AllocateLabRecordPortsCommandHandler(CommandHandlerBase, ...):
    async def handle_async(self, request, ...):
        # 1. Load LabRecord and its definition's port_template
        lab_record = await self._lab_record_repo.get_by_id_async(request.lab_record_id)
        if not lab_record:
            return self.not_found("LabRecord", request.lab_record_id)

        # 2. Check if already allocated (idempotent)
        if lab_record.state.allocated_ports:
            return self.ok({"allocated_ports": lab_record.state.allocated_ports, "already_allocated": True})

        # 3. Get port_template from definition
        definition = await self._definition_repo.get_by_id_async(lab_record.state.definition_id)
        if not definition or not definition.state.port_template:
            return self.ok({"allocated_ports": {}, "skipped": True})

        port_template = PortTemplate.from_dict(definition.state.port_template)

        # 4. Allocate via PortAllocationService (etcd) — keyed by lab_record_id
        result = await self._port_service.allocate_ports(
            worker_id=request.worker_id,
            session_id=request.lab_record_id,  # Use lab_record_id as etcd key
            port_template=port_template,
        )
        if not result.success:
            return self.conflict(f"Port allocation failed: {result.error}")

        # 5. Store on LabRecord
        lab_record.allocate_ports(result.allocated_ports)
        await self._lab_record_repo.update_async(lab_record)

        return self.ok({"allocated_ports": result.allocated_ports})
```

**Note on etcd key**: The existing `PortAllocationService.allocate_ports()` uses `session_id` as its etcd key parameter. We pass `lab_record_id` in that parameter — semantically it's "the entity that owns these ports." The etcd key structure is `ports/{worker_id}/{owner_id}`. No code change needed in `PortAllocationService` itself — only the caller changes what ID it passes.

### 3.7 Pipeline Step: `tags_sync`

After ports are allocated, write them to the CML node tags. This step requires a **new CML SPI method** to patch node tags.

```python
async def _step_tags_sync(self, instance, progress) -> StepResult:
    """Write allocated port numbers to CML node tags via PATCH API."""
    ports_step = progress.get_step("ports_alloc")
    if not ports_step or ports_step.status != "completed":
        return StepResult(step="tags_sync", status="skipped")

    allocated_ports = ports_step.result_data.get("allocated_ports", {})
    if not allocated_ports:
        return StepResult(step="tags_sync", status="skipped")

    resolve_step = progress.get_step("lab_resolve")
    cml_lab_id = resolve_step.result_data.get("cml_lab_id") if resolve_step else None
    if not cml_lab_id:
        return StepResult(step="tags_sync", status="failed", error="No cml_lab_id from lab_resolve")

    # Group allocated ports by node label
    # Port names follow convention: "{node_label}_{protocol}" (from PortTemplate.from_cml_nodes)
    node_tags: dict[str, list[str]] = {}  # {node_label: ["protocol:port", ...]}
    for port_name, port_number in allocated_ports.items():
        # Parse "{node_label}_{protocol}" → (node_label, protocol)
        parts = port_name.rsplit("_", 1)
        if len(parts) != 2:
            continue
        node_label, protocol = parts
        tag = f"{protocol}:{port_number}"
        node_tags.setdefault(node_label, []).append(tag)

    # Get CML lab nodes to find node IDs
    nodes = await self._cml_labs.get_lab_nodes(
        worker_id=instance.worker_id,
        lab_id=cml_lab_id,
    )

    # Write tags to each node via PATCH
    synced_nodes = []
    for node in nodes:
        node_label = node.get("label", "")
        safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", node_label)
        if safe_label in node_tags:
            await self._cml_labs.patch_node_tags(
                worker_id=instance.worker_id,
                lab_id=cml_lab_id,
                node_id=node["id"],
                tags=node_tags[safe_label],
            )
            synced_nodes.append(node_label)

    return StepResult(
        step="tags_sync", status="completed",
        result_data={"synced_nodes": synced_nodes, "tag_count": sum(len(t) for t in node_tags.values())},
    )
```

#### 3.7.1 CML SPI Extension: `patch_node_tags`

The CML REST API supports `PATCH /api/v0/labs/{lab_id}/nodes/{node_id}` with a `NodeUpdate` schema that includes `tags: list[str]`. The SPI client needs a new method:

```python
# integration/services/cml_labs_spi_client.py (MODIFY — lablet-controller)

async def patch_node_tags(
    self, worker_id: str, lab_id: str, node_id: str, tags: list[str]
) -> dict:
    """Update tags on a CML lab node.

    Uses PATCH /api/v0/labs/{lab_id}/nodes/{node_id} with NodeUpdate schema.
    Tags are fully replaced (not merged) — caller must provide the complete tag list.

    Args:
        worker_id: CML worker hosting the lab
        lab_id: CML lab ID
        node_id: CML node ID within the lab
        tags: Complete list of tags (e.g., ["serial:3001", "vnc:3002"])

    Returns:
        Updated node dict from CML API
    """
    worker = await self._get_worker(worker_id)
    url = f"{worker.endpoint}/api/v0/labs/{lab_id}/nodes/{node_id}"
    payload = {"tags": tags}
    response = await self._session.patch(url, json=payload, headers=self._auth_headers(worker))
    response.raise_for_status()
    return response.json()
```

### 3.8 Scheduler Changes

The scheduler stops passing static port values. It only assigns the worker:

```python
# BEFORE (scheduler_hosted_service.py _handle_assign):
allocated_ports = {entry["name"]: entry["port"] for entry in port_entries}
await self._api.schedule_session(..., allocated_ports=allocated_ports, ...)

# AFTER:
# Scheduler passes EMPTY ports — just the worker assignment
await self._api.schedule_session(..., allocated_ports={}, ...)
```

The `PlacementEngine`'s port count filter (Stage 5) remains unchanged — it correctly checks availability without allocating.

### 3.9 Lab Discovery Port Tracking

When `LabDiscoveryService` discovers a STARTED/BOOTED lab without a session, the CML node tags already contain actual port mappings. These should be registered in etcd to prevent allocation conflicts:

```python
# In lab_discovery_service.py — when creating/updating a discovered lab:
# ExternalInterfaces are already extracted from CML node tags
# Record ports on LabRecord and register in etcd
lab_record.allocate_ports(discovered_port_mapping)  # from ExternalInterface VOs
await self._api.register_discovered_ports(
    worker_id=worker_id,
    lab_record_id=lab_record_id,
    ports=discovered_port_mapping,
)
```

This ensures the `PortAllocationService`'s etcd state reflects all active port consumers, not just session-initiated ones.

### 3.10 Port Release Lifecycle

Ports are released when a **LabRecord** is deleted or recycled — NOT when a session expires. This is critical for lab reuse:

| Event | Port Action | Why |
|-------|-------------|-----|
| Session expires / stops | **No port release** | LabRecord may be reused by next session |
| Lab wiped | **No port release** | Tags persist; same ports reused on next start |
| Lab stopped | **No port release** | Same ports when restarted |
| LabRecord deleted | **Release ports** from etcd | LabRecord gone → ports available |
| LabRecord unbound + recycled (definition changed) | **Release + re-allocate** | New topology may need different ports |

This differs from the previous design where ports were released at session expiry.

---

## 4. Lab Binding & LabRunRecord

### 4.1 Step Ordering Rationale

`lab_binding` runs **after** `lab_resolve` and `tags_sync` because:

- We need a resolved `cml_lab_id` to know which LabRecord to bind
- Tags must be synced before binding so the LabRecord's port state is consistent
- The LabRunRecord captures **runtime** context (who started it, when, for which session) — it does NOT carry port data

### 4.2 Current State (Problems)

| Component | Current Behavior | Problem |
|-----------|-----------------|---------|
| **LabRecord.bind_to_lablet()** | Emits `LabBoundToLabletDomainEvent` | Event handler is a **no-op** (`pass`). No binding state persisted. |
| **LabletSession.schedule()** | Accepts `lab_record_id` parameter | Stored as simple string FK — no validation at schedule time. |
| **SchedulerHostedService._handle_assign()** | Passes `lab_record_id = definition.get("lab_record_id", "")` | Empty string — scheduler doesn't resolve lab records. |
| **LabletReconciler._resolve_lab_for_instance()** | Finds/imports labs at instantiation | Creates CML lab but **doesn't create a LabRunRecord or update lab_record_id on session**. |

### 4.3 Proposed Design

#### 4.3.1 Pipeline Step: `lab_binding`

After `lab_resolve` provides a `cml_lab_id` and `tags_sync` has written port tags to CML nodes, bind the LabRecord to the session:

```python
async def _step_lab_binding(self, instance, progress) -> StepResult:
    """Bind LabRecord to session and create LabRunRecord."""
    # Get lab_resolve result (contains cml_lab_id and lab_record_id)
    resolve_result = progress.get_step("lab_resolve")
    cml_lab_id = resolve_result.result_data.get("cml_lab_id") if resolve_result else None
    lab_record_id = resolve_result.result_data.get("lab_record_id") if resolve_result else None
    if not cml_lab_id or not lab_record_id:
        return StepResult(step="lab_binding", status="failed", error="No cml_lab_id/lab_record_id from lab_resolve")

    # Call CPA internal endpoint to:
    # 1. Bind LabRecord to session (set active_lablet_session_id)
    # 2. Create LabRunRecord (runtime tracking)
    # 3. Denormalize LabRecord.allocated_ports onto LabletSession
    result = await self._api.bind_lab_to_session(
        session_id=instance.id,
        worker_id=instance.worker_id,
        lab_record_id=lab_record_id,
    )
    return StepResult(
        step="lab_binding", status="completed",
        result_data=result,  # {"lab_record_id": "...", "run_id": "...", "allocated_ports": {...}}
    )
```

#### 4.3.2 CPA Command: BindLabToSessionCommand

```python
# application/commands/lablet_session/bind_lab_to_session_command.py (NEW)

@dataclass
class BindLabToSessionCommand(Command[OperationResult[dict]]):
    """Bind a LabRecord to a session and create a LabRunRecord."""
    session_id: str
    worker_id: str
    lab_record_id: str
    # NO allocated_ports — ports are on the LabRecord already

class BindLabToSessionCommandHandler(CommandHandlerBase, ...):
    async def handle_async(self, request, ...):
        # 1. Load LabRecord
        lab_record = await self._lab_record_repo.get_by_id_async(request.lab_record_id)
        if not lab_record:
            return self.not_found("LabRecord", request.lab_record_id)

        # 2. Create LabRunRecord (runtime tracking — NO port fields)
        run = LabRunRecord(
            run_id=str(uuid4()),
            started_at=datetime.now(timezone.utc),
            started_by="lablet-controller",
            lablet_session_id=request.session_id,
        )
        lab_record.record_run(run)

        # 3. Bind LabRecord to session
        lab_record.bind_to_lablet(
            lablet_session_id=request.session_id,
            binding_id=run.run_id,
            binding_role="instantiation",
        )
        await self._lab_record_repo.update_async(lab_record)

        # 4. Denormalize LabRecord.allocated_ports onto LabletSession
        session = await self._session_repo.get_by_id_async(request.session_id)
        session.bind_lab_record(lab_record.id())
        allocated_ports = lab_record.state.allocated_ports or {}
        if allocated_ports:
            session.update_allocated_ports(allocated_ports)
        await self._session_repo.update_async(session)

        return self.ok({
            "lab_record_id": lab_record.id(),
            "run_id": run.run_id,
            "allocated_ports": allocated_ports,  # Returned for caller visibility
        })
```

#### 4.3.3 Fix LabRecord Bind Event Handler

The current handler is a no-op (`pass`). It should track the active binding:

```python
# domain/entities/lab_record.py (MODIFY)

# Add fields to LabRecordState:
active_lablet_session_id: str | None  # Currently bound session (if any)
active_binding_id: str | None         # Current binding ID (LabRunRecord.run_id)

@dispatch(LabRecordBoundToLabletDomainEvent)
def on(self, event: LabRecordBoundToLabletDomainEvent) -> None:
    """Apply binding event — records that a lablet session is using this lab."""
    self.active_lablet_session_id = event.lablet_session_id
    self.active_binding_id = event.binding_id

@dispatch(LabRecordUnboundFromLabletDomainEvent)
def on(self, event: LabRecordUnboundFromLabletDomainEvent) -> None:
    """Apply unbinding event."""
    if self.active_binding_id == event.binding_id:
        self.active_lablet_session_id = None
        self.active_binding_id = None
```

### 4.4 Scheduler: No Lab Binding at Schedule Time

The scheduler continues to pass `lab_record_id=""` — lab records are resolved and bound during instantiation, not scheduling. The `ScheduleLabletSessionCommand` already handles empty `lab_record_id`.

---

## 5. Variables Step

### 5.1 Purpose

A placeholder step for future integration with a variable resolution service. Variables would be resolved from:

- User-provided values at session creation time
- Definition-level defaults
- Environment-level overrides (dev/staging/prod)
- Dynamic values computed at instantiation (e.g., credentials, connection strings)

### 5.2 Implementation (Placeholder)

```python
async def _step_resolve_variables(self, instance: LabletSessionReadModel) -> StepResult:
    """Resolve session variables. Currently a no-op placeholder."""
    # Gate: definition has variables defined
    definition = await self._get_definition(instance.definition_id)
    variables = getattr(definition, 'variables', None)
    if not variables:
        return StepResult(step="variables", status="skipped")

    # Future: call variable resolution service
    # For now, pass through definition defaults
    resolved = {var.name: var.default_value for var in variables if var.default_value}

    return StepResult(
        step="variables",
        status="completed",
        result_data={"resolved_variables": resolved},
    )
```

### 5.3 Future Extension Points

When a variable resolution service is available:

1. Add `VariableResolutionSpiClient` to lablet-controller
2. Call the SPI with (definition_id, session_id, context) during this step
3. Store resolved variables on LabletSession (new `resolved_variables` field)
4. Downstream steps (lab_resolve, lds_provision) consume resolved variables

---

## 6. Content Sync Prerequisite

### 6.1 Purpose

Before attempting to instantiate a lab, verify that the definition's content package is synchronized and available. This is a **fail-fast** check — if content is not synced, there's no point importing a lab (it will fail anyway because LDS provisioning requires the form_qualified_name and content).

### 6.2 Implementation

```python
async def _step_verify_content_sync(self, instance: LabletSessionReadModel) -> StepResult:
    """Verify definition content is synced and available."""
    definition = await self._get_definition(instance.definition_id)
    if not definition:
        return StepResult(step="content_sync", status="failed", error="Definition not found")

    # Check if content sync is relevant for this definition
    if not getattr(definition, 'content_sync_enabled', False):
        return StepResult(step="content_sync", status="skipped")

    # Check sync status
    sync_status = getattr(definition, 'sync_status', None)
    if sync_status == "synced":
        return StepResult(step="content_sync", status="completed",
                         result_data={"sync_status": sync_status,
                                      "form_qualified_name": definition.form_qualified_name})

    # Not synced — trigger sync and fail this step (will retry on next reconcile)
    if sync_status in (None, "not_synced", "sync_failed"):
        # Optionally trigger a sync request
        try:
            await self._content_sync_service.request_sync(definition.id)
        except Exception as e:
            logger.warning(f"Could not trigger content sync for {definition.id}: {e}")

        return StepResult(step="content_sync", status="failed",
                         error=f"Content not synced (status: {sync_status}). Sync requested.")

    # sync_requested or syncing — wait
    return StepResult(step="content_sync", status="failed",
                     error=f"Content sync in progress (status: {sync_status}). Waiting.")
```

### 6.3 Interaction with ContentSyncService

The `content_sync` step doesn't perform the sync itself — it delegates to the existing `ContentSyncService` (if needed) and checks the `sync_status` field on the definition read model. The reconciler will naturally retry failed steps on the next cycle.

---

## 7. Timeslot Lifecycle & Downstream Cleanup

### 7.1 Timeslot as Lifecycle Container

A LabletSession maps 1:1 to a **timeslot** (`timeslot_start`, `timeslot_end`). The timeslot defines when the session's resources are active. All lifecycle operations happen within the timeslot boundary.

**Timeslot operations** (already on LabletSession):

| Operation | Method | Behavior |
|-----------|--------|----------|
| **Extend** | `extend_timeslot(new_end)` | Move `timeslot_end` forward — extends active window |
| **Start** | `start()` | Transition SCHEDULED → INSTANTIATING (reconciler picks it up) |
| **Stop** | `stop()` / `release_capacity()` | Graceful stop — releases worker capacity |
| **Cancel** | `cancel()` | Cancel before start — no resources to clean up |
| **Requeue** | `requeue()` | Re-enter scheduling queue (e.g., after worker failure) |

**Not implemented (and not needed per current design):** pause/resume. The session state machine is forward-only: once started, a session progresses toward completion or failure.

### 7.2 Sync Rules

A LabletSession may be synced (reconciled) at any time during its timeslot. The reconciler checks the session status and acts accordingly:

| Session Status | Timeslot Status | Reconciler Action |
|----------------|-----------------|-------------------|
| INSTANTIATING | Active (inside timeslot) | Execute next pipeline step |
| INSTANTIATING | Expired (past `timeslot_end`) | Fail session → trigger cleanup |
| READY / RUNNING | Active | Monitor health, sync ports |
| READY / RUNNING | Expired | Expire session → trigger cleanup |
| STOPPING | Any | Continue shutdown sequence |
| COMPLETED / FAILED | Any | No action (terminal states) |

**Key rule**: An active session (inside its timeslot) may be synced anytime — this is the normal reconciliation path. The pipeline advances one step per reconcile cycle.

### 7.3 Expired Session Cleanup

When a session's timeslot expires, the sync must handle **downstream resource cleanup**. Note: ports are NOT released at session expiry because they belong to the LabRecord (topology-level) and persist for lab reuse.

```
Session Expired
    │
    ├─→ 1. Update LabletSession status → EXPIRED
    │
    ├─→ 2. UserSession cleanup
    │   └─ Terminate LDS UserSession (if provisioned)
    │   └─ Remove user access credentials
    │
    ├─→ 3. LabRecord cleanup
    │   └─ Stop the lab (if running)
    │   └─ Wipe lab state (if configured by definition)
    │   └─ Close LabRunRecord (set stopped_at, stop_reason="timeslot_expired")
    │   └─ Unbind from session (clear active_lablet_session_id)
    │   └─ LabRecord.allocated_ports UNCHANGED — ports persist for reuse
    │   └─ CML node tags UNCHANGED — topology-level, persist across cycles
    │
    ├─→ 4. Capacity cleanup
    │   └─ Release worker capacity (ReleaseCapacityCommand)
    │   └─ Worker slot becomes available for scheduling
    │
    └─→ 5. Reporting
        └─ Publish session completion report
        └─ Record usage metrics (duration, resource consumption)
```

**Key difference from previous design**: Port release is NOT part of session expiry cleanup. Ports are released only when the **LabRecord itself is deleted** (e.g., worker decommissioned, definition removed, manual cleanup). See §3.10 for the full port release lifecycle.

```

### 7.4 Implementation: Expiry Check in Reconciler

The reconciler already handles multiple session states. Add an **early expiry check** before status-specific handling:

```python
async def _reconcile_instance(self, instance: LabletSessionReadModel) -> ReconciliationResult:
    """Reconcile a single LabletSession instance."""

    # Early check: timeslot expired?
    if instance.timeslot_end and datetime.now(timezone.utc) > instance.timeslot_end:
        if instance.status not in ("COMPLETED", "FAILED", "CANCELLED", "EXPIRED"):
            return await self._handle_expired(instance)

    # Normal status-based dispatch
    match instance.status:
        case "INSTANTIATING":
            return await self._handle_instantiating(instance)  # Pipeline executor
        case "READY" | "RUNNING":
            return await self._handle_active(instance)
        case "STOPPING":
            return await self._handle_stopping(instance)
        ...
```

### 7.5 Cleanup Command: ExpireLabletSessionCommand

```python
# application/commands/lablet_session/expire_lablet_session_command.py (NEW — CPA)

@dataclass
class ExpireLabletSessionCommand(Command[OperationResult[dict]]):
    """Handle session expiry: update status and trigger downstream cleanup."""
    session_id: str
    reason: str = "timeslot_expired"

class ExpireLabletSessionCommandHandler(CommandHandlerBase, ...):
    async def handle_async(self, request, ...):
        session = await self._session_repo.get_by_id_async(request.session_id)
        if not session:
            return self.not_found("LabletSession", request.session_id)

        # 1. Expire the session
        session.expire(reason=request.reason)

        # 2. Close the LabRunRecord and unbind — but DO NOT release ports
        if session.state.lab_record_id:
            lab_record = await self._lab_record_repo.get_by_id_async(session.state.lab_record_id)
            if lab_record:
                lab_record.close_run(
                    lablet_session_id=request.session_id,
                    stop_reason=request.reason,
                    final_state="expired",
                )
                lab_record.unbind_from_lablet(lablet_session_id=request.session_id)
                # NOTE: lab_record.allocated_ports is UNCHANGED — ports are
                # topology-level and persist for future sessions. CML node tags
                # are also unchanged. See §3.10 for port release lifecycle.
                await self._lab_record_repo.update_async(lab_record)

        # 3. Release capacity (NOT ports — ports belong to LabRecord)
        await self.mediator.execute_async(
            ReleaseCapacityCommand(
                session_id=request.session_id,
                worker_id=session.state.worker_id,
            )
        )

        await self._session_repo.update_async(session)

        return self.ok({"session_id": request.session_id, "status": "expired"})
```

**Key change from v2**: No `release_ports()` call. Ports belong to `LabRecord.allocated_ports` (topology-level) and are not affected by session expiry. Port release occurs only on LabRecord deletion (see §3.10).

**Note**: UserSession (LDS) cleanup and lab stop/wipe are triggered by the lablet-controller — the CPA records the state change, and the reconciler handles the physical teardown on the next cycle (stop CML lab, delete LDS session).

---

## 8. Pipeline UI (Phase 5)

### 8.1 Current State

The Pipeline tab in `SessionDetailModal` renders `"Coming soon…"`. The Phase 5 plan from [labletsession-ux.md](labletsession-ux.md) specifies "dot-indicators" for pipeline stages.

### 8.2 Proposed UI

With `instantiation_progress` persisted on the session, the Pipeline tab can render:

```
Pipeline Tab (steps follow DAG order)
┌─────────────────────────────────────────────┐
│  ● Content Sync     ✅ completed  00:02     │
│  ○ Variables        ⏭ skipped    —         │
│  ● Lab Resolution   ✅ completed  00:15     │
│  ● Port Allocation  ✅ completed  00:01     │
│  ● Tag Sync         ✅ completed  00:02     │
│  ● Lab Binding      ✅ completed  00:03     │
│  ● Lab Start        🔄 running   01:23     │
│  ○ LDS Provision    ⏳ pending   —         │
│  ○ Mark Ready       ⏳ pending   —         │
└─────────────────────────────────────────────┘
```

Each step shows:

- **Dot indicator**: ✅ completed (green), 🔄 running (blue pulse), ❌ failed (red), ⏭ skipped (gray), ⏳ pending (outline)
- **Step name**: Human-readable label
- **Duration**: Time from start to completion
- **Retry count**: If attempt_count > 1, show "(retry N)"
- **Error detail**: Expandable on click if failed

### 8.3 Data Source

The Pipeline tab reads from `session.instantiation_progress` which is included in the session detail DTO. The `GetLabletSessionDetailQuery` already returns the full session state — it just needs the new `instantiation_progress` field serialized.

### 8.4 SSE Integration

When `LabletSessionInstantiationProgressUpdatedDomainEvent` is published, the SSE relay can broadcast to subscribed clients for real-time step updates without polling.

---

## 9. Cross-Service Implementation Plan

### Phase 1: Domain Model & CPA Foundation (control-plane-api) ✅ COMPLETE

**Priority: HIGH | Effort: Large | Risk: LOW**
**Completed**: 2026-03-02 | **Tests**: 821 passed, 0 failures | **Lint**: All checks passed

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 1 | `domain/value_objects/instantiation_progress.py` | CREATE | ✅ | `InstantiationProgress`, `StepResult` VOs with `requires` dependency fields (9 steps incl. `tags_sync`) |
| 2 | `domain/entities/lab_record.py` | MODIFY | ✅ | Added `allocated_ports`, `allocate_ports()`, `LabRecordPortsAllocatedDomainEvent`, fixed `bind_to_lablet`, added `active_lablet_session_id` / `active_binding_id`. Note: `close_run()` deferred — not needed for Phase 1 expiry flow |
| 3 | `domain/events/lab_record_events.py` | MODIFY | ✅ | Added `LabRecordPortsAllocatedDomainEvent` |
| 4 | `domain/events/lablet_session_events.py` | MODIFY | ✅ | Added `LabletSessionInstantiationProgressUpdatedDomainEvent`, `LabletSessionExpiredDomainEvent`, `LabletSessionLabBoundDomainEvent` (extra — needed by bind command) |
| 5 | `domain/entities/lablet_session.py` | MODIFY | ✅ | Added `instantiation_progress` field, `update_instantiation_progress()`, `expire()`, `bind_lab()` methods + `@dispatch` handlers |
| 6 | `application/commands/lab/allocate_lab_record_ports_command.py` | CREATE | ✅ | Command + handler using `PortAllocationService`. Note: actual path is `commands/lab/` (not `commands/lab_record/`) per existing convention |
| 7 | `application/commands/lablet_session/update_instantiation_progress_command.py` | CREATE | ✅ | Command + handler with `_build_default_progress()` that resolves capability flags from LabletDefinition |
| 8 | `application/commands/lablet_session/bind_lab_to_session_command.py` | CREATE | ✅ | Command + handler — binds LabRecord to session, creates LabRunRecord, denormalizes `allocated_ports` |
| 9 | `application/commands/lablet_session/expire_lablet_session_command.py` | CREATE | ✅ | Command + handler — expiry cleanup (unbind, release capacity — NO port release). `close_run()` skipped (not yet on LabRecord) |
| 10 | `api/controllers/internal_sessions_controller.py` | MODIFY | ✅ | Added `/instantiation-progress`, `/allocate-lab-record-ports`, `/bind-lab`, `/expire` endpoints. Note: actual controller is `internal_sessions_controller.py` (not `internal/lablet_session_internal_controller.py`) |

**Deviations from plan:**

- `close_run()` on LabRecord deferred — not required for minimum viable expiry (unbind + release capacity suffices)
- Command file path: `commands/lab/` not `commands/lab_record/` — follows existing convention
- Controller path: `api/controllers/internal_sessions_controller.py` — existing controller, not a new file
- Added `LabletSessionLabBoundDomainEvent` (not in original plan) — needed by `bind_lab()` aggregate method
- `/sync-tags` endpoint deferred to Phase 3 (lablet-controller side; CPA doesn't need a dedicated endpoint for it)

### Phase 2: Core Read Model Enrichment (lcm-core) ✅ COMPLETE

**Priority: HIGH | Effort: Small | Risk: LOW**
**Completed**: 2026-03-02 | **Tests**: 103 passed, 0 failures | **Lint**: All checks passed

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 1 | `lcm_core/domain/entities/read_models/lablet_session_read_model.py` | MODIFY | ✅ | Added `instantiation_progress: dict | None` field + `from_dict()` deserialization. `timeslot_start`/`timeslot_end` already present from ADR-020 |
| 2 | `lcm_core/domain/entities/read_models/cml_worker_read_model.py` | MODIFY | ✅ | Added `allocated_port_count`, `available_port_count`, `port_utilization_pct` fields + `from_dict()` deserialization |
| 3 | `lcm_core/integration/clients/control_plane_client.py` | MODIFY | ✅ | Added `update_instantiation_progress()`, `allocate_lab_record_ports()`, `bind_lab_to_session()`, `expire_session()` methods |

**Deviations from plan:**

- `timeslot_start`/`timeslot_end` already present on `LabletSessionReadModel` (added in ADR-020) — only `instantiation_progress` was new
- `sync_lab_tags()` client method deferred — lablet-controller calls CML PATCH API directly (no CPA passthrough needed). Added to Phase 3 scope instead

### Phase 3: Lablet-Controller Pipeline Refactor (lablet-controller) ✅ COMPLETE

**Priority: HIGH | Effort: Large | Risk: MEDIUM**
**Completed**: 2026-03-06 | **Tests**: 231 passed, 0 failures | **Lint**: All checks passed

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 1 | `application/hosted_services/lablet_reconciler.py` | MODIFY | ✅ | Added early timeslot expiry check in `reconcile()`. Replaced monolithic `_handle_instantiating()` with DAG-based pipeline executor (Option A: inline methods). Added `_handle_expired()` method. Added 4 static pipeline helpers: `_build_default_progress()`, `_next_executable_step()`, `_is_pipeline_complete()`, `_get_step_result_data()` |
| 2 | (9 step methods within reconciler) | ADD | ✅ | `_step_content_sync()`, `_step_variables()`, `_step_lab_resolve()`, `_step_ports_alloc()`, `_step_tags_sync()`, `_step_lab_binding()`, `_step_lab_start()`, `_step_lds_provision()`, `_step_mark_ready()` — all return plain dicts (not CPA VOs) |
| 3 | `integration/services/cml_labs_spi.py` | MODIFY | ✅ | Added `patch_node_tags(host, lab_id, node_id, tags, username, password)` — calls `PATCH /api/v0/labs/{lab_id}/nodes/{node_id}` with `{"tags": tags}`. Used by `_step_tags_sync()` |
| 4 | `tests/test_instantiation_pipeline.py` | CREATE | ✅ | 53 tests: pipeline helpers (DAG resolution, default progress, completion check), step methods (content_sync, variables, ports_alloc, tags_sync, lab_binding, lds_provision, mark_ready), pipeline executor (bootstrap, dispatch, error handling), timeslot expiry |
| 5 | `tests/test_lablet_reconciler_g5.py` | MODIFY | ✅ | Updated 11 tests for pipeline-based flow. Fixed `get_nodes` → `get_lab_nodes` mock references. Added `_progress_with_lab_resolve()` helper. Added `instantiation_progress` to `make_instance()` |
| 6 | `tests/test_phase9_lab_discovery.py` | MODIFY | ✅ | Updated 4 tests in `TestHandleInstantiatingWithResolution` to test pipeline steps directly. Added `_content_sync_service`, `_worker_cache`, `_resource_observer` to `make_reconciler()` |

**Deviations from plan:**

- Step methods return **plain dicts** (not `StepResult` VOs from CPA domain) — lablet-controller does not import CPA domain classes; pipeline progress on the read model is a raw `dict[str, Any]`
- Pipeline dispatch uses `getattr(self, f"_step_{step_name}")` naming convention instead of explicit dict mapping — cleaner, auto-discovers new steps
- `_provision_lds_session()` kept for backward compatibility — `_step_lds_provision()` delegates to it
- Fixed pre-existing bug: `get_nodes()` → `get_lab_nodes()` in `_provision_lds_session()`
- `_step_tags_sync` treats tag sync failures as **non-fatal** (AD-TAGS-001) — logs warning and marks step completed
- Added `import re` for node label sanitization in tag sync

**Architecture decisions:**

- **AD-TAGS-001**: Tags sync failures are non-fatal — lab can function without tags (they're for port documentation/external-interface resolution)
- **Option A confirmed**: Pipeline steps as inline methods on LabletReconciler — avoids premature abstraction while keeping all instantiation logic colocated

### Phase 4: Scheduler Simplification (resource-scheduler) ✅ COMPLETE

**Priority: MEDIUM | Effort: Small | Risk: LOW**
**Completed**: 2026-03-02 | **Tests**: 78 passed (resource-scheduler), 0 new failures | **Lint**: All checks passed

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 1 | `application/hosted_services/scheduler_hosted_service.py` | MODIFY | ✅ | Removed static port allocation block from `_handle_assign()` (lines 420–427). Replaced with `allocated_ports: dict[str, int] = {}`. Updated docstring and inline comments. Port allocation deferred to lablet-controller pipeline (`ports_alloc` step). |
| 2 | `application/services/placement_engine.py` | VERIFY | ✅ | `_check_port_availability()` confirmed count-only (checks `len(port_entries)` vs available). No change needed. |
| 3 | `tests/unit/.../test_scheduler_hosted_service_phase2.py` | MODIFY | ✅ | Updated `test_reconcile_includes_ports_in_schedule` to assert `allocated_ports == {}` instead of checking for specific port names. |

**Architecture decisions:**

- **AD-P4-001**: Defer port allocation from scheduler to lablet-controller pipeline — scheduler passes `{}`, real allocation happens during `ports_alloc` step
- Pre-existing `test_scheduler_service.py` failures (8 tests) confirmed unrelated — legacy test file using old API method names (`schedule_instance`, `get_pending_instances`)

### Phase 5: Lab Discovery Port Registration (lablet-controller) ✅ COMPLETE

**Priority: MEDIUM | Effort: Medium | Risk: LOW**
**Completed**: 2026-03-02 | **Tests**: 255 passed (lablet-controller), 0 new failures | **Lint**: All checks passed

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 1 | `application/hosted_services/lab_discovery_service.py` | MODIFY | ✅ | Added `_register_ports_and_sync_tags()` called after `discover_lab_records()` for BOOTED/STARTED labs. Finds LabRecord via CPA `get_lab_records_for_worker()`, calls `allocate_lab_record_ports()` (idempotent), then syncs CML node tags via `_sync_tags_if_missing()`. Added `PortRegistrationResult` class, port/tag stat counters, `get_stats()` update. |
| 2 | `application/hosted_services/lab_discovery_service.py` | ADD method | ✅ | `_sync_tags_if_missing(host, lab_id, allocated_ports)` — builds expected tags per node from port name convention (`{safe_label}_{protocol}`), compares with CML node tags, merges and PATCHes missing tags. AD-TAGS-001 non-fatal. |
| 3 | `tests/test_phase9_lab_discovery.py` | MODIFY | ✅ | Added 21 tests in 4 new test classes: `TestPortRegistrationResult` (2), `TestRegisterPortsAndSyncTags` (10), `TestSyncTagsIfMissing` (8), `TestDiscoveryPortRegistrationIntegration` (3). Covers: BOOTED/STARTED filtering, idempotent allocation, tag merge, non-fatal errors, stats tracking. |

**Architecture decisions:**

- **AD-P5-001**: Port registration runs after `discover_lab_records()` CPA call, as a non-blocking post-processing step. Discovery results are unaffected by port registration failures — separation of concerns between discovery sync and port management.
- **AD-P5-002**: Tag sync uses merge semantics — existing non-port tags are preserved, missing port tags are added. Tags are sorted for deterministic ordering.
- Labs without `based_on_definition_id` are skipped (unmanaged/ad-hoc labs don't have port templates).

### Phase 6: Worker Read Model & Frontend (control-plane-api + worker-controller) ✅ COMPLETE

**Priority: LOW | Effort: Medium | Risk: LOW**
**Completed**: 2026-03-02 | **Tests**: 822 passed, 0 new failures | **Lint**: All checks passed

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 1 | `application/dtos/cml_worker_dto.py` | MODIFY | ✅ | Added `allocated_port_count`, `available_port_count`, `port_utilization_pct` fields |
| 2 | `application/mappers/cml_worker_mapper.py` | MODIFY | ✅ | Added port usage defaults (0) — enriched by query handler |
| 3 | `application/queries/get_cml_worker_by_id_query.py` | MODIFY | ✅ | Injected `PortAllocationService`, enriches DTO with `get_port_usage_stats()` (graceful fallback to 0 on error) |
| 4 | `application/dtos/lablet_session_dto.py` | MODIFY | ✅ | Added `instantiation_progress: dict \| None` field to `LabletSessionDto` + mapping from `state.instantiation_progress` |
| 5 | `ui/src/scripts/components/modals/SessionDetailsModal.js` | MODIFY | ✅ | Replaced Pipeline tab "Coming soon…" with full DAG-ordered step progress visualization. Shows: step dot indicators (✅/🔄/❌/⏭/⏳), human labels, status badges, retry counts, error details, result data summary, progress bar, pipeline timing. SSE-reactive (invalidates cache on refresh). |
| 6 | `tests/application/test_lablet_session_queries.py` | MODIFY | ✅ | Added `instantiation_progress = None` to mock state |
| 7 | `tests/application/test_lablet_session_dtos_and_sse.py` | MODIFY | ✅ | Added `instantiation_progress = None` to mock state |

**Architecture decisions:**

- **AD-P6-001**: Port usage enrichment is done in the query handler (not the mapper) because `PortAllocationService` is async and requires etcd access — the mapper is a pure synchronous function. Port stats default to 0 and are enriched post-mapping.
- **AD-P6-002**: Pipeline tab is SSE-reactive — cache is invalidated on every `refreshCurrentTab()` call so step progress updates in real-time during instantiation.

### Phase 7: Testing (control-plane-api) ✅ COMPLETE

**Priority: MEDIUM | Effort: Medium | Risk: LOW**
**Completed**: 2026-03-02 | **Tests**: 773 passed (1 pre-existing rename-integrity failure), 0 new failures | **Lint**: 0 new lint errors

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 1 | `tests/domain/test_instantiation_progress.py` | CREATE (CPA) | ✅ | ~50 tests across 8 test classes: `TestStepResult` (5), `TestBuildDefault` (8), `TestDAGResolution` (10), `TestStepTransitions` (9), `TestPipelineCompletion` (11), `TestGetStep` (2), `TestProgressSerialization` (3), `TestFullPipelineWalkthrough` (2). Covers DAG resolution, skip semantics, serialization round-trip, full pipeline walkthrough |
| 2 | `tests/application/test_allocate_lab_record_ports_command.py` | CREATE (CPA) | ✅ | 9 tests: nominal allocation, idempotency (already allocated), lab record not found, no definition id, definition not found, no port template, empty port template, dict port template coercion, allocation service failure |
| 3 | `tests/application/test_bind_lab_to_session_command.py` | CREATE (CPA) | ✅ | 7 tests: nominal binding with port denormalization, binding without ports, idempotency (already bound), lab record not found, session not found, already bound to different session, conflicting binding |
| 4 | `tests/application/test_expire_lablet_session_command.py` | CREATE (CPA) | ✅ | 10 tests: nominal expiry (unbind + capacity release), allocated_ports unchanged invariant, idempotency (already expired), session not found, invalid state transition (409), no lab record bound, no worker (skip capacity release), capacity release failure (still ok), capacity release exception (still ok), custom reason propagation |
| 5 | `tests/test_instantiation_pipeline.py` | (lablet-controller) | ✅ | 53 tests — completed in Phase 3 |

**Key testing insight (gotcha):**

- `InstantiationProgress.next_executable_step()` treats `skipped` as satisfied — when testing that a failed step blocks dependents, use `build_default(has_port_template=True, has_content_sync=True, has_lds=True)` so intermediate steps are pending (not pre-skipped), otherwise `mark_ready` remains executable despite upstream failure.

**Deviations from plan:**

- Test file paths use flat `tests/domain/` and `tests/application/` directories (not `tests/test_*.py` at root)
- Expire tests cover 10 scenarios (not 4 as originally estimated) — added critical invariant tests for allocated_ports unchanged, capacity release edge cases, and custom reason propagation

---

## 10. Migration & Backward Compatibility

### 10.1 Existing Sessions

Sessions created before this change will have `instantiation_progress = None`. The pipeline executor handles this gracefully:

```python
def _build_default_progress(self, instance: LabletSessionReadModel) -> InstantiationProgress:
    """Build default progress for sessions without pipeline tracking."""
    # For sessions already past INSTANTIATING, mark all steps as completed
    if instance.status in ("READY", "RUNNING", ...):
        return InstantiationProgress(steps=[...all completed...])

    # For sessions currently INSTANTIATING, start fresh
    return InstantiationProgress(steps=[...all pending...])
```

### 10.2 Scheduler Port Allocation

The scheduler currently passes static port values. After Phase 4, it passes `{}`. The CPA `ScheduleLabletSessionCommand` already handles empty `allocated_ports` — the session is created with `allocated_ports=None` and real ports are allocated during the `ports_alloc` pipeline step.

### 10.3 LabRecord Field Addition

Adding `allocated_ports` to `LabRecord` (the `LabRecordState` dataclass) is backward-compatible — the field defaults to `None`. Existing lab records in MongoDB will deserialize with `allocated_ports=None`. Note: `LabRunRecord` intentionally has NO port fields — ports are a topology-level concern on the LabRecord, not a runtime concern.

### 10.4 CML SPI Backward Compatibility

The new `patch_node_tags()` method is additive — no existing SPI methods are modified. Workers running older CML versions that don't support `PATCH /api/v0/labs/{lab_id}/nodes/{node_id}` will fail the `tags_sync` step gracefully. The pipeline step should treat tag sync failures as non-fatal warnings (log and continue) since the lab can still function without tags — tags are primarily for port documentation and external-interface resolution.

### 10.5 API Versioning

New internal endpoints are additive (no breaking changes). The `update_instantiation_progress`, `allocate_lab_record_ports`, `sync_lab_tags`, `bind_lab_to_session`, and `expire_session` endpoints are called only by the updated lablet-controller. Old lablet-controllers (pre-pipeline) continue using the monolithic flow until upgraded.

### 10.6 Rollback Plan

If the pipeline refactor causes issues:

1. Revert lablet-controller to monolithic `_handle_instantiating()`
2. CPA changes are backward-compatible (new fields default to None)
3. Scheduler changes are backward-compatible (empty ports were already handled)

---

## Appendix A: Sequence Diagram — Full Pipeline Flow

```
resource-scheduler          control-plane-api          lablet-controller         CML Labs SPI       LDS SPI
      │                           │                           │                       │                │
      │ schedule_session(ports={})│                           │                       │                │
      ├──────────────────────────>│                           │                       │                │
      │                           │ PENDING→SCHEDULED         │                       │                │
      │                           │──── etcd publish ────────>│                       │                │
      │                           │                           │ reconcile(SCHEDULED)   │                │
      │                           │                           │ → start_instantiation()│                │
      │                           │ SCHEDULED→INSTANTIATING   │                       │                │
      │                           │<──────────────────────────│                       │                │
      │                           │──── etcd publish ────────>│                       │                │
      │                           │                           │ reconcile(INSTANTIATING)               │
      │                           │                           │                       │                │
      │                           │                           │ ┌─ DAG roots (parallel)─┐              │
      │                           │                           │ │                       │              │
      │                           │                           │ │ Step 1: content_sync  │              │
      │                           │                           │ │ (verify definition)   │              │
      │                           │                           │ │ → update_progress()   │              │
      │                           │<──────────────────────────│ │                       │              │
      │                           │                           │ │                       │              │
      │                           │                           │ │ Step 2: variables     │              │
      │                           │                           │ │ (skipped—placeholder) │              │
      │                           │                           │ └───────────────────────┘              │
      │                           │                           │                       │                │
      │                           │                           │ Step 3: lab_resolve (requires: content_sync)
      │                           │                           │─── resolve/import ────>│                │
      │                           │                           │<──────────────────────│                │
      │                           │                           │ → update_progress()    │                │
      │                           │<──────────────────────────│                       │                │
      │                           │                           │                       │                │
      │                           │                           │ Step 4: ports_alloc (requires: lab_resolve)
      │                           │                           │ → allocate_lab_record_ports()          │
      │                           │ PortAllocationService     │                       │                │
      │                           │ (etcd atomic alloc,       │                       │                │
      │                           │  keyed by lab_record_id)  │                       │                │
      │                           │ LabRecord.allocated_ports │                       │                │
      │                           │<──────────────────────────│                       │                │
      │                           │                           │                       │                │
      │                           │                           │ Step 5: tags_sync (requires: ports_alloc)
      │                           │                           │─ PATCH node tags ─────>│                │
      │                           │                           │ (per node: protocol:port)              │
      │                           │                           │<──────────────────────│                │
      │                           │                           │ → update_progress()    │                │
      │                           │<──────────────────────────│                       │                │
      │                           │                           │                       │                │
      │                           │                           │ Step 6: lab_binding (requires: tags_sync)
      │                           │                           │ → bind_lab_to_session()│                │
      │                           │ LabRunRecord created      │                       │                │
      │                           │ (NO ports on run)         │                       │                │
      │                           │ Session gets denormalized │                       │                │
      │                           │ ports from LabRecord      │                       │                │
      │                           │<──────────────────────────│                       │                │
      │                           │                           │                       │                │
      │                           │                           │ Step 7: lab_start (requires: lab_binding)
      │                           │                           │─── start_lab ─────────>│                │
      │                           │                           │ (poll until BOOTED)    │                │
      │                           │                           │<──────────────────────│                │
      │                           │                           │ → update_progress()    │                │
      │                           │<──────────────────────────│                       │                │
      │                           │                           │                       │                │
      │                           │                           │ Step 8: lds_provision (requires: lab_start)
      │                           │                           │──── create_session ───────────────────>│
      │                           │                           │──── set_devices ──────────────────────>│
      │                           │                           │<──────────────────────────────────────│
      │                           │                           │ → create_user_session() │                │
      │                           │<──────────────────────────│                       │                │
      │                           │                           │                       │                │
      │                           │                           │ Step 9: mark_ready (requires: lds_provision)
      │                           │                           │ → mark_session_ready() │                │
      │                           │ INSTANTIATING→READY       │                       │                │
      │                           │<──────────────────────────│                       │                │
      │                           │                           │                       │                │
      ·                           ·                    ── timeslot expires ──         ·                ·
      │                           │                           │                       │                │
      │                           │                           │ Expiry: reconcile()    │                │
      │                           │                           │ → expire_session()     │                │
      │                           │ close LabRunRecord        │                       │                │
      │                           │ unbind LabRecord          │                       │                │
      │                           │ (ports UNCHANGED on       │                       │                │
      │                           │  LabRecord — topology)    │                       │                │
      │                           │ release capacity          │                       │                │
      │                           │ READY→EXPIRED             │                       │                │
      │                           │<──────────────────────────│                       │                │
      │                           │                           │ stop CML lab ─────────>│                │
      │                           │                           │ delete LDS session ───────────────────>│
```

## Appendix B: Decision Record

**ADR-031: Checkpoint-Based Instantiation Pipeline**

- **Decision**: Replace monolithic `_handle_instantiating()` with DAG-based checkpoint pipeline where progress is persisted per-step to the LabletSession aggregate. Steps declare their prerequisites; `next_executable_step()` resolves execution order. Pipeline has 9 steps including `tags_sync`.
- **Rationale**: Current waterfall approach has no recovery, no visibility, no per-step retry capability. Combined with drain-loop fix, checkpoints enable reliable multi-step advancement.
- **Alternatives Rejected**:
  - **Workflow engine** (Temporal/Prefect): Adds operational complexity, overkill for 9 steps
  - **Saga pattern**: Steps don't have compensating actions (can't "un-import" a lab meaningfully)
  - **Linear ordering**: Steps have true dependencies (e.g., tags_sync needs ports_alloc result), so a DAG is the natural representation
- **Related**: AD-DRAIN-001 (prerequisite), ADR-020 (session consolidation), ADR-029 (port template), ADR-030 (resource observation)

**AD-PORT-001: Port Allocation as LabRecord Topology Concern**

- **Decision**: Ports are allocated to the **LabRecord** (`LabRecordState.allocated_ports: dict[str, int] | None`), NOT to a LabRunRecord or LabletSession. The LabletSession gets a denormalized copy via the `lab_binding` step. Port allocation uses etcd, keyed by `lab_record_id`. Ports persist across start/stop/wipe cycles and are released **only** when the LabRecord is deleted.
- **Rationale**: Ports are a topology-level concern — they represent how a lab's nodes are reachable on a worker's port range. A lab's topology (nodes, edges, tags) persists across start/stop/wipe operations. If ports were on LabRunRecord, they would be lost on each stop/wipe cycle, requiring re-allocation and re-tagging. By owning ports at the LabRecord level, we ensure port stability for the lab's entire lifetime on a worker.
- **Scheduler impact**: Scheduler only validates port count availability (`validate_port_availability()`), passes `allocated_ports={}`. Real allocation is a provisioning concern, not a scheduling concern.
- **Lab discovery**: Discovered labs register their existing ports on the LabRecord via `AllocateLabRecordPortsCommand` to prevent conflicts.

**AD-BIND-001: LabRunRecord Without Port Fields**

- **Decision**: The `lab_binding` pipeline step creates a `LabRunRecord` WITHOUT `allocated_ports`. `LabRunRecord` is a pure runtime concern (run_id, started_at, stopped_at, duration, stop_reason). Port information comes from the parent `LabRecord.allocated_ports`. The LabRecord tracks the active binding (`active_lablet_session_id`, `active_binding_id`).
- **Rationale**: Ports don't change between runs — they are topology-level (see AD-PORT-001). Duplicating ports on every LabRunRecord would create data inconsistency risks and storage waste. A LabRunRecord captures the complete context of a lab run — who started it, when, for how long, for which session. Port lookup is via `LabRecord.allocated_ports` (single source of truth).

**AD-TAGS-001: CML Node Tags Synced with Allocated Ports**

- **Decision**: After port allocation (`ports_alloc` step), a new `tags_sync` step writes allocated ports as CML node tags using `PATCH /api/v0/labs/{lab_id}/nodes/{node_id}` with `tags: list[str]`. Tag format: `protocol:port_number` (e.g., `serial:3001`, `vnc:3002`). Tags persist across start/stop/wipe because they are topology-level. The `tags_sync` step is non-fatal — if CML doesn't support PATCH or the call fails, the step logs a warning and proceeds.
- **Rationale**: CML node tags are the canonical mechanism for documenting which ports map to which protocols on each node. They are consumed by `PortTemplate.from_cml_nodes()` to build `ExternalInterface` value objects. Without tag sync, allocated ports would be invisible to topology inspection, and lab discovery would not be able to reconstruct port mappings for already-running labs.
- **Tag lifecycle**: Tags are written once (after `ports_alloc`) and persist for the lab's lifetime. They are NOT modified by stopping, wiping, or restarting the lab. Tags are removed only if the lab is deleted from CML (which also triggers LabRecord deletion and port release).
- **CML SPI extension**: Requires `patch_node_tags(worker_id, lab_id, node_id, tags: list[str])` method added to the CML SPI client.

**AD-TIMESLOT-001: Timeslot-Centric Session Lifecycle**

- **Decision**: A LabletSession maps 1:1 to a timeslot (`timeslot_start`, `timeslot_end`). Expiry triggers downstream cleanup: LabRunRecord closure, LabRecord unbinding, capacity release, LDS session teardown. **Ports are NOT released at session expiry** — they belong to the LabRecord and persist for lab reuse.
- **Rationale**: Keeping the lifecycle simple (forward-only state machine with extend support) avoids complexity. The timeslot is the authoritative lifecycle boundary — when it expires, runtime resources (capacity, LDS session) are cleaned up, but topology-level resources (ports, tags) remain on the LabRecord for future sessions.
