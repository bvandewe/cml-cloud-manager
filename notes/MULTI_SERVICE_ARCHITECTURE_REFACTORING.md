# Multi-Service Architecture Refactoring

**Date:** 2025-01-20
**Status:** IN PROGRESS (Updated 2026-01-16)

## Overview

The Lablet Cloud Manager has been refactored from a monolithic application into a multi-service architecture with four independent microservices. This enables better separation of concerns, independent scaling, and prepares the codebase for the Lablet Resource Manager implementation.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Lablet Cloud Manager                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────┐  ┌─────────────────┐  ┌───────────────────────────┐│
│  │  Control Plane API  │  │Resource Scheduler│  │    Lablet Controller      ││
│  │    (Port 8020)      │  │   (Port 8081)   │  │      (Port 8082)          ││
│  │                     │  │                 │  │                           ││
│  │  • REST API         │  │  • Leader       │  │  • Leader Election        ││
│  │  • Bootstrap 5 UI   │  │    Election     │  │  • LabletInstance         ││
│  │  • MongoDB Writer   │  │  • Placement    │  │    Reconciliation         ││
│  │  • Auth (Keycloak)  │  │    Algorithm    │  │  • CML Labs SPI           ││
│  │  • SSE Events       │  │  • Queue Watch  │  │    (Labs/Nodes/Interfaces)││
│  └─────────┬───────────┘  └────────┬────────┘  └─────────────┬─────────────┘│
│            │                       │                         │              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                       Worker Controller                                  ││
│  │                         (Port 8083)                                      ││
│  │                                                                          ││
│  │  • Leader Election                                                       ││
│  │  • CML Worker Reconciliation (SPEC → OBSERVE → ACT)                      ││
│  │  • Cloud Provider SPI (EC2, CloudWatch, CML System API)                  ││
│  │  • Scale-up execution (launch EC2 instances)                             ││
│  │  • Scale-down execution (stop/terminate EC2 instances)                   ││
│  │  • License registration/deregistration                                   ││
│  │  • Auto-import workers from AWS tags                                     ││
│  └──────────────────────────────────┬──────────────────────────────────────┘│
│                                     │                                        │
│            └────────────────────────┼────────────────────────┘              │
│                                     │                                        │
│                        ┌────────────┴────────────┐                          │
│                        │        etcd             │                          │
│                        │    (Port 2379)          │                          │
│                        │  • State Store          │                          │
│                        │  • Leader Election      │                          │
│                        │  • Watch Triggers       │                          │
│                        └─────────────────────────┘                          │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Controller Domain Separation

