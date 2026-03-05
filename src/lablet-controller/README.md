# Lablet Controller Service

The Lablet Controller is responsible for **LabletInstance reconciliation** - managing the workload lifecycle by reconciling desired instance state (spec) against actual CML lab state.

## Domain: Application Layer (CML Labs SPI)

The Lablet Controller operates at the **application layer**, talking exclusively to the **CML Labs SPI**:

- **Labs API** - Lab lifecycle (create, start, stop, wipe, delete)
- **Nodes API** - Node state and configuration extraction
- **Interfaces API** - Console port mapping and external access
- **Links API** - Topology connectivity information

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                LABLET CONTROLLER - RECONCILIATION PATTERN                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐   │
│   │       SPEC       │     │     OBSERVE      │     │       ACT        │   │
│   │   (Desired)      │     │    (Actual)      │     │   (Reconcile)    │   │
│   └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘   │
│            │                        │                        │              │
│            ▼                        ▼                        ▼              │
│   ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐   │
│   │ LabletInstance   │     │ CML Lab State    │     │ • Import lab     │   │
│   │ • state=RUNNING  │     │ • state=DEFINED  │     │ • Start nodes    │   │
│   │ • worker_id=W1   │ ←→  │ • nodes stopped  │  →  │ • Allocate ports │   │
│   │ • ports={...}    │     │ • no ports       │     │ • Update state   │   │
│   └──────────────────┘     └──────────────────┘     └──────────────────┘   │
│                                                                              │
│   Source: MongoDB         Source: CML Labs API       Target: Both          │
│   (via Control Plane)     (direct observation)       (via Control Plane)   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Responsibilities

- **Instance Reconciliation**: Compare desired instance state with actual CML lab state
- **Lab Lifecycle**: Import topology, start/stop/wipe labs
- **Port Allocation**: Map console ports to external access
- **Node Configuration**: Extract configs from running nodes
- **Capacity Signaling**: Signal to Worker Controller when scale-up is needed

## Domain Separation

| Service | Abstraction Layer | SPI (Service Provider Interface) |
|---------|-------------------|----------------------------------|
| **Lablet Controller** | Application (Workload) | CML Labs SPI (Labs, Nodes, Interfaces, Links API) |
| **Worker Controller** | Infrastructure (Compute) | Cloud Provider SPI (EC2, CloudWatch, CML System API) |

Both controllers follow the same **reconciliation pattern** (SPEC → OBSERVE → ACT), but at different abstraction layers.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     LABLET CONTROLLER                            │
│               (Application Layer - Workloads)                    │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                  LEADER ELECTION (etcd)                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                            │                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                 RECONCILIATION LOOP                       │  │
│  │     For each LabletInstance: SPEC ←→ OBSERVE → ACT       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                            │                                    │
│                            ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    CML LABS SPI                           │  │
│  │                                                           │  │
│  │  ┌────────────────┐ ┌────────────────┐ ┌──────────────┐  │  │
│  │  │  Labs API      │ │  Nodes API     │ │ Interfaces   │  │  │
│  │  │  /api/v0/labs  │ │  /labs/{id}/   │ │ API          │  │  │
│  │  │                │ │  nodes         │ │              │  │  │
│  │  │ • Import YAML  │ │ • List nodes   │ │ • Get ports  │  │  │
│  │  │ • Start/Stop   │ │ • Node state   │ │ • Map access │  │  │
│  │  │ • Wipe/Delete  │ │ • Extract cfg  │ │              │  │  │
│  │  └────────────────┘ └────────────────┘ └──────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                            │                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   CONTROL PLANE API                       │  │
│  │         (All mutations via API - ADR-001)                 │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Reconciliation Examples

| Desired (Spec) | Actual (Observed) | Action |
|----------------|-------------------|--------|
| Instance state=RUNNING | Lab not imported | Import topology, start lab |
| Instance state=RUNNING | Lab state=DEFINED | Start lab nodes |
| Instance state=RUNNING | Lab state=STARTED | No action (converged) |
| Instance state=STOPPED | Lab state=STARTED | Stop lab nodes |
| Instance state=TERMINATED | Lab exists | Wipe and delete lab |

## Key Design Decision

**API-Centric Mutations (ADR-001):** The Lablet Controller does NOT write directly to MongoDB or etcd. All state changes are made via the Control Plane API:

- `POST /api/internal/instances/{id}/transition` - Update instance lifecycle state
- `PUT /api/internal/instances/{id}/lab-mapping` - Update CML lab ID mapping
- `PUT /api/internal/instances/{id}/ports` - Update allocated ports

## Directory Structure

```
application/
    commands/       # Controller commands
    queries/        # State queries
    services/       # Lablet Controller service, reconcilers
    dtos/           # Data transfer objects
domain/
    entities/       # Controller domain entities
    repositories/   # Repository interfaces
    events/         # Domain events
integration/
    repositories/   # etcd state store implementation
    services/       # Control Plane API client, CML Labs SPI client
infrastructure/    # Technical adapters
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ETCD_HOST` | etcd server host | `localhost` |
| `ETCD_PORT` | etcd server port | `2379` |
| `CONTROL_PLANE_API_URL` | Control Plane API URL | `http://localhost:8020` |
| `LABLET_CONTROLLER_INSTANCE_ID` | Unique instance ID | Auto-generated |
| `LEADER_LEASE_TTL` | Leader lease TTL in seconds | `15` |
| `RECONCILE_INTERVAL` | Reconciliation interval in seconds | `30` |
| `CML_WORKER_API_USERNAME` | CML Labs API username | - |
| `CML_WORKER_API_PASSWORD` | CML Labs API password | - |

## Development

```bash
# Install dependencies
make install

# Run locally (requires etcd and Control Plane API)
make run

# Run tests
make test
```

## Health Check

The service exposes a health endpoint at `/health` for container orchestration.
