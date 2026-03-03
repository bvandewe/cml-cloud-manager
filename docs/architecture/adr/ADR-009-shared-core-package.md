# ADR-009: Shared Core Package Architecture

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-01-16 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-001](./ADR-001-api-centric-state-management.md), [ADR-002](./ADR-002-separate-resource-scheduler-service.md) |

## Context

The Lablet Cloud Manager consists of four microservices:

| Service | Port | Responsibility |
|---------|------|----------------|
| control-plane-api | 8020 | Single writer to MongoDB/etcd |
| resource-scheduler | 8081 | Scheduling & placement decisions |
| lablet-controller | 8082 | LabletInstance reconciliation via CML Labs SPI |
| worker-controller | 8083 | CML Worker reconciliation via Cloud Provider SPI |

**Problem:** Each service needs access to shared domain models (entities, enums, value objects, DTOs) and integration code (API clients, etcd abstractions). Without a centralized approach:

1. **Code duplication** - Same entity definitions copied across services
2. **Drift risk** - Entity definitions diverge over time
3. **Inconsistent contracts** - Different services use incompatible DTOs
4. **Maintenance burden** - Changes require updates in multiple places

Options considered:

1. **Copy-paste** - Each service maintains its own domain code
2. **Git submodule** - Shared code as a git submodule
3. **Published package** - Shared code as internal PyPI package
4. **Monorepo shared package** - Local package within monorepo

## Decision

**Implement a shared `core` package (`src/core/`) as a local Python package within the monorepo.**

All services depend on `lcm-core` for:

- Shared domain entities (read-only models for controllers)
- Shared enums and value objects
- CloudEvents schemas
- Control Plane API client
- etcd client abstractions
- Leader election utilities

## Rationale

### Benefits

| Benefit | Description |
|---------|-------------|
| **Single source of truth** | Domain models defined once, imported everywhere |
| **Type consistency** | DTOs and enums identical across services |
| **Easy refactoring** | Changes in one place propagate to all services |
| **Clear dependencies** | Explicit imports show what each service needs |
| **Version control** | Changes to core require explicit review |
| **Local development** | No package publishing needed during dev |

### Trade-offs

| Trade-off | Mitigation |
|-----------|------------|
| Coupling between services | Core only contains stable, shared abstractions |
| Versioning complexity | Use semantic versioning in core package |
| Larger CI scope | Core changes trigger all service tests |

### Why Not Alternatives?

| Alternative | Rejection Reason |
|-------------|-----------------|
| Copy-paste | High duplication, drift guaranteed |
| Git submodule | Complex workflow, poor IDE integration |
| Published package | Overkill for monorepo, adds publish step |

## Package Structure

```
src/
├── core/                                # NEW: Shared core package
│   ├── pyproject.toml                   # Package configuration
│   ├── README.md                        # Package documentation
│   ├── lcm_core/                        # Package source
│   │   ├── __init__.py
│   │   ├── domain/                      # Shared domain layer
│   │   │   ├── __init__.py
│   │   │   ├── entities/                # Read-only entity models
│   │   │   │   ├── __init__.py
│   │   │   │   ├── cml_worker.py        # CMLWorker read model
│   │   │   │   ├── lablet_instance.py   # LabletInstance read model
│   │   │   │   ├── lablet_definition.py # LabletDefinition read model
│   │   │   │   └── worker_template.py   # WorkerTemplate read model
│   │   │   ├── enums/                   # Shared enumerations
│   │   │   │   ├── __init__.py
│   │   │   │   ├── cml_worker_status.py
│   │   │   │   ├── lablet_instance_state.py
│   │   │   │   └── license_type.py
│   │   │   ├── value_objects/           # Shared value objects
│   │   │   │   ├── __init__.py
│   │   │   │   ├── resource_requirements.py
│   │   │   │   └── port_template.py
│   │   │   └── events/                  # CloudEvents schemas
│   │   │       ├── __init__.py
│   │   │       ├── instance_events.py
│   │   │       └── worker_events.py
│   │   ├── integration/                 # Shared integration layer
│   │   │   ├── __init__.py
│   │   │   ├── control_plane_api_client.py  # HTTP client for Control Plane API
│   │   │   ├── etcd_client.py           # etcd client wrapper
│   │   │   └── sse_client.py            # SSE subscription client
│   │   └── infrastructure/              # Shared infrastructure
│   │       ├── __init__.py
│   │       └── leader_election.py       # Leader election abstraction
│   └── tests/                           # Core package tests
│       ├── __init__.py
│       └── test_domain_models.py
├── control-plane-api/                   # OWNS aggregates (full write access)
├── resource-scheduler/                  # Uses: core.domain (read-only)
├── lablet-controller/                   # Uses: core.domain, core.integration
└── worker-controller/                   # Uses: core.domain, core.integration
```

