# ADR-032: Port Allocation as LabRecord Topology Concern

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-02 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-004](./ADR-004-port-allocation-per-worker.md) (Port Allocation per Worker), [ADR-019](./ADR-019-labrecord-independent-aggregate.md) (LabRecord as AggregateRoot), [ADR-020](./ADR-020-session-entity-model.md) (Session Entity Model), [ADR-029](./ADR-029-port-template-extraction-from-cml-yaml.md) (Port Template Extraction), [ADR-031](./ADR-031-checkpoint-instantiation-pipeline.md) (Checkpoint Pipeline), [ADR-033](./ADR-033-cml-node-tag-sync.md) (CML Node Tag Sync) |
| **Implementation** | [Instantiation Pipeline Plan §3](../../implementation/instantiation-pipeline.md) |

## Context

Port allocation determines which host-side TCP ports on a CML worker are mapped to each lab node's console protocols (serial, VNC, SSH, etc.). The system must decide **which entity owns allocated ports** — this determines the port lifecycle (when allocated, when released) and has significant implications for resource accounting accuracy.

### Previous Design (Superseded)

Early designs placed `allocated_ports` on either the `LabletSession` (scheduling-time allocation) or the `LabRunRecord` (runtime allocation). Both have a fundamental flaw:

- **Session-level ownership**: Ports are released when the session expires, then re-allocated for the next session on the same lab — even though the lab topology hasn't changed. Wasteful and prone to port churn.
- **Run-level ownership**: Ports are released when a run stops (wipe/stop), then re-allocated when the next run starts — even though the lab's nodes and their tags haven't changed. Equally wasteful.

### Key Insight: Ports Are Topology

A CML lab's topology consists of **nodes**, **edges** (links between nodes), and **tags** (metadata on nodes, including port protocol assignments). Ports represent how a node is externally reachable — this is a property of the lab's topology on a specific worker, not a property of any individual session or run.

**Topology persists across start/stop/wipe operations.** Stopping a lab doesn't delete its nodes or remove its tags. Wiping a lab resets node state but preserves the topology graph. Only deleting the lab removes the topology entirely.

Since ports are part of the topology, they should be owned by the entity that represents the lab's topology on a worker: the **LabRecord**.

## Decision

### 1. Port Ownership on LabRecord

Add `allocated_ports: dict[str, int] | None` to `LabRecordState`. This field stores the mapping from port name (e.g., `PC_serial`) to host port number (e.g., `3001`).

```python
# Port ownership hierarchy:
#
#   LabRecord.allocated_ports        ← canonical owner (topology-level)
#       │
#       ├──→ LabletSession.allocated_ports   ← denormalized copy (via lab_binding step)
#       │
#       └──→ CML node tags                   ← synced copy (via tags_sync step)
#
#   LabRunRecord                     ← NO port fields (pure runtime concern)
```

### 2. LabRunRecord Has NO Port Fields

`LabRunRecord` is a pure runtime value object: `run_id`, `started_at`, `stopped_at`, `duration_seconds`, `started_by`, `stop_reason`, `lablet_session_id`, `final_state`. It intentionally does **not** carry `allocated_ports`.

Port information for a given run is always available via the parent `LabRecord.allocated_ports` — there is a single source of truth.

### 3. Port Allocation Keyed by lab_record_id

The `PortAllocationService` (etcd-backed atomic allocation) uses `lab_record_id` as the entity key instead of `session_id`:

```python
# AllocateLabRecordPortsCommand handler:
result = await self._port_service.allocate_ports(
    worker_id=worker_id,
    session_id=lab_record_id,    # ← lab_record_id in the session_id slot
    port_template=port_template,
)

# No code change needed in PortAllocationService itself — it treats
# session_id as an opaque entity key for etcd key construction.
```

### 4. Port Allocation via AllocateLabRecordPortsCommand

A new CQRS command handles port allocation as a LabRecord concern:

