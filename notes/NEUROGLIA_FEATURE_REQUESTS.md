# Neuroglia Framework - Feature Requests & Gap Analysis

## Context

This document captures identified gaps in the Neuroglia framework that would enhance
the developer experience for building CQRS/DDD microservices with automatic seeding
and schema generation capabilities.

**Date**: 2026-01-17
**Project**: Lablet Cloud Manager
**Framework Version**: neuroglia (latest)

---

## Feature Request 1: Automatic Aggregate Schema Generation

### Current Situation

Aggregates in Neuroglia require manual creation of DTOs, YAML schemas, and serialization
mappings. When creating seeders or export functionality, developers must manually
define the serialization format and validation rules.

### Desired Behavior

The framework should provide automatic schema generation for AggregateRoot classes:

```python
from neuroglia.data.abstractions import AggregateRoot
from neuroglia.schema import generate_yaml_schema, generate_json_schema

# Generate JSON Schema for validation
schema = generate_json_schema(WorkerTemplate)
# -> Returns JSON Schema object with all properties, types, constraints

# Generate sample YAML for seeding
sample = generate_yaml_sample(WorkerTemplate)
# -> Returns valid YAML with all fields and default values

# Export aggregate to YAML (for backup/migration)
yaml_content = export_to_yaml(aggregate)
```

### Benefits

- Reduced boilerplate for YAML-based seeding
- Consistent serialization format across all aggregates
- Auto-generated documentation for seed file formats
- Schema validation before entity creation

### Implementation Suggestions

1. Leverage Python dataclass introspection for AggregateState
2. Support custom serializers via `@yaml_field` decorators
3. Include Pydantic integration for validation
4. Generate both JSON Schema and YAML examples

---

## Feature Request 2: Built-in HostedService for Database Seeding

### Current Situation

Each project must implement its own DatabaseSeeder infrastructure with:

- YAML file discovery
- Entity creation from dictionary
- Idempotent seeding logic
- Result tracking

### Desired Behavior

Neuroglia should provide a built-in seeding infrastructure:

```python
from neuroglia.hosting.seeding import DatabaseSeeder, EntitySeeder

class WorkerTemplateSeeder(EntitySeeder[WorkerTemplate]):
    # Minimal implementation - framework handles discovery, loading, tracking

builder.add_seeder(WorkerTemplateSeeder())
```

### Benefits

- Consistent seeding patterns across all Neuroglia projects
- Reduced per-project infrastructure code
- Framework-level optimizations for bulk seeding

---

## Feature Request 3: Add Hosted Service Registration Helper

### Current Situation

Registering a HostedService for automatic lifecycle management requires:

```python
# Register concrete type
builder.services.add_singleton(MyHostedService, factory)

# Also register as generic HostedService
builder.services.add_singleton(
    HostedService,
    implementation_factory=lambda sp: sp.get_required_service(MyHostedService),
)
```

### Desired Behavior

Simplified registration:

```python
# Single call handles both registrations
builder.services.add_hosted_service(MyHostedService, factory)
```

### Benefits

- Cleaner configuration code
- Less error-prone (can't forget the generic registration)
- More intuitive API

---

## Feature Request 4: Lifespan Context Manager Access

### Current Situation

When using `build_app_with_lifespan()`, there's no easy way to add custom
startup/shutdown logic alongside the HostedService management.

### Desired Behavior

Support for custom lifespan hooks:

```python
async def on_startup(app, services):
    """Custom startup logic after HostedServices start."""
    logger.info("Custom initialization...")

async def on_shutdown(app, services):
    """Custom shutdown logic before HostedServices stop."""
    logger.info("Custom cleanup...")

app = builder.build_app_with_lifespan(
    on_startup=on_startup,
    on_shutdown=on_shutdown,
)
```

### Benefits

- Flexibility for project-specific initialization
- Clean separation from HostedService lifecycle
- No need to fall back to deprecated `on_event` decorators

---

## Feature Request 5: Repository Export/Import Methods

### Current Situation

Repositories only support CRUD operations. Exporting all entities for backup
or migration requires manual iteration and serialization.

### Desired Behavior

Built-in export/import support on repositories:

```python
# Export all entities to YAML
async def export_all_to_yaml(self, output_dir: Path) -> int:
    """Export all entities to individual YAML files."""

# Import entities from YAML (with conflict resolution)
async def import_from_yaml(
    self,
    input_dir: Path,
    on_conflict: ConflictResolution = ConflictResolution.SKIP,
) -> ImportResult:
    """Import entities from YAML files."""
```

### Benefits

- Standardized backup/restore functionality
- Easy data migration between environments
- Support for declarative infrastructure-as-code patterns

---

## Feature Request 6: Aggregate Validation Decorators

### Current Situation

Validation logic is scattered across entity creation methods and must be
manually synchronized with YAML schema expectations.

### Desired Behavior

Declarative validation on AggregateState fields:

```python
class WorkerTemplateState(AggregateState[str]):
    @required
    @min_length(1)
    @max_length(50)
    name: str

    @required
    @range(min=0.0, max=100.0)
    cost_per_hour_usd: float

    @pattern(r"CML-.*")
    ami_name_pattern: str
```

### Benefits

- Single source of truth for validation rules
- Auto-generated YAML schema includes constraints
- Clearer error messages on seed failures

---

## Summary of Priorities

| Feature | Priority | Effort | Impact |
|---------|----------|--------|--------|
| FR3: Hosted Service Registration Helper | High | Low | Medium |
| FR4: Lifespan Context Manager Access | High | Low | High |
| FR2: Built-in Database Seeding | Medium | Medium | High |
| FR1: Automatic Schema Generation | Medium | High | High |
| FR5: Repository Export/Import | Low | Medium | Medium |
| FR6: Validation Decorators | Low | High | Medium |

---

## Workarounds Implemented

In the absence of these framework features, the Lablet Cloud Manager project
has implemented the following in `lcm-core`:

1. **DatabaseSeeder**: Generic seeding infrastructure with EntitySeeder protocol
2. **DatabaseSeederService**: HostedService wrapper for automatic startup seeding
3. **SeedResult/SeedSummary**: Result tracking dataclasses
4. **Manual HostedService registration**: Pattern documented in copilot-instructions

These workarounds are located in `src/core/lcm_core/infrastructure/seeding/`.
