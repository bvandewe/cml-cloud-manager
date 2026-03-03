# Resource & Port Observation — "Learn from Live" Implementation Plan

**Status**: ✅ Complete
**Created**: 2026-02-28
**Last Updated**: 2026-02-28
**Author**: AI Architect (lcm-senior-architect)
**ADR**: [ADR-030](../architecture/adr/ADR-030-resource-observation-learn-from-live.md)
**Scope**: End-to-end resource and port observation — from CML runtime introspection in lablet-controller through CPA storage, admin review UI, and definition revision workflow.

---

## Implementation Progress

| Phase | Scope | Status | Completed |
|-------|-------|--------|-----------|
| **Phase 1** | Shared domain model (lcm-core value objects + event schemas) | ✅ Complete | 2026-02-28 |
| **Phase 2** | CPA domain changes (LabletSession aggregate + events + command) | ✅ Complete | 2026-02-28 |
| **Phase 3** | CPA internal API endpoint + query for aggregated observations | ✅ Complete | 2026-02-28 |
| **Phase 4** | lablet-controller CML API extensions (simulation_stats, interfaces) | ✅ Complete | 2026-02-28 |
| **Phase 5** | lablet-controller observation assembly + POST to CPA | ✅ Complete | 2026-02-28 |
| **Phase 6** | Manual observation trigger (CPA command + etcd + lablet-controller watch) | ✅ Complete | 2026-02-28 |
| **Phase 7** | CPA admin API (external endpoints for definition resource review) | ✅ Complete | 2026-02-28 |
| **Phase 8** | Frontend — observation panel on definition detail + session detail | ✅ Complete | 2026-02-28 |
| **Phase 9** | Tests (lcm-core 16, CPA domain 11, CPA commands 9, CPA query 8, LC observer 8 = **52 tests**) | ✅ Complete | 2026-02-28 |
| **Phase 10** | Documentation & configuration | ✅ Complete | 2026-02-28 |

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture Decision Summary](#2-architecture-decision-summary)
3. [Phase 1: Shared Domain Model (lcm-core)](#3-phase-1-shared-domain-model-lcm-core)
4. [Phase 2: CPA Domain Changes](#4-phase-2-cpa-domain-changes)
5. [Phase 3: CPA Internal API](#5-phase-3-cpa-internal-api)
6. [Phase 4: lablet-controller CML API Extensions](#6-phase-4-lablet-controller-cml-api-extensions)
7. [Phase 5: lablet-controller Observation + POST](#7-phase-5-lablet-controller-observation--post)
8. [Phase 6: Manual Observation Trigger](#8-phase-6-manual-observation-trigger)
9. [Phase 7: CPA Admin API](#9-phase-7-cpa-admin-api)
10. [Phase 8: Frontend](#10-phase-8-frontend)
11. [Phase 9: Tests](#11-phase-9-tests)
12. [Phase 10: Documentation](#12-phase-10-documentation)
13. [Appendix A: CML API Reference](#appendix-a-cml-api-reference)
14. [Appendix B: Data Flow Diagram](#appendix-b-data-flow-diagram)
15. [Appendix C: File Index](#appendix-c-file-index)

---

## 1. Overview

### 1.1 Problem Statement

LabletDefinition `resource_requirements` (cpu_cores, memory_gb, storage_gb) and `port_template` are configured at definition-creation time as estimates or derived from CML YAML topology (ADR-029). Accurate values can only be known after a lab session runs on CML. Additionally, CML labs may be edited directly (bypassing LCM), causing port allocation drift that can lead to conflicts across sessions on the same worker.

### 1.2 Solution — "Learn from Live"

An observe-then-record pattern:

1. **Create** definitions with defaults/estimates (status quo)
2. **Run** a lablet session (existing lifecycle)
3. **Observe** (at COLLECTING phase or manual trigger): lablet-controller queries CML runtime APIs for actual resource consumption and port allocations
4. **Record**: lablet-controller POSTs observations to CPA via `ControlPlaneApiClient`
5. **Store**: CPA stores observations on the `LabletSession` aggregate and detects port drift
6. **Aggregate**: CPA provides a query aggregating observations across sessions for a given definition
7. **Review & Apply**: Admin reviews aggregated observations in the UI and manually applies revised resource requirements to the definition

### 1.3 High-Level Data Flow

```
┌─────────────────────────┐     ┌──────────────────────────┐     ┌──────────────┐
│   lablet-controller     │     │   control-plane-api      │     │    Admin UI   │
│                         │     │                          │     │              │
│ COLLECTING trigger      │     │                          │     │              │
│ OR manual etcd watch    │     │                          │     │              │
│         │               │     │                          │     │              │
│         ▼               │     │                          │     │              │
│ CML API observations:   │     │                          │     │              │
│  - simulation_stats     │     │                          │     │              │
│  - node details + tags  │     │                          │     │              │
│  - node interfaces      │     │                          │     │              │
│         │               │     │                          │     │              │
│         ▼               │     │                          │     │              │
│ Assemble observation ───┼────▶│ Store on LabletSession   │     │              │
│ POST /internal/sessions │     │ Detect port drift        │     │              │
│   /{id}/resource-       │     │ Emit domain events       │     │              │
│   observations          │     │         │                │     │              │
│                         │     │         ▼                │     │              │
│                         │     │ Query: aggregate by      │     │              │
│                         │     │ definition_id ───────────┼────▶│ Review panel │
│                         │     │                          │     │ on def detail│
│                         │     │                          │     │              │
│                         │     │ Admin: "Apply observed"  │◀────┤ Apply button │
│                         │     │ → update() on definition │     │              │
└─────────────────────────┘     └──────────────────────────┘     └──────────────┘
```

### 1.4 Key Context for Future Coding Sessions

**Established patterns this plan follows:**

| Pattern | Reference | Usage in this plan |
|---------|-----------|-------------------|
| Self-contained command+handler | `application/commands/transition_session_command.py` | New `RecordResourceObservationCommand` |
| ControlPlaneApiClient POST | `lcm_core/integration/control_plane_api_client.py` → `transition_session()` | New `report_resource_observations()` |
| Internal API controller | `api/controllers/internal_sessions_controller.py` | New endpoint on same controller |
| EtcdProjector (reactive trigger) | `infrastructure/projectors/lablet_session_etcd_projectors.py` | New `ObserveResourcesRequestedEtcdProjector` |
| CmlLabsApiClient HTTP calls | `integration/services/cml_labs_api_client.py` → `get_lab_nodes()` | New `get_lab_simulation_stats()`, `get_node_interfaces()` |
| Reconciler handler | `lablet_reconciler.py` → `_handle_running()` | Modified to add observation before COLLECTING transition |
| Domain event + state handler | `domain/events/lablet_session_events.py` + `@dispatch` in aggregate | New `LabletSessionResourcesObservedDomainEvent` |
| Value object (frozen dataclass) | `domain/value_objects/resource_requirements.py` | New `ResourceObservation`, `NodeObservation`, `InterfaceObservation` |

**Key file locations:**

| Component | File | Purpose |
|-----------|------|---------|
| LabletSession aggregate | `control-plane-api/domain/entities/lablet_session.py` | Add observation fields + methods |
| LabletSession events | `control-plane-api/domain/events/lablet_session_events.py` | Add observation events |
| Session commands | `control-plane-api/application/commands/` | New command file |
| Internal sessions controller | `control-plane-api/api/controllers/internal_sessions_controller.py` | New endpoint |
| CML labs client | `lablet-controller/integration/services/cml_labs_api_client.py` | New CML API methods |
| Lablet reconciler | `lablet-controller/application/hosted_services/lablet_reconciler.py` | Modified `_handle_running()` |
| CPA API client | `core/lcm_core/integration/control_plane_api_client.py` | New `report_resource_observations()` |
| Shared domain | `core/lcm_core/domain/` | New value objects |

---

## 2. Architecture Decision Summary

> Full ADR: [ADR-030](../architecture/adr/ADR-030-resource-observation-learn-from-live.md)

| Code | Decision | Rationale |
|------|----------|-----------|
| AD-OLR-001 | Observe at COLLECTING phase + manual trigger | Nodes are booted and representative; manual trigger for ad-hoc |
| AD-OLR-002 | HTTP POST via ControlPlaneApiClient (not CloudEvents) | Follows established internal service-to-service pattern |
| AD-OLR-003 | Store observations on LabletSession aggregate | Observations are a property of session execution, not an independent entity |
| AD-OLR-004 | Port drift detection: compare allocated_ports vs observed_ports | CML may be edited directly; detect conflicts early |
| AD-OLR-005 | Admin-driven definition revision via aggregated observations | Single observations may be unrepresentative; admin judgment needed |
| AD-OLR-006 | CML API: simulation_stats + node details + interfaces | Comprehensive runtime data at P0 priority |
| AD-OLR-007 | Manual trigger via reactive etcd watch (follows AD-023 pattern) | Consistent with content sync trigger architecture |

---

## 3. Phase 1: Shared Domain Model (lcm-core)

> **Scope**: Value objects in `lcm-core` for cross-service use (lablet-controller constructs, CPA stores).

### 3.1 Add `InterfaceObservation` Value Object

**File**: `src/core/lcm_core/domain/value_objects/interface_observation.py` _(new)_

```python
"""Interface observation value object — observed CML node interface at runtime."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InterfaceObservation:
    """Observed state of a single CML node interface during a live session.

    Captures the runtime interface configuration including IP addresses
    assigned by DHCP or static config — data only available when the lab is booted.
    """

    interface_id: str           # CML interface ID
    label: str                  # Interface label (e.g., "GigabitEthernet0/0")
    slot: int                   # Interface slot number
    state: str                  # "UP", "DOWN", etc.
    mac_address: str | None     # MAC address if available
    ip4: tuple[str, ...]        # L3 IPv4 addresses (may be empty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface_id": self.interface_id,
            "label": self.label,
            "slot": self.slot,
            "state": self.state,
            "mac_address": self.mac_address,
            "ip4": list(self.ip4),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "InterfaceObservation":
        return InterfaceObservation(
            interface_id=data["interface_id"],
            label=data["label"],
            slot=data.get("slot", 0),
            state=data.get("state", "UNKNOWN"),
            mac_address=data.get("mac_address"),
            ip4=tuple(data.get("ip4", [])),
        )
```

### 3.2 Add `NodeObservation` Value Object

**File**: `src/core/lcm_core/domain/value_objects/node_observation.py` _(new)_

```python
"""Node observation value object — observed CML node resource usage at runtime."""

from dataclasses import dataclass
from typing import Any

from lcm_core.domain.value_objects.interface_observation import InterfaceObservation


@dataclass(frozen=True)
class NodeObservation:
    """Observed state of a single CML node during a live session.

    Captures the runtime resource allocation (cpu_limit, ram), node
    definition, tags (which encode port mappings), and interface details.
    """

    node_id: str                              # CML node ID
    label: str                                # Node label (e.g., "PC", "iosv-0")
    node_definition: str                      # Node definition name (e.g., "iosv", "csr1000v")
    state: str                                # "BOOTED", "STOPPED", etc.
    cpu_limit: int | None                     # CPU limit assigned to this node
    ram_mb: int | None                        # RAM in MB assigned to this node
    tags: tuple[str, ...]                     # Raw CML tags (e.g., ("serial:5041", "vnc:5044"))
    interfaces: tuple[InterfaceObservation, ...]  # Observed interfaces

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "node_definition": self.node_definition,
            "state": self.state,
            "cpu_limit": self.cpu_limit,
            "ram_mb": self.ram_mb,
            "tags": list(self.tags),
            "interfaces": [i.to_dict() for i in self.interfaces],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "NodeObservation":
        return NodeObservation(
            node_id=data["node_id"],
            label=data["label"],
            node_definition=data.get("node_definition", ""),
            state=data.get("state", "UNKNOWN"),
            cpu_limit=data.get("cpu_limit"),
            ram_mb=data.get("ram_mb"),
            tags=tuple(data.get("tags", [])),
            interfaces=tuple(InterfaceObservation.from_dict(i) for i in data.get("interfaces", [])),
        )
```

### 3.3 Add `ResourceObservation` Value Object

**File**: `src/core/lcm_core/domain/value_objects/resource_observation.py` _(new)_

```python
"""Resource observation value object — aggregated runtime resource snapshot."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from lcm_core.domain.value_objects.node_observation import NodeObservation


@dataclass(frozen=True)
class ResourceObservation:
    """Aggregated resource observation from a live CML lab session.

    Assembled by the lablet-controller from multiple CML API calls
    (node details, interfaces, simulation_stats) and POSTed to CPA
    for storage on the LabletSession aggregate.

    The observed_ports dict maps PortTemplate-style names to actual
    CML-assigned port numbers (e.g., {"PC_serial": 5041, "PC_vnc": 5044}).
    This enables drift detection against allocated_ports.
    """

    observed_at: datetime                     # When the observation was taken
    observer: str                             # "lablet-controller" or "admin:{user_id}"

    # Aggregate resource consumption
    total_cpu_cores: float                    # Sum of node cpu_limit values
    total_memory_mb: int                      # Sum of node RAM allocations
    total_storage_mb: int | None              # From resource_pool_usage (future, P2)

    # Node-level detail
    nodes: tuple[NodeObservation, ...]        # Per-node observations
    actual_node_count: int                    # Count of observed nodes
    node_definitions_used: tuple[str, ...]    # Unique node definition names

    # Port observations (actual runtime port allocations from node tags)
    observed_ports: dict[str, int]            # {port_name: port_number}

    # Simulation stats (runtime CPU/memory metrics — raw CML response)
    simulation_stats: dict[str, Any] | None   # Raw simulation_stats if available

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at.isoformat(),
            "observer": self.observer,
            "total_cpu_cores": self.total_cpu_cores,
            "total_memory_mb": self.total_memory_mb,
            "total_storage_mb": self.total_storage_mb,
            "nodes": [n.to_dict() for n in self.nodes],
            "actual_node_count": self.actual_node_count,
            "node_definitions_used": list(self.node_definitions_used),
            "observed_ports": self.observed_ports,
            "simulation_stats": self.simulation_stats,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ResourceObservation":
        observed_at = data["observed_at"]
        if isinstance(observed_at, str):
            observed_at = datetime.fromisoformat(observed_at)
        return ResourceObservation(
            observed_at=observed_at,
            observer=data.get("observer", "lablet-controller"),
            total_cpu_cores=data.get("total_cpu_cores", 0.0),
            total_memory_mb=data.get("total_memory_mb", 0),
            total_storage_mb=data.get("total_storage_mb"),
            nodes=tuple(NodeObservation.from_dict(n) for n in data.get("nodes", [])),
            actual_node_count=data.get("actual_node_count", 0),
            node_definitions_used=tuple(data.get("node_definitions_used", [])),
            observed_ports=dict(data.get("observed_ports", {})),
            simulation_stats=data.get("simulation_stats"),
        )
```

### 3.4 Export from `lcm_core.domain.value_objects`

**File**: `src/core/lcm_core/domain/value_objects/__init__.py` _(modify)_

Add exports for the three new value objects.

### 3.5 Verification

- [ ] All three value objects are frozen dataclasses with `to_dict()` / `from_dict()` serialization
- [ ] Round-trip test: `from_dict(obj.to_dict()) == obj` for each value object
- [ ] lcm-core tests pass: `cd src/core && poetry run pytest`

---

## 4. Phase 2: CPA Domain Changes

> **Scope**: LabletSession aggregate — new state fields, domain events, and aggregate methods.

### 4.1 Add New Domain Events

**File**: `src/control-plane-api/domain/events/lablet_session_events.py` _(modify)_

Add two new events after the existing events:

```python
@cloudevent("lablet_session.resources_observed.v1")
@dataclass
class LabletSessionResourcesObservedDomainEvent(DomainEvent):
    """Event raised when runtime resource observations are recorded.

    Does NOT change session status — this is a data-enrichment event.
    Can occur during RUNNING or COLLECTING states.
    """

    aggregate_id: str
    observed_resources: dict          # Serialized ResourceObservation
    observed_ports: dict[str, int]    # Actual CML port allocations
    port_drift_detected: bool         # True if observed ≠ allocated
    observed_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        observed_resources: dict,
        observed_ports: dict[str, int],
        port_drift_detected: bool,
        observed_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.observed_resources = observed_resources
        self.observed_ports = observed_ports
        self.port_drift_detected = port_drift_detected
        self.observed_at = observed_at


@cloudevent("lablet_session.port_drift_detected.v1")
@dataclass
class LabletSessionPortDriftDetectedDomainEvent(DomainEvent):
    """Event raised when observed ports differ from allocated ports.

    This is a separate event from ResourcesObserved to allow independent
    handling (e.g., alerting, worker port reconciliation).
    """

    aggregate_id: str
    allocated_ports: dict[str, int]   # Planned ports from scheduling
    observed_ports: dict[str, int]    # Actual CML ports at runtime
    drift_details: dict[str, Any]     # {"added": {...}, "removed": {...}, "changed": {...}}
    detected_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        allocated_ports: dict[str, int],
        observed_ports: dict[str, int],
        drift_details: dict[str, Any],
        detected_at: datetime,
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.allocated_ports = allocated_ports
        self.observed_ports = observed_ports
        self.drift_details = drift_details
        self.detected_at = detected_at
```

### 4.2 Add State Fields to `LabletSessionState`

**File**: `src/control-plane-api/domain/entities/lablet_session.py` _(modify)_

Add to `LabletSessionState` class definition (field annotations) and `__init__`:

```python
# New field annotations on LabletSessionState:
observed_resources: dict | None           # Serialized ResourceObservation
observed_ports: dict[str, int] | None     # Actual CML port allocations at runtime
port_drift_detected: bool                 # True if observed ports ≠ allocated ports
observation_count: int                    # Number of observations recorded
observed_at: datetime | None              # Timestamp of last observation

# In __init__():
self.observed_resources = None
self.observed_ports = None
self.port_drift_detected = False
self.observation_count = 0
self.observed_at = None
```

### 4.3 Add `@dispatch` Handlers on `LabletSessionState`

```python
@dispatch(LabletSessionResourcesObservedDomainEvent)
def on(self, event: LabletSessionResourcesObservedDomainEvent) -> None:
    """Apply the resource observation event to the state."""
    self.observed_resources = event.observed_resources
    self.observed_ports = event.observed_ports
    self.port_drift_detected = event.port_drift_detected
    self.observation_count += 1
    self.observed_at = event.observed_at
    self.updated_at = event.observed_at
```

### 4.4 Add Aggregate Method on `LabletSession`

```python
def record_resource_observation(
    self,
    observed_resources: dict,
    observed_ports: dict[str, int],
) -> None:
    """Record runtime resource observations from CML.

    Compares observed_ports against allocated_ports to detect drift.
    Emits LabletSessionResourcesObservedDomainEvent always.
    Additionally emits LabletSessionPortDriftDetectedDomainEvent if drift found.

    Args:
        observed_resources: Serialized ResourceObservation dict
        observed_ports: Actual CML port allocations {port_name: port_number}
    """
    now = datetime.now(timezone.utc)

    # Detect port drift
    allocated = self.state.allocated_ports or {}
    drift_detected = False
    drift_details: dict[str, Any] = {"added": {}, "removed": {}, "changed": {}}

    if allocated and observed_ports:
        allocated_set = set(allocated.keys())
        observed_set = set(observed_ports.keys())

        # Ports in CML but not in LCM allocation
        for name in observed_set - allocated_set:
            drift_details["added"][name] = observed_ports[name]
            drift_detected = True

        # Ports in LCM allocation but not in CML
        for name in allocated_set - observed_set:
            drift_details["removed"][name] = allocated[name]
            drift_detected = True

        # Ports present in both but with different port numbers
        for name in allocated_set & observed_set:
            if allocated[name] != observed_ports[name]:
                drift_details["changed"][name] = {
                    "allocated": allocated[name],
                    "observed": observed_ports[name],
                }
                drift_detected = True

    # Always emit the observation event
    self.state.on(
        self.register_event(
            LabletSessionResourcesObservedDomainEvent(
                aggregate_id=self.id(),
                observed_resources=observed_resources,
                observed_ports=observed_ports,
                port_drift_detected=drift_detected,
                observed_at=now,
            )
        )
    )

    # Emit drift event if detected
    if drift_detected:
        self.state.on(
            self.register_event(
                LabletSessionPortDriftDetectedDomainEvent(
                    aggregate_id=self.id(),
                    allocated_ports=allocated,
                    observed_ports=observed_ports,
                    drift_details=drift_details,
                    detected_at=now,
                )
            )
        )
```

### 4.5 Verification

- [ ] New events follow `@cloudevent` + `@dataclass` + `DomainEvent` pattern (match `LabletSessionCollectingDomainEvent`)
- [ ] New `@dispatch` handler on state follows existing pattern
- [ ] `record_resource_observation()` follows aggregate method pattern (match `start_collection()`)
- [ ] Port drift detection covers added/removed/changed scenarios
- [ ] CPA tests pass: `cd src/control-plane-api && poetry run pytest`

---

## 5. Phase 3: CPA Internal API

> **Scope**: New CPA command, internal controller endpoint, and aggregation query.

### 5.1 Add `RecordResourceObservationCommand`

**File**: `src/control-plane-api/application/commands/record_resource_observation_command.py` _(new)_

Self-contained command + handler following the established pattern (reference: `transition_session_command.py`):

```python
"""Record resource observations from a live CML lab session.

Self-contained command + handler (established CQRS pattern).
Called by lablet-controller via internal API after CML runtime introspection.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from neuroglia.mediation import Command, CommandHandler

from application.commands.command_handler_base import CommandHandlerBase
from domain.entities.lablet_session import LabletSession

logger = logging.getLogger(__name__)


@dataclass
class RecordResourceObservationCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to record resource observations on a LabletSession."""

    session_id: str
    observed_resources: dict          # Serialized ResourceObservation
    observed_ports: dict[str, int]    # Actual CML port allocations


class RecordResourceObservationCommandHandler(
    CommandHandlerBase,
    CommandHandler[RecordResourceObservationCommand, OperationResult[dict[str, Any]]],
):
    def __init__(self, mediator, mapper, cloud_event_bus, cloud_event_publishing_options, lablet_session_repository):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._session_repository = lablet_session_repository

    async def handle_async(self, request, cancellation_token=None):
        session = await self._session_repository.get_by_id_async(request.session_id, cancellation_token)
        if not session:
            return self.not_found("LabletSession", request.session_id)

        # Validate session is in an observable state
        from domain.enums import LabletSessionStatus

        observable_states = {LabletSessionStatus.RUNNING, LabletSessionStatus.COLLECTING}
        if session.state.status not in observable_states:
            return self.bad_request(
                f"Cannot record observations for session in '{session.state.status}' state. "
                f"Session must be in {[s.value for s in observable_states]}"
            )

        # Record the observation (drift detection happens inside aggregate)
        session.record_resource_observation(
            observed_resources=request.observed_resources,
            observed_ports=request.observed_ports,
        )

        await self._session_repository.update_async(session, cancellation_token)

        drift = session.state.port_drift_detected
        if drift:
            logger.warning(f"Port drift detected for session {request.session_id}")

        return self.ok({
            "session_id": request.session_id,
            "observation_count": session.state.observation_count,
            "port_drift_detected": drift,
            "observed_at": session.state.observed_at.isoformat() if session.state.observed_at else None,
        })
```

### 5.2 Add Internal API Endpoint

**File**: `src/control-plane-api/api/controllers/internal_sessions_controller.py` _(modify)_

Add a new request model and endpoint:

```python
# New request model (add alongside existing models):
class RecordResourceObservationRequest(BaseModel):
    observed_resources: dict
    observed_ports: dict[str, int] = {}

# New endpoint (add to InternalLabletSessionsController):
@router.post("/{session_id}/resource-observations")
async def record_resource_observations(
    self,
    session_id: str,
    request: RecordResourceObservationRequest,
    _api_key: str = Depends(verify_internal_api_key),
) -> dict:
    result = await self.mediator.execute_async(
        RecordResourceObservationCommand(
            session_id=session_id,
            observed_resources=request.observed_resources,
            observed_ports=request.observed_ports,
        )
    )
    return self.process(result)
```

### 5.3 Add Aggregated Observations Query

**File**: `src/control-plane-api/application/queries/get_definition_resource_observations_query.py` _(new)_

Self-contained query + handler that aggregates observations across all sessions for a given definition:

```python
"""Query to aggregate resource observations across sessions for a given definition.

Returns max, average, and latest observed resources — enabling admin
to make informed decisions about definition resource_requirements updates.
"""

import logging
from dataclasses import dataclass
from typing import Any

from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class GetDefinitionResourceObservationsQuery(Query[OperationResult[dict[str, Any]]]):
    """Query for aggregated resource observations by definition_id."""

    definition_id: str
    limit: int = 20  # Max sessions to include


class GetDefinitionResourceObservationsQueryHandler(
    QueryHandler[GetDefinitionResourceObservationsQuery, OperationResult[dict[str, Any]]],
):
    def __init__(self, lablet_session_repository):
        self._session_repository = lablet_session_repository

    async def handle_async(self, request, cancellation_token=None):
        # Fetch sessions with observations for this definition
        sessions = await self._session_repository.find_with_observations_async(
            definition_id=request.definition_id,
            limit=request.limit,
            cancellation_token=cancellation_token,
        )

        if not sessions:
            return self.ok({
                "definition_id": request.definition_id,
                "observation_count": 0,
                "sessions": [],
                "aggregate": None,
            })

        # Aggregate observations
        cpu_values = []
        memory_values = []
        storage_values = []
        node_counts = []
        port_drift_count = 0

        session_summaries = []
        for session in sessions:
            obs = session.state.observed_resources
            if obs:
                cpu_values.append(obs.get("total_cpu_cores", 0))
                memory_values.append(obs.get("total_memory_mb", 0))
                if obs.get("total_storage_mb") is not None:
                    storage_values.append(obs["total_storage_mb"])
                node_counts.append(obs.get("actual_node_count", 0))

            if session.state.port_drift_detected:
                port_drift_count += 1

            session_summaries.append({
                "session_id": session.id(),
                "observed_at": session.state.observed_at.isoformat() if session.state.observed_at else None,
                "total_cpu_cores": obs.get("total_cpu_cores") if obs else None,
                "total_memory_mb": obs.get("total_memory_mb") if obs else None,
                "actual_node_count": obs.get("actual_node_count") if obs else None,
                "port_drift_detected": session.state.port_drift_detected,
                "observation_count": session.state.observation_count,
            })

        aggregate = {
            "cpu_cores": {
                "max": max(cpu_values) if cpu_values else None,
                "avg": sum(cpu_values) / len(cpu_values) if cpu_values else None,
                "latest": cpu_values[-1] if cpu_values else None,
            },
            "memory_mb": {
                "max": max(memory_values) if memory_values else None,
                "avg": sum(memory_values) / len(memory_values) if memory_values else None,
                "latest": memory_values[-1] if memory_values else None,
            },
            "storage_mb": {
                "max": max(storage_values) if storage_values else None,
                "avg": sum(storage_values) / len(storage_values) if storage_values else None,
                "latest": storage_values[-1] if storage_values else None,
            } if storage_values else None,
            "node_count": {
                "max": max(node_counts) if node_counts else None,
                "avg": sum(node_counts) / len(node_counts) if node_counts else None,
                "latest": node_counts[-1] if node_counts else None,
            },
            "port_drift_sessions": port_drift_count,
        }

        return self.ok({
            "definition_id": request.definition_id,
            "observation_count": len(sessions),
            "sessions": session_summaries,
            "aggregate": aggregate,
        })
```

### 5.4 Add Repository Method

**File**: `src/control-plane-api/domain/repositories/lablet_session_repository.py` _(modify)_

Add abstract method:

```python
async def find_with_observations_async(
    self, definition_id: str, limit: int = 20, cancellation_token=None
) -> list[LabletSession]:
    """Find sessions with resource observations for a given definition."""
    ...
```

**File**: `src/control-plane-api/integration/repositories/mongo_lablet_session_repository.py` _(modify)_

Implement with MongoDB query:

```python
async def find_with_observations_async(
    self, definition_id: str, limit: int = 20, cancellation_token=None
) -> list[LabletSession]:
    """Find sessions with resource observations, sorted by observed_at desc."""
    cursor = self._collection.find(
        {
            "state.definition_id": definition_id,
            "state.observed_resources": {"$ne": None},
        }
    ).sort("state.observed_at", -1).limit(limit)

    results = []
    async for doc in cursor:
        session = self._deserialize(doc)
        results.append(session)
    return results
```

### 5.5 Verification

- [ ] Command follows self-contained pattern (command + handler in one file)
- [ ] Handler uses `CommandHandlerBase` + `CommandHandler` dual inheritance
- [ ] Handler uses `self.ok()`, `self.not_found()`, `self.bad_request()` helper methods
- [ ] Internal API endpoint uses `verify_internal_api_key` dependency
- [ ] Query follows self-contained pattern (query + handler in one file)
- [ ] Repository method has abstract definition + MongoDB implementation
- [ ] CPA tests pass: `cd src/control-plane-api && poetry run pytest`

---

## 6. Phase 4: lablet-controller CML API Extensions

> **Scope**: New methods on `CmlLabsApiClient` for runtime introspection.

### 6.1 Add `SimulationStats` Data Class

**File**: `src/lablet-controller/integration/services/cml_labs_api_client.py` _(modify)_

Add after existing data classes:

```python
@dataclass
class SimulationStats:
    """CML lab simulation statistics — runtime resource metrics."""

    lab_id: str
    nodes: list[dict[str, Any]]       # Per-node simulation data (CPU, state, etc.)
    links: list[dict[str, Any]]       # Per-link simulation data
    raw: dict[str, Any]               # Full raw response for future use
```

### 6.2 Add `get_lab_simulation_stats()` Method

```python
async def get_lab_simulation_stats(
    self,
    host: str,
    lab_id: str,
    username: str | None = None,
    password: str | None = None,
) -> SimulationStats | None:
    """Get runtime simulation statistics for a lab.

    CML API: GET /api/v0/labs/{lab_id}/simulation_stats

    Returns per-node CPU consumption and link state.
    Only available when the lab is in BOOTED state.
    """
    url = f"https://{host}/api/v0/labs/{lab_id}/simulation_stats"
    response = await self._authenticated_request("GET", url, username, password)
    if response is None:
        return None
    return SimulationStats(
        lab_id=lab_id,
        nodes=response.get("nodes", []),
        links=response.get("links", []),
        raw=response,
    )
```

### 6.3 Add `get_node_interfaces()` Method

```python
async def get_node_interfaces(
    self,
    host: str,
    lab_id: str,
    node_id: str,
    username: str | None = None,
    password: str | None = None,
) -> list[InterfaceInfo]:
    """Get interfaces for a specific node.

    CML API: GET /api/v0/labs/{lab_id}/nodes/{node_id}/interfaces

    Returns interface details including IP addresses (only available
    when node is booted).
    """
    url = f"https://{host}/api/v0/labs/{lab_id}/nodes/{node_id}/interfaces"
    response = await self._authenticated_request("GET", url, username, password)
    if response is None:
        return []

    interfaces = []
    # Response is a list of interface IDs — need to fetch each
    for iface_id in response:
        iface_url = f"https://{host}/api/v0/labs/{lab_id}/interfaces/{iface_id}"
        iface_data = await self._authenticated_request("GET", iface_url, username, password)
        if iface_data:
            interfaces.append(InterfaceInfo(
                id=str(iface_id),
                label=iface_data.get("label", ""),
                node_id=node_id,
                slot=iface_data.get("slot"),
                state=iface_data.get("state"),
                mac_address=iface_data.get("mac_address"),
                ip4=iface_data.get("ip4", []),
            ))
    return interfaces
```

### 6.4 Verification

- [ ] New methods follow existing pattern (`_authenticated_request()` with retry)
- [ ] Data classes use `@dataclass` pattern matching `LabInfo`, `NodeInfo`
- [ ] Error handling: return `None` / empty list on failure (don't raise)
- [ ] lablet-controller tests pass: `cd src/lablet-controller && poetry run pytest`

---

## 7. Phase 5: lablet-controller Observation + POST

> **Scope**: Observation assembly logic in lablet-controller and POST to CPA.

### 7.1 Add `observe_lab_resources()` Service Method

**File**: `src/lablet-controller/application/services/resource_observer.py` _(new)_

```python
"""Resource observation service — observes live CML lab resources.

Queries CML API for runtime resource consumption, port allocations,
and simulation statistics, then assembles a ResourceObservation.

AD-OLR-006: Uses simulation_stats + node details + interfaces.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from lcm_core.domain.value_objects.interface_observation import InterfaceObservation
from lcm_core.domain.value_objects.node_observation import NodeObservation
from lcm_core.domain.value_objects.resource_observation import ResourceObservation

from integration.services.cml_labs_api_client import CmlLabsApiClient

logger = logging.getLogger(__name__)

# Same protocols as PortTemplate (ADR-029)
CML_TCP_PROTOCOLS = frozenset({"serial", "vnc", "ssh", "telnet", "tcp", "http", "https"})
TAG_PATTERN = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*):(\d+)$")


class ResourceObserver:
    """Observes live CML lab resources and assembles ResourceObservation."""

    def __init__(self, cml_labs_client: CmlLabsApiClient):
        self._cml = cml_labs_client

    async def observe(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
        observer: str = "lablet-controller",
    ) -> ResourceObservation | None:
        """Observe resource consumption for a running CML lab.

        Queries:
        1. GET /labs/{id}/nodes (+ per-node detail) → cpu_limit, ram, tags
        2. GET /labs/{id}/nodes/{nid}/interfaces → interface details
        3. GET /labs/{id}/simulation_stats → runtime CPU metrics

        Returns None if observation fails entirely (e.g., lab not accessible).
        Partial failures (e.g., simulation_stats unavailable) are tolerated.
        """
        try:
            # 1. Get all nodes with details
            nodes = await self._cml.get_lab_nodes(host, lab_id, username, password)
            if not nodes:
                logger.warning(f"No nodes found for lab {lab_id} on {host}")
                return None

            # 2. Get interfaces for each node
            node_observations: list[NodeObservation] = []
            total_cpu = 0.0
            total_memory = 0
            observed_ports: dict[str, int] = {}
            node_definitions: set[str] = set()

            for node in nodes:
                # Fetch interfaces
                interfaces = await self._cml.get_node_interfaces(
                    host, lab_id, node.id, username, password
                )

                iface_observations = tuple(
                    InterfaceObservation(
                        interface_id=iface.id,
                        label=iface.label,
                        slot=iface.slot or 0,
                        state=iface.state or "UNKNOWN",
                        mac_address=iface.mac_address,
                        ip4=tuple(iface.ip4 or []),
                    )
                    for iface in interfaces
                )

                node_obs = NodeObservation(
                    node_id=node.id,
                    label=node.label,
                    node_definition=node.node_definition,
                    state=node.state,
                    cpu_limit=node.cpu_limit,
                    ram_mb=node.ram,
                    tags=tuple(node.tags or []),
                    interfaces=iface_observations,
                )
                node_observations.append(node_obs)

                # Aggregate resources
                if node.cpu_limit:
                    total_cpu += node.cpu_limit
                if node.ram:
                    total_memory += node.ram
                node_definitions.add(node.node_definition)

                # Extract ports from tags (same logic as PortTemplate.from_cml_nodes)
                for tag in node.tags or []:
                    match = TAG_PATTERN.match(tag.strip())
                    if match:
                        protocol = match.group(1).lower()
                        port_number = int(match.group(2))
                        if protocol in CML_TCP_PROTOCOLS:
                            safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", node.label)
                            port_name = f"{safe_label}_{protocol}"
                            observed_ports[port_name] = port_number

            # 3. Get simulation stats (best-effort)
            sim_stats_raw: dict[str, Any] | None = None
            try:
                sim_stats = await self._cml.get_lab_simulation_stats(
                    host, lab_id, username, password
                )
                if sim_stats:
                    sim_stats_raw = sim_stats.raw
            except Exception as e:
                logger.debug(f"Could not fetch simulation_stats for lab {lab_id}: {e}")

            return ResourceObservation(
                observed_at=datetime.now(timezone.utc),
                observer=observer,
                total_cpu_cores=total_cpu,
                total_memory_mb=total_memory,
                total_storage_mb=None,  # Future: resource_pool_usage
                nodes=tuple(node_observations),
                actual_node_count=len(node_observations),
                node_definitions_used=tuple(sorted(node_definitions)),
                observed_ports=observed_ports,
                simulation_stats=sim_stats_raw,
            )

        except Exception as e:
            logger.error(f"Failed to observe resources for lab {lab_id} on {host}: {e}")
            return None
```

### 7.2 Add `report_resource_observations()` to ControlPlaneApiClient

**File**: `src/core/lcm_core/integration/control_plane_api_client.py` _(modify)_

Add new method following the established `transition_session()` pattern:

```python
async def report_resource_observations(
    self,
    session_id: str,
    observed_resources: dict,
    observed_ports: dict[str, int],
) -> dict[str, Any]:
    """Report resource observations for a session.

    Posts runtime CML resource and port observations to CPA
    for storage on the LabletSession aggregate.
    """
    result = await self._request(
        "POST",
        f"/api/internal/lablet-sessions/{session_id}/resource-observations",
        json={
            "observed_resources": observed_resources,
            "observed_ports": observed_ports,
        },
    )
    return dict(result) if result else {}
```

### 7.3 Integrate into Lablet Reconciler `_handle_running()`

**File**: `src/lablet-controller/application/hosted_services/lablet_reconciler.py` _(modify)_

Modify `_handle_running()` to observe resources before transitioning to COLLECTING (or STOPPING):

```python
async def _handle_running(self, instance: LabletSessionReadModel) -> ReconciliationResult:
    """Handle RUNNING session - sync state, observe resources, check timeslot."""
    if not instance.cml_lab_id:
        return ReconciliationResult.failed("No CML lab ID")

    try:
        # Check if timeslot has ended
        if instance.timeslot_end:
            now = datetime.now(timezone.utc)
            # ... existing timeslot parsing ...

            if now >= timeslot_end:
                # AD-OLR-001: Observe resources before transitioning
                await self._observe_and_report(instance)

                # Timeslot ended - transition to STOPPING
                await self._api.transition_session(
                    session_id=instance.id,
                    new_status=LabletSessionStatus.STOPPING,
                    reason="Timeslot ended",
                )
                return ReconciliationResult.requeue("Timeslot ended")

        # ... existing lab state verification ...

    except Exception as e:
        logger.warning(f"Failed to sync lab state for session {instance.id}: {e}")
        return ReconciliationResult.success()
```

Add helper method:

```python
async def _observe_and_report(self, instance: LabletSessionReadModel) -> None:
    """Observe live CML lab resources and report to CPA.

    Best-effort: failures are logged but do not block session lifecycle.
    AD-OLR-001: Observation at COLLECTING/STOPPING boundary.
    """
    try:
        observation = await self._resource_observer.observe(
            host=instance.worker_ip,
            lab_id=instance.cml_lab_id,
            username=instance.worker_cml_username,
            password=instance.worker_cml_password,
        )
        if observation:
            await self._api.report_resource_observations(
                session_id=instance.id,
                observed_resources=observation.to_dict(),
                observed_ports=observation.observed_ports,
            )
            logger.info(
                f"Resource observation reported for session {instance.id}: "
                f"cpu={observation.total_cpu_cores}, mem={observation.total_memory_mb}MB, "
                f"nodes={observation.actual_node_count}, ports={len(observation.observed_ports)}"
            )
        else:
            logger.warning(f"No resource observation available for session {instance.id}")
    except Exception as e:
        logger.warning(f"Resource observation failed for session {instance.id}: {e}")
```

### 7.4 Inject `ResourceObserver` into Reconciler

**File**: `src/lablet-controller/main.py` _(modify)_

Register `ResourceObserver` in the DI container and inject into the reconciler:

```python
# In create_app() or service registration:
builder.services.add_scoped(ResourceObserver)
```

### 7.5 Verification

- [ ] `ResourceObserver` has no side effects (pure observation) — all writes go through CPA
- [ ] `_observe_and_report()` is best-effort (failure does not block session lifecycle)
- [ ] `report_resource_observations()` follows `transition_session()` pattern exactly
- [ ] Port extraction logic matches `PortTemplate.from_cml_nodes()` (same `CML_TCP_PROTOCOLS`, same tag regex)
- [ ] lablet-controller tests pass: `cd src/lablet-controller && poetry run pytest`

---

## 8. Phase 6: Manual Observation Trigger

> **Scope**: Admin-initiated resource observation for RUNNING sessions via reactive etcd watch.

### 8.1 Add CPA External API Endpoint

**File**: `src/control-plane-api/api/controllers/lablet_sessions_controller.py` _(modify)_

Add endpoint for authenticated admin users:

```python
@router.post("/{session_id}/observe-resources")
async def request_resource_observation(
    self,
    session_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Request resource observation for a RUNNING session.

    Writes an etcd key that the lablet-controller watches for.
    The observation is performed asynchronously.
    """
    result = await self.mediator.execute_async(
        RequestResourceObservationCommand(
            session_id=session_id,
            requested_by=current_user.get("sub", "admin"),
        )
    )
    return self.process(result)
```

### 8.2 Add `RequestResourceObservationCommand`

**File**: `src/control-plane-api/application/commands/request_resource_observation_command.py` _(new)_

```python
"""Command to request resource observation for a RUNNING session.

Validates the session is in an observable state, then emits a domain event
that triggers an etcd projector. The lablet-controller watches for the
etcd key and performs the actual observation.

AD-OLR-007: Follows reactive etcd watch pattern (ADR-023).
"""

import logging
from dataclasses import dataclass
from typing import Any

from neuroglia.mediation import Command, CommandHandler

from application.commands.command_handler_base import CommandHandlerBase
from domain.enums import LabletSessionStatus

logger = logging.getLogger(__name__)


@dataclass
class RequestResourceObservationCommand(Command[OperationResult[dict[str, Any]]]):
    session_id: str
    requested_by: str = ""


class RequestResourceObservationCommandHandler(
    CommandHandlerBase,
    CommandHandler[RequestResourceObservationCommand, OperationResult[dict[str, Any]]],
):
    def __init__(self, mediator, mapper, cloud_event_bus, cloud_event_publishing_options, lablet_session_repository):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self._session_repository = lablet_session_repository

    async def handle_async(self, request, cancellation_token=None):
        session = await self._session_repository.get_by_id_async(request.session_id, cancellation_token)
        if not session:
            return self.not_found("LabletSession", request.session_id)

        if session.state.status != LabletSessionStatus.RUNNING:
            return self.bad_request(
                f"Resource observation can only be requested for RUNNING sessions. "
                f"Current status: {session.state.status}"
            )

        if not session.state.cml_lab_id or not session.state.worker_id:
            return self.bad_request("Session has no CML lab or worker assigned")

        # Emit domain event → etcd projector writes key → lablet-controller watches
        session.request_resource_observation(requested_by=request.requested_by)

        await self._session_repository.update_async(session, cancellation_token)

        return self.accepted({
            "session_id": request.session_id,
            "message": "Resource observation requested. Results will be recorded asynchronously.",
        })
```

### 8.3 Add Domain Event + Aggregate Method

**File**: `src/control-plane-api/domain/events/lablet_session_events.py` _(modify)_

```python
@cloudevent("lablet_session.observe_resources_requested.v1")
@dataclass
class LabletSessionObserveResourcesRequestedDomainEvent(DomainEvent):
    """Event raised when admin requests resource observation.

    Does NOT change session status. Triggers etcd projector for
    lablet-controller to pick up and perform the observation.
    """

    aggregate_id: str
    requested_by: str
    requested_at: datetime

    def __init__(self, aggregate_id, requested_by, requested_at):
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.requested_by = requested_by
        self.requested_at = requested_at
```

**File**: `src/control-plane-api/domain/entities/lablet_session.py` _(modify)_

Add aggregate method:

```python
def request_resource_observation(self, requested_by: str = "") -> None:
    """Request resource observation (manual trigger).

    Emits event for etcd projector. Does not change session status.
    """
    self.state.on(
        self.register_event(
            LabletSessionObserveResourcesRequestedDomainEvent(
                aggregate_id=self.id(),
                requested_by=requested_by,
                requested_at=datetime.now(timezone.utc),
            )
        )
    )
```

Add `@dispatch` handler on state (no-op — just bumps `updated_at`):

```python
@dispatch(LabletSessionObserveResourcesRequestedDomainEvent)
def on(self, event: LabletSessionObserveResourcesRequestedDomainEvent) -> None:
    self.updated_at = event.requested_at
```

### 8.4 Add EtcdProjector

**File**: `src/control-plane-api/infrastructure/projectors/lablet_session_etcd_projectors.py` _(modify)_

Add new projector following established pattern:

```python
class ObserveResourcesRequestedEtcdProjector(
    DomainEventHandler[LabletSessionObserveResourcesRequestedDomainEvent]
):
    """Project observation request to etcd for lablet-controller watch."""

    def __init__(self, etcd_store: EtcdStateStore):
        self._etcd = etcd_store

    async def handle_async(self, event: LabletSessionObserveResourcesRequestedDomainEvent) -> None:
        import json

        payload = json.dumps({
            "session_id": event.aggregate_id,
            "requested_by": event.requested_by,
            "requested_at": event.requested_at.isoformat(),
        })
        await self._etcd._etcd.put(
            f"/sessions/{event.aggregate_id}/observe_resources",
            payload,
        )
        log.info(f"etcd: wrote observe_resources request for session {event.aggregate_id}")
        return None
```

### 8.5 Add lablet-controller Watch Handler

**File**: `src/lablet-controller/application/hosted_services/lablet_reconciler.py` _(modify)_

Add a watch for `/sessions/*/observe_resources` keys in the reconciler's watch loop. When triggered:

1. Parse the session_id from the etcd key
2. Fetch session details from CPA
3. Call `_observe_and_report(instance)` (reuses Phase 5 logic)
4. Delete the etcd key after observation completes

```python
async def _handle_observe_resources_event(self, key: str, value: str) -> None:
    """Handle manual observation request from etcd watch."""
    import json

    data = json.loads(value)
    session_id = data.get("session_id")
    if not session_id:
        return

    instance = await self._api.get_session(session_id)
    if instance and instance.get("status") == "running":
        read_model = LabletSessionReadModel(**instance)
        await self._observe_and_report(read_model)

    # Delete the etcd key (observation complete or not applicable)
    await self._etcd.delete(f"/sessions/{session_id}/observe_resources")
```

### 8.6 Verification

- [ ] Follows reactive etcd pattern exactly (ADR-023): command → event → projector → etcd → controller watch → delete key
- [ ] Manual trigger only works for RUNNING sessions
- [ ] Observation failures don't leave dangling etcd keys (always deleted)
- [ ] Both CPA and lablet-controller tests pass

---

## 9. Phase 7: CPA Admin API

> **Scope**: External API endpoints for admin to review aggregated observations and apply to definitions.

### 9.1 Add External Query Endpoint

**File**: `src/control-plane-api/api/controllers/lablet_definitions_controller.py` _(modify)_

```python
@router.get("/{definition_id}/resource-observations")
async def get_resource_observations(
    self,
    definition_id: str,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get aggregated resource observations for a definition.

    Returns max/avg/latest observed resources across all sessions
    that have completed resource observation for this definition.
    """
    result = await self.mediator.execute_async(
        GetDefinitionResourceObservationsQuery(
            definition_id=definition_id,
            limit=limit,
        )
    )
    return self.process(result)
```

### 9.2 Leverage Existing `UpdateLabletDefinitionCommand`

No new command needed. The admin uses the existing `PATCH /api/lablet-definitions/{id}` endpoint with the `update()` method to apply revised resource requirements. The UI will pre-fill the form with aggregated observation values.

### 9.3 Verification

- [ ] Query endpoint requires authentication
- [ ] Returns aggregated data (max, avg, latest) — not raw observation dumps
- [ ] Uses existing `GetDefinitionResourceObservationsQuery` from Phase 3

---

## 10. Phase 8: Frontend

> **Scope**: UI changes to surface observations in the admin interface.

### 10.1 Session Detail: Observation Panel

**File**: `src/control-plane-api/ui/src/pages/session-detail.js` _(modify)_

Add a collapsible panel showing:

- **Observation status**: Whether observations have been recorded
- **Observed resources**: CPU cores, memory MB, node count, node definitions
- **Port comparison**: Side-by-side table of allocated vs observed ports
- **Port drift badge**: Warning badge if drift detected
- **"Observe Now" button**: Triggers manual observation (POST to `/api/lablet-sessions/{id}/observe-resources`)

```
┌─ Resource Observations ───────────────────────────────────────┐
│ Status: 1 observation recorded at 2026-02-28T14:30:00Z        │
│                                                                │
│ Observed Resources:                                            │
│   CPU: 4 cores  |  Memory: 8192 MB  |  Nodes: 5               │
│   Node definitions: iosv, csr1000v, ubuntu-desktop-24-04-v2    │
│                                                                │
│ Port Allocation Comparison:          ⚠️ Drift Detected         │
│ ┌──────────────┬───────────┬──────────┬────────┐               │
│ │ Port Name    │ Allocated │ Observed │ Status │               │
│ ├──────────────┼───────────┼──────────┼────────┤               │
│ │ PC_serial    │ 5041      │ 5041     │ ✓      │               │
│ │ PC_vnc       │ 5044      │ 5044     │ ✓      │               │
│ │ iosv-0_serial│ 5042      │ 5042     │ ✓      │               │
│ │ NEW_ssh      │ —         │ 5050     │ ⚠ ADD  │               │
│ └──────────────┴───────────┴──────────┴────────┘               │
│                                                                │
│ [🔄 Observe Now]  (only shown for RUNNING sessions)            │
└────────────────────────────────────────────────────────────────┘
```

### 10.2 Definition Detail: Aggregated Observations Panel

**File**: `src/control-plane-api/ui/src/pages/definition-detail.js` _(modify)_

Add a panel showing aggregated observations:

```
┌─ Observed Resources (from 3 sessions) ────────────────────────┐
│                                                                │
│ Resource Comparison:                                           │
│ ┌──────────────┬───────────────┬──────┬──────┬────────┐        │
│ │ Resource     │ Configured    │ Max  │ Avg  │ Latest │        │
│ ├──────────────┼───────────────┼──────┼──────┼────────┤        │
│ │ CPU cores    │ 2             │ 4    │ 3.5  │ 4      │        │
│ │ Memory (GB)  │ 4             │ 8    │ 6    │ 8      │        │
│ │ Node count   │ 3             │ 5    │ 4    │ 5      │        │
│ └──────────────┴───────────────┴──────┴──────┴────────┘        │
│                                                                │
│ Port drift detected in 1/3 sessions                            │
│                                                                │
│ [📋 Apply Max Observed]  [📋 Apply Latest]  [✏️ Custom]       │
│                                                                │
│ Session History:                                               │
│  • Session abc-123 (2026-02-28): 4 CPU, 8192MB, 5 nodes       │
│  • Session def-456 (2026-02-27): 3 CPU, 6144MB, 4 nodes       │
│  • Session ghi-789 (2026-02-26): 4 CPU, 8192MB, 5 nodes       │
└────────────────────────────────────────────────────────────────┘
```

**Apply buttons** pre-fill the existing "Edit Definition" form with the observed values, then submit via the existing `PATCH /api/lablet-definitions/{id}` endpoint using `update()`.

### 10.3 Definition List: Observation Indicator

**File**: `src/control-plane-api/ui/src/pages/definitions-list.js` _(modify)_

Add a small indicator column showing:

- 🔍 = has observations
- ⚠️ = port drift detected in recent session
- ➖ = no observations yet

### 10.4 UI Build

After modifying JS sources:

```bash
cd src/control-plane-api && make build-ui
```

### 10.5 Verification

- [ ] Session detail shows observation data when available
- [ ] "Observe Now" button only appears for RUNNING sessions
- [ ] Definition detail shows aggregated observations with comparison table
- [ ] "Apply" buttons correctly pre-fill the edit form
- [ ] Port drift warning badge is visible
- [ ] UI builds cleanly: `make build-ui`
- [ ] End-to-end test: create definition → run session → observe → review → apply

---

## 11. Phase 9: Tests

> **Scope**: Unit and integration tests for all new components.

### 9.1 lcm-core Tests

**File**: `src/core/tests/domain/value_objects/test_resource_observation.py` _(new)_

- [ ] `ResourceObservation` round-trip serialization
- [ ] `NodeObservation` round-trip serialization
- [ ] `InterfaceObservation` round-trip serialization
- [ ] Edge cases: empty nodes, empty interfaces, null fields

### 9.2 CPA Domain Tests

**File**: `src/control-plane-api/tests/domain/test_lablet_session_observation.py` _(new)_

- [ ] `record_resource_observation()` — happy path
- [ ] `record_resource_observation()` — port drift detection (added ports)
- [ ] `record_resource_observation()` — port drift detection (removed ports)
- [ ] `record_resource_observation()` — port drift detection (changed ports)
- [ ] `record_resource_observation()` — no drift (exact match)
- [ ] `record_resource_observation()` — no allocated ports (no drift)
- [ ] `request_resource_observation()` — emits event
- [ ] Domain event serialization for new events

### 9.3 CPA Command Tests

**File**: `src/control-plane-api/tests/application/commands/test_record_resource_observation_command.py` _(new)_

- [ ] Happy path: RUNNING session with observations
- [ ] Happy path: COLLECTING session with observations
- [ ] Error: session not found
- [ ] Error: session in wrong state (PENDING, SCHEDULED, etc.)

### 9.4 CPA Query Tests

**File**: `src/control-plane-api/tests/application/queries/test_get_definition_resource_observations_query.py` _(new)_

- [ ] Aggregation with multiple sessions
- [ ] Aggregation with no observations
- [ ] Port drift count
- [ ] Limit parameter

### 9.5 lablet-controller Tests

**File**: `src/lablet-controller/tests/application/services/test_resource_observer.py` _(new)_

- [ ] `ResourceObserver.observe()` — happy path with mocked CML API
- [ ] `ResourceObserver.observe()` — partial failure (no simulation_stats)
- [ ] `ResourceObserver.observe()` — complete failure (returns None)
- [ ] Port extraction from tags matches `PortTemplate.from_cml_nodes()` logic

### 9.6 Integration Tests

- [ ] End-to-end: observation through reconciler → CPA storage
- [ ] Manual trigger: etcd write → watch → observe → report → delete

---

## 12. Phase 10: Documentation

> **Scope**: Update documentation and configuration.

### 10.1 Update `CHANGELOG.md`

```markdown
## Unreleased

### Added
- Resource & Port Observation — "Learn from Live" (ADR-030)
  - lablet-controller observes CML runtime resources at COLLECTING phase
  - Manual observation trigger for RUNNING sessions
  - Port drift detection (allocated vs observed ports)
  - Aggregated observation query per definition
  - Admin UI panels on session detail and definition detail
```

### 10.2 Update Settings Documentation

Document new settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `RESOURCE_OBSERVATION_ENABLED` | `true` | Enable automatic observation at COLLECTING |
| `RESOURCE_OBSERVATION_TIMEOUT_SECONDS` | `30` | Timeout for CML API observation calls |

### 10.3 Update API Documentation

- Internal API: `POST /api/internal/lablet-sessions/{id}/resource-observations`
- External API: `POST /api/lablet-sessions/{id}/observe-resources`
- External API: `GET /api/lablet-definitions/{id}/resource-observations`

### 10.4 Verification

- [ ] CHANGELOG updated
- [ ] Settings documented
- [ ] API endpoints documented in OpenAPI spec (auto-generated)
- [ ] ADR-030 linked from this plan

---

## Appendix A: CML API Reference

### Relevant Endpoints (CML v2.9)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/v0/labs/{lab_id}/simulation_stats` | JWT | Runtime CPU/state per node |
| `GET` | `/api/v0/labs/{lab_id}/nodes` | JWT | List node IDs |
| `GET` | `/api/v0/labs/{lab_id}/nodes/{node_id}` | JWT | Node details (cpu_limit, ram, tags) |
| `GET` | `/api/v0/labs/{lab_id}/nodes/{node_id}/interfaces` | JWT | Interface IDs for a node |
| `GET` | `/api/v0/labs/{lab_id}/interfaces/{interface_id}` | JWT | Interface details (mac, ip4, state) |
| `GET` | `/api/v0/resource_pool_usage` | JWT | Pool-level resource usage (P2) |

### Node Detail Response (relevant fields)

```json
{
    "id": "n0",
    "label": "PC",
    "node_definition": "ubuntu-desktop-24-04-v2",
    "state": "BOOTED",
    "cpu_limit": 1,
    "ram": 2048,
    "tags": ["serial:5041", "vnc:5044"],
    "x": 100,
    "y": 200
}
```

### Simulation Stats Response

```json
{
    "nodes": {
        "n0": {"state": "BOOTED", "cpu_usage": 12.5, "disk_read": 0, "disk_write": 0}
    },
    "links": {
        "l0": {"state": "UP"}
    }
}
```

---

## Appendix B: Data Flow Diagram

### Automatic Observation (COLLECTING phase)

```
Time ──────────────────────────────────────────────────────────────▶

lablet-controller                   CML API                CPA
     │                               │                      │
     │  Timeslot expires              │                      │
     │  (_handle_running)             │                      │
     │                                │                      │
     ├─── GET /nodes ────────────────▶│                      │
     │◀── [{id,label,cpu,ram,tags}] ──┤                      │
     │                                │                      │
     ├─── GET /nodes/{id}/interfaces ▶│  (per node)          │
     │◀── [{id,label,slot,state}] ────┤                      │
     │                                │                      │
     ├─── GET /simulation_stats ─────▶│                      │
     │◀── {nodes:{n0:{cpu_usage}}} ───┤                      │
     │                                │                      │
     │  Assemble ResourceObservation  │                      │
     │                                │                      │
     ├─── POST /internal/sessions ────────────────────────▶  │
     │    /{id}/resource-observations │                      │
     │                                │  Store on session    │
     │                                │  Detect port drift   │
     │◀── 200 OK ─────────────────────────────────────────── │
     │                                │                      │
     ├─── POST /internal/sessions ────────────────────────▶  │
     │    /{id}/transition (STOPPING) │                      │
     │                                │                      │
```

### Manual Observation Trigger

```
Admin UI              CPA                    etcd              lablet-controller
  │                    │                      │                      │
  ├─ POST /sessions/   │                      │                      │
  │  {id}/observe ────▶│                      │                      │
  │                    │  Validate RUNNING     │                      │
  │                    │  Emit event           │                      │
  │◀── 202 Accepted ──┤                      │                      │
  │                    │                      │                      │
  │                    ├── PUT /sessions/ ────▶│                      │
  │                    │   {id}/observe_res    │                      │
  │                    │                      │── watch event ──────▶│
  │                    │                      │                      │
  │                    │                      │    observe + POST ───▶│ (CPA)
  │                    │                      │◀── DELETE key ───────┤
```

---

## Appendix C: File Index

### New Files

| File | Service | Phase |
|------|---------|-------|
| `core/lcm_core/domain/value_objects/interface_observation.py` | lcm-core | 1 |
| `core/lcm_core/domain/value_objects/node_observation.py` | lcm-core | 1 |
| `core/lcm_core/domain/value_objects/resource_observation.py` | lcm-core | 1 |
| `control-plane-api/application/commands/record_resource_observation_command.py` | CPA | 3 |
| `control-plane-api/application/commands/request_resource_observation_command.py` | CPA | 6 |
| `control-plane-api/application/queries/get_definition_resource_observations_query.py` | CPA | 3 |
| `lablet-controller/application/services/resource_observer.py` | lablet-controller | 5 |

### Modified Files

| File | Service | Phase | Changes |
|------|---------|-------|---------|
| `core/lcm_core/domain/value_objects/__init__.py` | lcm-core | 1 | Export new value objects |
| `control-plane-api/domain/events/lablet_session_events.py` | CPA | 2, 6 | 3 new domain events |
| `control-plane-api/domain/entities/lablet_session.py` | CPA | 2, 6 | New state fields + methods |
| `control-plane-api/domain/repositories/lablet_session_repository.py` | CPA | 3 | New abstract method |
| `control-plane-api/integration/repositories/mongo_lablet_session_repository.py` | CPA | 3 | Implement new method |
| `control-plane-api/api/controllers/internal_sessions_controller.py` | CPA | 3 | New endpoint |
| `control-plane-api/api/controllers/lablet_definitions_controller.py` | CPA | 7 | New endpoint |
| `control-plane-api/api/controllers/lablet_sessions_controller.py` | CPA | 6 | New endpoint |
| `control-plane-api/infrastructure/projectors/lablet_session_etcd_projectors.py` | CPA | 6 | New projector |
| `core/lcm_core/integration/control_plane_api_client.py` | lcm-core | 5 | New method |
| `lablet-controller/integration/services/cml_labs_api_client.py` | lablet-controller | 4 | New data class + methods |
| `lablet-controller/application/hosted_services/lablet_reconciler.py` | lablet-controller | 5, 6 | Observation logic + watch |
| `lablet-controller/main.py` | lablet-controller | 5 | DI registration |
| `control-plane-api/ui/src/pages/session-detail.js` | CPA UI | 8 | Observation panel |
| `control-plane-api/ui/src/pages/definition-detail.js` | CPA UI | 8 | Aggregated observations panel |
| `control-plane-api/ui/src/pages/definitions-list.js` | CPA UI | 8 | Observation indicator |