```python
@dataclass
class AllocateLabRecordPortsCommand(Command[OperationResult[dict]]):
    """Allocate ports from worker range and write to LabRecord."""
    lab_record_id: str
    worker_id: str
    port_template: dict    # Serialized PortTemplate

class AllocateLabRecordPortsCommandHandler(CommandHandlerBase):
    async def handle_async(self, request, ...):
        lab_record = await self._lab_record_repo.get_by_id_async(request.lab_record_id)
        if not lab_record:
            return self.not_found("LabRecord", request.lab_record_id)

        # Skip if already allocated (idempotent)
        if lab_record.state.allocated_ports:
            return self.ok(lab_record.state.allocated_ports)

        # Allocate from worker's port range
        template = PortTemplate.from_dict(request.port_template)
        result = await self._port_service.allocate_ports(
            worker_id=request.worker_id,
            session_id=request.lab_record_id,
            port_template=template,
        )

        if not result.success:
            return self.conflict(f"Port allocation failed: {result.error}")

        # Record on aggregate
        lab_record.allocate_ports(result.allocated_ports)
        await self._lab_record_repo.update_async(lab_record)

        return self.ok(result.allocated_ports)
```

### 5. Port Release Lifecycle

Ports are released **only** when the LabRecord is deleted:

| Event | Port Action | Rationale |
|-------|-------------|-----------|
| Session scheduled | — | Ports not allocated yet |
| `ports_alloc` step | **ALLOCATE** | Ports assigned from worker range |
| `tags_sync` step | — | Tags written to CML nodes |
| Session expires | **UNCHANGED** | Topology persists for reuse |
| Lab stopped | **UNCHANGED** | Stop preserves topology |
| Lab wiped | **UNCHANGED** | Wipe resets state, not topology |
| New session on same lab | **REUSE** | Existing ports from LabRecord |
| Lab deleted from CML | **RELEASE** | Topology destroyed |
| LabRecord deleted | **RELEASE** | Entity removed |
| Worker decommissioned | **RELEASE** | All ports freed |

### 6. Session Gets Denormalized Copy

During the `lab_binding` pipeline step, the `LabletSession` receives a **denormalized copy** of `LabRecord.allocated_ports`. This enables the session to serve port data without joining to the LabRecord — useful for UI display, SSE events, and LDS device provisioning.

```python
# BindLabToSessionCommand handler:
session.bind_lab(
    lab_record_id=lab_record.id(),
    allocated_ports=lab_record.state.allocated_ports,  # denormalized copy
)
```

### 7. Lab Discovery Registers Existing Ports

When `LabDiscoveryService` discovers an already-running lab on a worker, it registers the lab's existing ports on the LabRecord via `AllocateLabRecordPortsCommand`. This prevents port allocation conflicts when new sessions are scheduled on the same worker. It also syncs CML node tags if ports were assigned but tags are missing.

## Rationale

### Why LabRecord (not LabRunRecord)?

- **Topology persistence**: A lab's nodes, edges, and tags persist across start/stop/wipe. Ports are part of this topology. If ports were on LabRunRecord, they'd be lost on each stop/wipe cycle, requiring re-allocation and re-tagging on every restart.
- **Single source of truth**: One field (`LabRecord.allocated_ports`) is the canonical owner. LabRunRecord and LabletSession get copies. No risk of data inconsistency across run records.
- **Storage efficiency**: Instead of duplicating port data on every LabRunRecord in `run_history_v2` (up to 50 entries), ports are stored once on the LabRecord.

### Why LabRecord (not LabletSession)?

- **Lab-centric, not session-centric**: The same lab with the same ports can be used across multiple sessions. Ports are a property of "this lab exists on this worker with these port mappings" — not "this session was allocated these ports".
- **Reuse**: When a new session binds to a LabRecord that already has allocated ports, no re-allocation is needed. The session simply copies the existing ports.

