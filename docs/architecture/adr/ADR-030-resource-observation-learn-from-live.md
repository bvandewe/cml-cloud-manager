# ADR-030: Resource & Port Observation — "Learn from Live"

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-02-28 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-004](./ADR-004-port-allocation-per-worker.md) (Port Allocation), [ADR-017](./ADR-017-lab-operations-via-lablet-controller.md) (Lab Operations via Lablet-Controller), [ADR-020](./ADR-020-session-entity-model.md) (Session Entity Model), [ADR-029](./ADR-029-port-template-extraction-from-cml-yaml.md) (Port Template Extraction) |
| **Implementation** | [Observe Live Resources Plan](../../implementation/observe_live_resources.md) |

## Context

LabletDefinition `resource_requirements` (cpu_cores, memory_gb, storage_gb) and `port_template` are currently configured at definition-creation time — either manually or via content sync extraction from CML YAML topology files (ADR-029). However, **accurate resource consumption and actual port allocations can only be known after a lab is running on a CML worker**.

Current limitations:

1. **Resource requirements are estimates**: Operators guess CPU/memory/storage values at definition time. Over-provisioning wastes resources; under-provisioning causes failures.
2. **Port templates are derived from topology, not runtime**: `PortTemplate.from_cml_nodes()` parses node tags from the CML YAML, but CML may allocate different ports at runtime, or the topology may be modified directly on CML without LCM's knowledge.
3. **No feedback loop**: There is no mechanism to feed runtime observations back to the definition for iterative refinement.
4. **Port drift risk**: CML labs can be edited directly (e.g., via CML web UI), adding nodes or changing port assignments without LCM knowing, leading to port allocation conflicts across sessions on the same worker.

The system needs an "observe-then-record" pattern — after a lablet session runs, the lablet-controller should observe actual resource consumption and port allocations from the CML API, then POST these observations to the CPA for storage and analysis.

## Decision

### 1. Observation Timing: COLLECTING Phase + Manual Trigger

**Primary trigger**: When a `LabletSession` transitions from `RUNNING` → `COLLECTING`, the lablet-controller observes the live CML lab before any teardown begins. At this point, nodes have been running and resource consumption is representative of steady-state usage.

**Manual trigger**: An admin can request resource observation for any session in `RUNNING` state via a CPA API endpoint. CPA writes an etcd key; the lablet-controller watches for it, performs the observation, and POSTs results back. This follows the established reactive etcd pattern (ADR-023).

**Rationale**: COLLECTING is the natural boundary between "lab active" and "teardown begins". It guarantees nodes are still booted and measurable. The manual trigger supports ad-hoc characterization of definitions without waiting for the full session lifecycle.

### 2. Observation Data Flow: HTTP POST (Not CloudEvents)

```
lablet-controller                    control-plane-api
     │                                      │
     │  1. Observe CML API endpoints:       │
     │     - GET /labs/{id}/simulation_stats │
     │     - GET /labs/{id}/nodes (details)  │
     │     - GET /nodes/{id}/interfaces      │
     │                                      │
     │  2. POST /api/internal/lablet-       │
     │     sessions/{id}/resource-          │
     │     observations                     │
     │────────────────────────────────────▶  │
     │                                      │  3. Store observations on
     │                                      │     LabletSession aggregate
     │                                      │
     │                                      │  4. Compare with LabletDefinition
     │                                      │     resource_requirements + port_template
     │                                      │
     │                                      │  5. IF significant delta detected:
     │                                      │     flag definition for admin review
     │  ◀────────────── 200 OK ────────────│
```

**Rationale**: The lablet-controller already POSTs to CPA via `ControlPlaneApiClient` for all session lifecycle operations (schedule, transition, mark-ready, etc.). Adding a new `report_resource_observations()` method follows the exact same pattern. CloudEvents are reserved for external integration (ADR-003); internal service-to-service communication uses direct HTTP.

### 3. Storage on LabletSession (Not Separate Entity)

Observations are stored as new fields on the `LabletSession` aggregate state:

```python
# New fields on LabletSessionState:
observed_resources: dict | None         # Full serialized ResourceObservation
observed_ports: dict[str, int] | None   # Actual CML port allocations (runtime)
port_drift_detected: bool               # True if observed ports ≠ allocated ports
observation_count: int                  # Number of observations recorded (default 0)
observed_at: datetime | None            # Timestamp of last observation
```

**Rationale**: Observations are a property of a session execution — they belong on the session aggregate. No need for a separate entity with its own lifecycle. The session already tracks `allocated_ports` (from scheduling); adding `observed_ports` enables direct comparison.

### 4. Port Drift Detection

When observations are recorded, the CPA compares:

- **`allocated_ports`** (planned at scheduling time from `PortTemplate`) with
- **`observed_ports`** (actual CML runtime port allocations from node tags/interfaces)

If any discrepancy is found:

1. `port_drift_detected = True` is set on the session
2. A `LabletSessionPortDriftDetectedDomainEvent` is emitted
3. The event is logged and surfaced in the admin UI
4. Subsequent sessions on the same worker must account for the "leaked" ports (ports allocated by CML but not tracked by LCM)

**Rationale**: CML labs can be modified directly (bypassing LCM). Port conflicts across sessions on the same worker are a critical reliability concern. Early detection prevents cascading failures.

### 5. Definition Revision: Admin-Driven with Aggregated Observations

The system does **not** auto-apply observed resources to the LabletDefinition. Instead:

1. **Store**: Each session's observations are stored on the session itself
2. **Aggregate**: A CPA query aggregates observations across all completed sessions for a given definition (max, avg, latest values)
3. **Review**: Admin views aggregated observations in the definition detail UI
4. **Apply**: Admin manually applies revised resource requirements via the existing `update()` method on LabletDefinition

**Rationale**: Resource observations from a single session may not be representative (e.g., lab not fully loaded, network conditions, student behaviour). Admin judgment is needed to decide whether to apply the max, average, or a custom value. This avoids premature auto-tuning that could destabilize scheduling.

### 6. CML API Endpoints for Observation

| Endpoint | Data Collected | Priority |
|----------|----------------|----------|
| `GET /labs/{lab_id}/nodes` + per-node `GET /labs/{lab_id}/nodes/{node_id}` | cpu_limit, ram, node_definition, tags, state, label | **P0** |
| `GET /labs/{lab_id}/nodes/{node_id}/interfaces` | interface label, slot, state, mac, ip4 | **P0** |
| `GET /labs/{lab_id}/simulation_stats` | Runtime CPU consumption per node | **P0** |
| `GET /resource_pool_usage` | Pool-level RAM, disk, licenses | **P2** (future) |

**New methods required on `CmlLabsApiClient`**:

- `get_lab_simulation_stats(host, lab_id, ...) -> SimulationStats | None`
- `get_node_interfaces(host, lab_id, node_id, ...) -> list[InterfaceInfo]`

### 7. Observation Value Object

```python
@dataclass
class ResourceObservation:
    """Observed resource consumption from a live CML lab session."""
    observed_at: datetime
    observer: str                        # "lablet-controller" or "manual"

    # Aggregate resource consumption
    total_cpu_cores: float               # Sum of node cpu_limit values
    total_memory_mb: int                 # Sum of node RAM allocations
    total_storage_mb: int | None         # From resource_pool_usage (future)

    # Node-level detail
    nodes: list[NodeObservation]
    actual_node_count: int
    node_definitions_used: list[str]     # e.g. ["iosv", "csr1000v"]

    # Port observations (actual runtime ports from node tags)
    observed_ports: dict[str, int]       # e.g. {"PC_serial": 5041, "PC_vnc": 5044}

    # Simulation stats (runtime metrics)
    simulation_stats: dict | None        # Raw simulation_stats response


@dataclass
class NodeObservation:
    """Per-node resource observation."""
    node_id: str
    label: str
    node_definition: str
    state: str                           # "BOOTED", "STOPPED", etc.
    cpu_limit: int | None
    ram_mb: int | None
    tags: list[str]
    interfaces: list[InterfaceObservation]


@dataclass
class InterfaceObservation:
    """Per-interface observation."""
    interface_id: str
    label: str
    slot: int
    state: str
    mac_address: str | None
    ip4: list[str]
```