## Domain Ownership Model

**Critical distinction: Control Plane API owns aggregates; controllers use read-only models.**

| Service | Domain Access | Description |
|---------|---------------|-------------|
| control-plane-api | Full aggregates | Owns persistence, event sourcing, state transitions |
| resource-scheduler | Read-only models | Makes placement decisions, no state mutations |
| lablet-controller | Read-only models | Reconciles via Control Plane API, not direct writes |
| worker-controller | Read-only models | Reconciles via Control Plane API, not direct writes |

### Read-Only vs Full Aggregates

**Full Aggregate (control-plane-api only):**

```python
# control-plane-api/domain/entities/cml_worker.py
class CMLWorker(AggregateRoot[CMLWorkerState]):
    """Full aggregate with event sourcing and state mutations."""

    def start(self) -> None:
        """Start the worker - records domain event."""
        self.record_event(CMLWorkerStartedDomainEvent(worker_id=self.id()))

    @dispatch(CMLWorkerStartedDomainEvent)
    def on(self, event: CMLWorkerStartedDomainEvent) -> None:
        self.state.status = CMLWorkerStatus.RUNNING
```

**Read-Only Model (core package):**

```python
# core/lcm_core/domain/entities/cml_worker.py
@dataclass(frozen=True)
class CMLWorkerReadModel:
    """Immutable read model for CMLWorker."""

    id: str
    name: str
    status: CMLWorkerStatus
    ec2_instance_id: str
    ip_address: str | None
    license_type: LicenseType
    capacity: ResourceRequirements

    @classmethod
    def from_dict(cls, data: dict) -> "CMLWorkerReadModel":
        """Create from API response."""
        return cls(
            id=data["id"],
            name=data["name"],
            status=CMLWorkerStatus(data["status"]),
            ec2_instance_id=data["ec2_instance_id"],
            ip_address=data.get("ip_address"),
            license_type=LicenseType(data["license_type"]),
            capacity=ResourceRequirements.from_dict(data["capacity"]),
        )
```

## Integration Patterns

### Control Plane API Client

All controllers communicate with Control Plane API via a shared HTTP client:

```python
# core/lcm_core/integration/control_plane_api_client.py
class ControlPlaneApiClient:
    """HTTP client for Control Plane API."""

    def __init__(self, base_url: str, api_key: str | None = None):
        self._base_url = base_url
        self._session = aiohttp.ClientSession(headers=self._auth_headers(api_key))

    async def list_workers(self) -> list[CMLWorkerReadModel]:
        """Get all workers."""
        async with self._session.get(f"{self._base_url}/api/v1/workers") as resp:
            data = await resp.json()
            return [CMLWorkerReadModel.from_dict(w) for w in data]

    async def update_worker_status(self, worker_id: str, status: CMLWorkerStatus) -> None:
        """Update worker status via API (not direct DB write)."""
        async with self._session.patch(
            f"{self._base_url}/api/internal/workers/{worker_id}/status",
            json={"status": status.value}
        ) as resp:
            resp.raise_for_status()
```