### Why not release on session expiry?

- Releasing ports on session expiry would require re-allocating them when the next session uses the same lab. Since the lab topology hasn't changed, this is pure waste.
- Worse, re-allocation could assign different port numbers, requiring CML node tags to be updated and LDS sessions to be reconfigured — a cascade of unnecessary work.
- Port exhaustion risk is addressed by releasing ports when labs are actually deleted.

## Consequences

### Positive

- **Port stability**: A lab's ports remain consistent for its entire lifetime on a worker — no churn across sessions
- **Reduced overhead**: No port allocation/release on session boundaries — only on lab creation/deletion
- **Simplified binding**: `BindLabToSessionCommand` just copies ports, doesn't allocate them
- **Accurate accounting**: `PortAllocationService` tracks ports by `lab_record_id`, reflecting actual topology-level consumption
- **Reusable labs**: Labs with pre-allocated ports can serve multiple sessions without port re-allocation

### Negative

- **Longer port hold times**: Ports are held for the lab's entire lifetime, not just active sessions. In a high-turnover environment with many short-lived labs, this could reduce available ports. Mitigated: port range is 2000-9999 (8000 ports per worker), and lab lifecycle management should clean up unused labs.
- **LabRecord deletion discipline**: Ports are only freed on LabRecord deletion. If orphan LabRecords accumulate without cleanup, ports leak. Mitigated: orphan detection and garbage collection (ADR-014 pattern).

### Risks

- **etcd key collision**: Using `lab_record_id` instead of `session_id` as the etcd key changes the semantics. If the `PortAllocationService` has logic that assumes `session_id` semantics, it could misbehave. Mitigated: the service treats the key as an opaque string — no semantic assumptions.
- **Backward compatibility**: Existing sessions with `allocated_ports` on the session (but not the LabRecord) need migration handling. Mitigated: field defaults to `None`, and the `ports_alloc` step handles the initial allocation.

## Implementation Notes

### Domain Changes (control-plane-api)

```python
# LabRecordState additions:
allocated_ports: dict[str, int] | None = None

# New domain event:
@dataclass
class LabRecordPortsAllocatedDomainEvent(DomainEvent):
    lab_record_id: str
    worker_id: str
    allocated_ports: dict[str, int]

# New aggregate method:
def allocate_ports(self, ports: dict[str, int]) -> None:
    self.record_event(LabRecordPortsAllocatedDomainEvent(
        lab_record_id=self.id(),
        worker_id=self.state.worker_id,
        allocated_ports=ports,
    ))

@dispatch(LabRecordPortsAllocatedDomainEvent)
def on(self, event: LabRecordPortsAllocatedDomainEvent) -> None:
    self.state.allocated_ports = event.allocated_ports
```

### Port Release (Future Implementation)

Port release is triggered by LabRecord deletion:

```python
# DeleteLabRecordCommand handler (or LabRecord.delete() method):
if lab_record.state.allocated_ports:
    await self._port_service.release_ports(
        worker_id=lab_record.state.worker_id,
        session_id=lab_record.id(),  # lab_record_id as key
    )
```

## Related Documents

- [Instantiation Pipeline Plan §3](../../implementation/instantiation-pipeline.md)
- [ADR-004: Port Allocation per Worker](./ADR-004-port-allocation-per-worker.md)
- [ADR-029: Port Template Extraction from CML YAML](./ADR-029-port-template-extraction-from-cml-yaml.md)
- [ADR-031: Checkpoint-Based Instantiation Pipeline](./ADR-031-checkpoint-instantiation-pipeline.md)
- [ADR-033: CML Node Tag Sync with Allocated Ports](./ADR-033-cml-node-tag-sync.md)
- `domain/entities/lab_record.py` — LabRecord aggregate
- `domain/value_objects/lab_run_record.py` — LabRunRecord value object (no ports)
- `application/services/port_allocation_service.py` — PortAllocationService
