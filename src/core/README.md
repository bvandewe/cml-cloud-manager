# CCM Core Package

Shared core package for Lablet Cloud Manager microservices.

## Overview

This package provides shared domain models, enums, value objects, and integration utilities used across all Lablet Cloud Manager services:

- **control-plane-api**: Central API gateway (owns full aggregates)
- **resource-scheduler**: Scheduling and placement decisions
- **lablet-controller**: LabletInstance reconciliation
- **worker-controller**: CML Worker reconciliation

## Package Structure

```
lcm_core/
├── domain/           # Shared domain layer
│   ├── entities/     # Read-only entity models
│   ├── enums/        # Shared enumerations
│   ├── value_objects/# Shared value objects
│   └── events/       # CloudEvents schemas
├── integration/      # Shared integration layer
│   ├── control_plane_api_client.py
│   ├── etcd_client.py
│   └── sse_client.py
└── infrastructure/   # Shared infrastructure
    └── leader_election.py
```

## Installation

**Using Poetry (recommended for this project):**

Add to your service's `pyproject.toml`:

```toml
[tool.poetry.dependencies]
lcm-core = {path = "../core", develop = true}
```

Then run:

```bash
cd src/control-plane-api  # or any service directory
poetry install
```

**For core package development:**

```bash
cd src/core
poetry install
poetry run pytest tests/ -v
```

## Usage

```python
from lcm_core.domain.entities import CMLWorkerReadModel, LabletInstanceReadModel
from lcm_core.domain.enums import CMLWorkerStatus, LabletInstanceState
from lcm_core.integration import ControlPlaneApiClient
```

## Design Principles

1. **Read-Only Models**: Controllers use immutable read models, not full aggregates
2. **API-Centric**: All state mutations go through Control Plane API
3. **Minimal Dependencies**: Core has minimal external dependencies
4. **Stability**: Core API surface is stable; breaking changes require version bump

## Related Documentation

- [ADR-009: Shared Core Package Architecture](../../docs/architecture/adr/ADR-009-shared-core-package.md)
- [ADR-001: API-Centric State Management](../../docs/architecture/adr/ADR-001-api-centric-state-management.md)