### Controller Pattern (Using Core)

```python
# worker-controller/application/services/worker_reconciler.py
from lcm_core.domain.entities import CMLWorkerReadModel
from lcm_core.domain.enums import CMLWorkerStatus
from lcm_core.integration import ControlPlaneApiClient

class WorkerReconciler:
    """Reconciles workers using read models and API mutations."""

    def __init__(self, api_client: ControlPlaneApiClient, cloud_spi: CloudProviderSPI):
        self._api = api_client
        self._cloud = cloud_spi

    async def reconcile(self) -> list[ReconciliationAction]:
        # Read current state via API
        workers = await self._api.list_workers()

        # Compare with actual cloud state
        ec2_instances = await self._cloud.describe_instances()

        actions = []
        for worker in workers:
            ec2 = ec2_instances.get(worker.ec2_instance_id)
            if worker.status == CMLWorkerStatus.RUNNING and not ec2:
                # Worker should be running but EC2 is missing
                actions.append(AlertMissingInstanceAction(worker))

        return actions
```

## Dependency Configuration

### pyproject.toml (core)

```toml
[tool.poetry]
name = "lcm-core"
version = "0.1.0"
description = "Shared core package for Lablet Cloud Manager services"
packages = [{include = "lcm_core"}]

[tool.poetry.dependencies]
python = ">=3.11,<4.0"
aiohttp = ">=3.9.0,<4.0.0"
pydantic = ">=2.0.0,<3.0.0"

[tool.poetry.group.dev.dependencies]
pytest = ">=7.0.0"
pytest-asyncio = ">=0.21.0"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

### pyproject.toml (services)

```toml
# In control-plane-api/pyproject.toml, resource-scheduler/pyproject.toml, etc.
[tool.poetry.dependencies]
lcm-core = {path = "../core", develop = true}
```

Then run `poetry install` in each service directory.

### Usage in Services

```python
# Any service can import from core
from lcm_core.domain.entities import CMLWorkerReadModel, LabletInstanceReadModel
from lcm_core.domain.enums import CMLWorkerStatus, LabletInstanceState
from lcm_core.integration import ControlPlaneApiClient
```

## Consequences

### Positive

- **No duplication** - Single source of truth for shared code
- **Type safety** - Consistent types across all services
- **Faster development** - Changes propagate automatically
- **Clear boundaries** - Explicit dependency on core package
- **Testable in isolation** - Core package has its own test suite

### Negative

- **Coupling** - Core changes affect all services
- **CI complexity** - Core changes trigger full test suite
- **Versioning discipline** - Breaking changes require coordination

### Mitigation

- Core package follows semantic versioning
- Breaking changes require explicit version bump
- CI runs all service tests when core changes
- Regular review of core API surface

## Implementation

### Phase 2 Prerequisite

Create `src/core/` package structure before Phase 2 begins:

1. Create package scaffold with empty implementations
2. Add to all service dependencies
3. Migrate shared enums first (lowest risk)
4. Incrementally migrate value objects, then entities
5. Add ControlPlaneApiClient for controller use

### Migration Path

| Step | Items | Risk |
|------|-------|------|
| 1 | Package scaffold | None |
| 2 | Shared enums | Low |
| 3 | Value objects | Low |
| 4 | Read-only entity models | Medium |
| 5 | ControlPlaneApiClient | Medium |
| 6 | etcd client wrapper | Medium |
| 7 | Leader election abstraction | Low |

## Related Decisions

- **[ADR-001](./ADR-001-api-centric-state-management.md)**: Control Plane API as single writer (controllers use API client from core)
- **[ADR-002](./ADR-002-separate-resource-scheduler-service.md)**: Scheduler as separate service (uses core for read models)
- **Phase 3.5**: Migration of worker runtime jobs to worker-controller (will use core.integration)