## Rationale

### Why POST (not CloudEvents)?

- Internal service-to-service communication in LCM uses direct HTTP via `ControlPlaneApiClient` (established pattern)
- CloudEvents are for external integration boundaries (ADR-003)
- The lablet-controller already has 20+ POST methods to CPA — adding one more is consistent

### Why store on LabletSession (not a separate observation entity)?

- An observation is intrinsically tied to a session execution — it has no independent lifecycle
- Keeps the data model simple: one query on `LabletSession` returns both planned and observed resources
- Avoids entity proliferation for what is essentially metadata on an existing concept

### Why admin-driven revision (not auto-apply)?

- Single observations may be unrepresentative (partial boot, student load variance)
- Admin can aggregate across sessions and apply professional judgment
- Avoids the complexity of confidence scoring, quorum thresholds, and rollback logic
- MVP approach: ship observation + aggregation first, consider auto-apply later

### Why observe at COLLECTING (not RUNNING start)?

- At COLLECTING, nodes have been running for the session duration — resource consumption is representative
- Observing at lab start would capture boot-time resource spikes, not steady-state
- The COLLECTING phase is already the natural "wrap up" boundary in the session lifecycle
- The manual trigger covers the case where an admin wants to observe during RUNNING

## Consequences

### Positive

- First feedback loop from runtime to definition — enables iterative resource refinement
- Port drift detection prevents cascading port allocation conflicts
- No changes to the scheduler — it continues using LabletDefinition's resource_requirements as-is
- Admin retains full control over when and how to apply observed resources
- Observation data enables future analytics (resource utilization reports, cost optimization)

### Negative

- Adds complexity to the lablet-controller (new CML API calls, observation assembly)
- LabletSession state grows with observation data (mitigated: observations are nullable, only stored when collected)
- Requires new CML API client methods (simulation_stats, node interfaces)

### Risks

- CML API may not return simulation_stats for all lab configurations (mitigated: observation is best-effort, missing data is recorded as null)
- Observation adds latency to the COLLECTING transition (mitigated: observation is non-blocking for the session lifecycle — failure to observe does not block teardown)
- Port drift detection may produce false positives if CML reorders ports (mitigated: comparison uses port name mapping, not positional ordering)

## Implementation Notes

### Cross-Service Changes

| Service | Changes |
|---------|---------|
| **lcm-core** | New `ResourceObservation`, `NodeObservation`, `InterfaceObservation` dataclasses in shared domain |
| **lablet-controller** | New CML API methods (`get_lab_simulation_stats`, `get_node_interfaces`), observation assembly logic, `report_resource_observations()` on `ControlPlaneApiClient` |
| **control-plane-api** | New domain event (`LabletSessionResourcesObservedDomainEvent`, `LabletSessionPortDriftDetectedDomainEvent`), new command (`RecordResourceObservationCommand`), new internal API endpoint, new query for aggregated observations, UI panel on definition detail page |
| **resource-scheduler** | No changes (continues using LabletDefinition resource_requirements) |

### Observation Trigger Sequence

```
lablet-controller reconciler:
  _handle_running():
    IF timeslot expired:
      1. observe_lab_resources(session, worker)    ← NEW
      2. transition_session(COLLECTING)
      3. POST observations to CPA

Manual trigger:
  Admin → CPA API: POST /api/lablet-sessions/{id}/observe-resources
    → CPA writes etcd key: /lcm/sessions/{id}/observe_resources
    → lablet-controller watches, performs observation, POSTs results
    → CPA deletes etcd key
```

## Related Documents

- [Observe Live Resources Implementation Plan](../../implementation/observe_live_resources.md)
- [ADR-004: Port Allocation per Worker](./ADR-004-port-allocation-per-worker.md)
- [ADR-029: Port Template Extraction from CML YAML](./ADR-029-port-template-extraction-from-cml-yaml.md)
- `domain/value_objects/resource_requirements.py` — ResourceRequirements value object
- `domain/value_objects/port_template.py` — PortTemplate value object
- `domain/entities/lablet_session.py` — LabletSession aggregate