Both controllers follow the same **reconciliation pattern** (SPEC → OBSERVE → ACT), but operate at different abstraction layers:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      CONTROLLER DOMAIN SEPARATION                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    APPLICATION LAYER (Workloads)                       │  │
│  │                                                                        │  │
│  │  ┌─────────────────────┐              ┌─────────────────────────────┐ │  │
│  │  │  LABLET CONTROLLER  │──────────────│      CML LABS SPI           │ │  │
│  │  │                     │              │                             │ │  │
│  │  │  Reconciles:        │              │  • /api/v0/labs             │ │  │
│  │  │  • LabletInstances  │              │  • /api/v0/labs/{id}/nodes  │ │  │
│  │  │  • Lab lifecycle    │              │  • /api/v0/labs/{id}/links  │ │  │
│  │  │  • Port allocations │              │  • /api/v0/labs/{id}/       │ │  │
│  │  │                     │              │    interfaces               │ │  │
│  │  └─────────────────────┘              └─────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                   INFRASTRUCTURE LAYER (Compute)                       │  │
│  │                                                                        │  │
│  │  ┌─────────────────────┐              ┌─────────────────────────────┐ │  │
│  │  │  WORKER CONTROLLER  │──────────────│    CLOUD PROVIDER SPI       │ │  │
│  │  │                     │              │                             │ │  │
│  │  │  Reconciles:        │              │  • AWS EC2 API              │ │  │
│  │  │  • CML Workers      │              │  • AWS CloudWatch           │ │  │
│  │  │  • EC2 lifecycle    │              │  • CML System API           │ │  │
│  │  │  • License state    │              │    (/system_stats, license) │ │  │
│  │  │                     │              │                             │ │  │
│  │  └─────────────────────┘              └─────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
lablet-cloud-manager/
├── src/
│   ├── control-plane-api/     # Main API + UI service
│   │   ├── api/               # REST controllers
│   │   ├── application/       # Commands, queries, services
│   │   ├── domain/            # Entities, repositories (interfaces)
│   │   ├── infrastructure/    # Session stores, adapters
│   │   ├── integration/       # MongoDB, AWS, CML clients
│   │   ├── observability/     # OTEL instrumentation
│   │   ├── ui/                # Bootstrap 5 SPA (Parcel)
│   │   ├── tests/             # pytest test suite
│   │   ├── main.py            # FastAPI app factory
│   │   ├── Dockerfile         # Multi-stage with UI build
│   │   ├── Makefile           # Service-specific commands
│   │   ├── pyproject.toml     # Poetry dependencies
│   │   └── pytest.ini         # Test configuration
│   │
│   ├── resource-scheduler/   # LabletInstance placement service
│   │   ├── application/       # Settings, scheduler service
│   │   ├── domain/            # (Future: scheduling domain logic)
│   │   ├── integration/       # etcd client, API client
│   │   ├── tests/             # pytest test suite
│   │   ├── main.py            # Service entry point
│   │   ├── Dockerfile
│   │   ├── Makefile
│   │   ├── pyproject.toml
│   │   └── pytest.ini
│   │
│   ├── lablet-controller/     # LabletInstance lifecycle service
│   │   ├── application/       # Settings, lablet controller service
│   │   ├── domain/            # (Future: controller domain logic)
│   │   ├── integration/       # CML Labs SPI client, etcd client
│   │   │   └── providers/     # CML Labs API implementation
│   │   ├── tests/             # pytest test suite
│   │   ├── main.py            # Service entry point
│   │   ├── Dockerfile
│   │   ├── Makefile
│   │   ├── pyproject.toml
│   │   └── pytest.ini
│   │
│   └── worker-controller/     # CML Worker reconciliation service
│       ├── application/       # Settings, jobs, worker controller service
│       ├── domain/            # (Future: worker controller domain logic)
│       ├── integration/       # Cloud Provider SPI clients
│       │   └── providers/     # AWS EC2, CloudWatch, CML System API
│       ├── tests/             # pytest test suite
│       ├── main.py            # Service entry point
│       ├── Dockerfile
│       ├── Makefile
│       ├── pyproject.toml
│       └── pytest.ini
│
├── docker-compose.yml         # All services orchestration
├── Makefile                   # Root orchestration commands
├── ccm.code-workspace         # VS Code multi-root workspace
└── ...
```

## Service Responsibilities

### Control Plane API (`src/control-plane-api/`)

**Purpose:** Central API gateway and UI, single writer to MongoDB

- REST API endpoints for all CRUD operations
- Bootstrap 5 SPA with Server-Side Events (SSE)
- Keycloak OAuth2/OIDC authentication
- MongoDB as source of truth
- Internal API endpoints for other services

**Port:** 8020 (HTTP), 5680 (Debug)

### Resource Scheduler (`src/resource-scheduler/`)

**Purpose:** LabletInstance placement decisions

- Leader election via etcd
- Watches etcd for PENDING instances
- Placement algorithm (bin-packing with resource constraints)
- Updates instance state via Control Plane API

**Port:** 8081 (Health), 5681 (Debug)

**Key Components:**

- `SchedulerService`: Main scheduling loop with leader election
- `EtcdClient`: etcd state store wrapper
- `ControlPlaneClient`: HTTP client for API calls

### Lablet Controller (`src/lablet-controller/`)

**Purpose:** LabletInstance reconciliation via CML Labs SPI

**Domain:** Application layer (workload management)

- Leader election via etcd
- Reconciliation loop (actual lab state vs. desired instance state)
- CML Labs SPI integration:
  - Labs API (`/api/v0/labs`) - lab lifecycle
  - Nodes API (`/api/v0/labs/{id}/nodes`) - node state
  - Interfaces API (`/api/v0/labs/{id}/interfaces`) - port mapping
  - Links API (`/api/v0/labs/{id}/links`) - topology
- Updates instance state via Control Plane API

**Port:** 8082 (Health), 5682 (Debug)

**Key Components:**

- `LabletControllerService`: Main reconciliation loop
- `CMLLabsSpiClient`: CML Labs API client
- `InstanceReconciler`: Compares spec vs actual lab state

### Worker Controller (`src/worker-controller/`)

**Purpose:** CML Worker reconciliation via Cloud Provider SPI

**Domain:** Infrastructure layer (compute management)

- Leader election via etcd
- Reconciliation loop (actual EC2/CML state vs. desired worker state)
- Cloud Provider SPI integration:
  - AWS EC2 API - instance lifecycle (start/stop/terminate/create)
  - AWS CloudWatch - infrastructure metrics
  - CML System API (`/system_information`, `/system_stats`, license)
- Scale-up execution (launch EC2 instances)
- Scale-down execution (stop/terminate EC2 instances)
- License registration/deregistration
- Auto-import workers from AWS tags

**Port:** 8083 (Health), 5683 (Debug)

**Key Components:**

- `WorkerControllerService`: Main reconciliation loop
- `CloudProviderSpiClient`: AWS EC2/CloudWatch client
- `CMLSystemApiClient`: CML system-level API client
- `WorkerReconciler`: Compares spec vs actual EC2/CML state

## Development Commands

### Root Level (Orchestration)

```bash
# Docker operations
make up                    # Start all services
make down                  # Stop all services
make dev                   # Build and run with logs
make logs                  # All service logs
make logs-api              # Control plane API logs
make logs-resource-scheduler # Resource scheduler logs
make logs-lablet-controller # Lablet controller logs
make logs-worker-controller # Worker controller logs
make urls                  # Show all service URLs

# All services
make install-all     # Install deps for all services
make test-all        # Run all tests
make lint-all        # Lint all services
make setup           # Complete setup for new developers
```

### Per-Service Commands

```bash
# Control Plane API
make api-install     # Install Python deps
make api-install-ui  # Install Node.js deps
make api-build-ui    # Build frontend
make api-run         # Run locally
make api-test        # Run tests
make api-lint        # Run linting

# Resource Scheduler
make resource-scheduler-install
make resource-scheduler-run
make resource-scheduler-test
make resource-scheduler-lint

# Lablet Controller
make lablet-controller-install
make lablet-controller-run
make lablet-controller-test
make lablet-controller-lint

# Worker Controller (TODO - not yet implemented)
# make worker-controller-install
# make worker-controller-run
# make worker-controller-test
# make worker-controller-lint
```

## VS Code Workspace

The workspace file (`ccm.code-workspace`) includes:

- 📂 Folders for all four microservices
- 🚀 Launch configurations for running/debugging each service
- ⚙️ Tasks for common operations
- 🔌 Extension recommendations

### Launch Configurations

- `control-plane-api: Run` - Run API locally
- `resource-scheduler: Run` - Run resource scheduler locally
- `lablet-controller: Run` - Run lablet controller locally
- `All Services (Local)` - Run all services locally
- `All Services (Attach Docker)` - Attach debugger to Docker containers

## Docker Compose Services

| Service | Port(s) | Description |
|---------|---------|-------------|
| `control-plane-api` | 8020, 5680 | Main API + UI |
| `resource-scheduler` | 8081, 5681 | Placement service |
| `lablet-controller` | 8082, 5682 | LabletInstance reconciliation service |
| `worker-controller` | 8083, 5683 | CML Worker observation service |
| `etcd` | 2379, 2380 | State store |
| `mongodb` | 8022 | Primary database |
| `keycloak` | 8021 | Auth server |
| `redis` | 6379 | Session store |
| `event-player` | 8024 | Event visualization |
| `otel-collector` | 4317, 4318 | Observability |

## Key Design Decisions

### AD-1: Independent Dependencies

Each microservice has its own:

- `pyproject.toml` with Poetry
- `Dockerfile` with independent builds
- `Makefile` for service-specific commands
- `.venv` (created by Poetry)

**Rationale:** Enables independent versioning, deployment, and scaling.

### AD-2: Leader Election Pattern

Both resource-scheduler and lablet-controller implement leader election via etcd.

**Rationale:** Ensures only one instance performs critical operations, preventing conflicts.

### AD-3: Cloud Provider SPI (Worker Controller)

Worker Controller uses an abstract `CloudProviderInterface` with AWS implementation.

**Rationale:** Worker Controller manages infrastructure lifecycle; enables future support for other cloud providers (GCP, Azure).

### AD-4: CML Labs SPI (Lablet Controller)

Lablet Controller uses the CML Labs API exclusively for workload management.

**Rationale:** Clear separation between infrastructure (Worker Controller) and application (Lablet Controller) concerns.

### AD-5: Control Plane as Single Writer

Only the Control Plane API writes to MongoDB. Resource Scheduler and Controller communicate via API.

**Rationale:** Prevents data conflicts, simplifies consistency, enables audit logging at single point.

## Migration Notes

### What Changed

1. All `src/` code moved to `src/control-plane-api/`
2. `tests/` and `pytest.ini` moved to `src/control-plane-api/`
3. New `src/resource-scheduler/` and `src/lablet-controller/` services created
4. `src/worker-controller/` to be created (will extract from control-plane-api)
5. Root `docker-compose.yml` updated with all services
6. Root `Makefile` updated with orchestration commands
7. `ccm.code-workspace` updated with new folders

### What Didn't Change

1. All imports in control-plane-api remain the same (relative imports)
2. API endpoints remain the same
3. UI functionality unchanged
4. Test suite unchanged (just moved)

## Next Steps

1. **Implement real etcd client** - Replace mock with `etcd3-py`
2. **Add placement algorithm** - Bin-packing in resource-scheduler
3. **Add Worker Controller reconciliation logic** - EC2/CloudWatch/CML System API integration
4. **Add Lablet Controller reconciliation logic** - CML Labs API integration
5. **Add health endpoints** - HTTP health checks for all services
6. **Add integration tests** - Cross-service communication tests
7. **Update documentation** - MkDocs architecture diagrams

## References

- [Lablet Resource Manager Implementation Plan](docs/implementation-plan/)
- [Architecture Decision Records](notes/)
- [Neuroglia Framework](https://github.com/neuroglia-io/framework-python)
