# Neuroglia Repository Registration Enhancement

## Current Status (v0.6.5)

Neuroglia v0.6.5 includes the `domain_repository_type` parameter in `MotorRepository.configure()`, but it only registers the domain interface to resolve to the **base** `MotorRepository[Entity, Key]` class.

### Current Behavior

```python
MotorRepository.configure(
    builder,
    entity_type=Task,
    key_type=str,
    database_name="lablet_cloud_manager",
    collection_name="tasks",
    domain_repository_type=TaskRepository,  # Resolves to MotorRepository[Task, str]
)
```

**Result**: `TaskRepository` resolves to `MotorRepository[Task, str]`, which only includes base CRUD methods and lacks custom domain-specific queries.

### Current Workaround

To use custom repository implementations (like `MongoTaskRepository` with methods like `get_by_id_async`, `get_by_assignee_async`, etc.), we must manually override the registration:

```python
# Step 1: Configure base repository (infrastructure setup)
MotorRepository.configure(
    builder,
    entity_type=Task,
    key_type=str,
    database_name="lablet_cloud_manager",
    collection_name="tasks",
)

# Step 2: Override with custom implementation
services.add_scoped(TaskRepository, MongoTaskRepository)
```

This works but requires two steps instead of one.

---

## Desired Behavior

### Goal: Single-Line Registration

Enable automatic detection and registration of custom repository implementations that extend `MotorRepository`:

```python
# Desired: One line, auto-discovers MongoTaskRepository
MotorRepository.configure(
    builder,
    entity_type=Task,
    key_type=str,
    database_name="lablet_cloud_manager",
    collection_name="tasks",
    domain_repository_type=TaskRepository,  # Should resolve to MongoTaskRepository
)
```

---

## Required Enhancement

### Implementation Strategy

Add an explicit `implementation_type` parameter to `MotorRepository.configure()` that allows specifying the custom repository implementation class directly.

**Design Principles**:

- **Explicit over implicit**: Developers specify exactly which implementation to use
- **Type-safe**: IDEs can validate implementation types at development time
- **Flexible**: Works with any naming convention or project structure
- **Simple**: No complex discovery logic or magic behavior

### Proposed Code Changes

**File**: `neuroglia/data/infrastructure/mongo/motor_repository.py`

**Current Implementation** (simplified):

```python
@staticmethod
def configure(
    builder: ApplicationBuilderBase,
    entity_type: type[TEntity],
    key_type: type[TKey],
    database_name: str,
    collection_name: Optional[str] = None,
    connection_string_name: str = "mongo",
    domain_repository_type: Optional[type] = None,
) -> ApplicationBuilderBase:
    """Configure the application to use MotorRepository."""

    # ... MongoDB client setup ...

    # Register base MotorRepository
    builder.services.add_scoped(
        MotorRepository[entity_type, key_type],
        implementation_factory=lambda sp: MotorRepository(
            client=sp.get_required_service(AsyncIOMotorClient),
            serializer=sp.get_required_service(JsonSerializer),
            mediator=sp.get_required_service(Mediator),
            # ... other args ...
        ),
    )

    # Register domain interface (points to base MotorRepository)
    if domain_repository_type:
        builder.services.add_scoped(
            domain_repository_type,
            implementation_factory=lambda sp: sp.get_required_service(
                MotorRepository[entity_type, key_type]
            ),
        )

    return builder
```

**Proposed Enhancement**:

```python
@staticmethod
def configure(
    builder: ApplicationBuilderBase,
    entity_type: type[TEntity],
    key_type: type[TKey],
    database_name: str,
    collection_name: Optional[str] = None,
    connection_string_name: str = "mongo",
    domain_repository_type: Optional[type] = None,
    implementation_type: Optional[type] = None,  # NEW PARAMETER
) -> ApplicationBuilderBase:
    """Configure the application to use MotorRepository.

    Args:
        builder: Application builder instance
        entity_type: The entity type this repository will manage
        key_type: The type of the entity's unique identifier
        database_name: Name of the MongoDB database
        collection_name: Optional collection name (defaults to lowercase entity name)
        connection_string_name: Name of connection string in settings (default: "mongo")
        domain_repository_type: Optional domain-layer repository interface to register
        implementation_type: Optional custom repository implementation class.
            If provided with domain_repository_type, this implementation will be
            registered for the domain interface instead of base MotorRepository.
            Must extend MotorRepository[entity_type, key_type].
    """

    # ... MongoDB client setup ...

    # Determine which implementation to use
    impl_type = implementation_type if implementation_type else MotorRepository[entity_type, key_type]

    # Validate implementation_type if provided
    if implementation_type and not issubclass(implementation_type, MotorRepository):
        raise ValueError(
            f"implementation_type {implementation_type.__name__} must extend "
            f"MotorRepository[{entity_type.__name__}, {key_type.__name__}]"
        )

    # Register the implementation
    builder.services.add_scoped(
        MotorRepository[entity_type, key_type],
        impl_type,
    )

    # Register domain interface if provided
    if domain_repository_type:
        builder.services.add_scoped(
            domain_repository_type,
            impl_type,
        )

    return builder
```

---

## Benefits of Enhancement

### 1. **Cleaner Application Code**

```python
# Before (current workaround)
MotorRepository.configure(builder, ...)
services.add_scoped(TaskRepository, MongoTaskRepository)

# After (with enhancement)
MotorRepository.configure(
    builder,
    ...,
    domain_repository_type=TaskRepository,
    implementation_type=MongoTaskRepository,
)
```

### 2. **Explicit and Clear**

- No magic or hidden behavior
- Developer explicitly specifies which implementation to use
- Easy to understand and debug

### 3. **Type-Safe and IDE-Friendly**

- IDEs can validate the implementation type at development time
- Auto-completion helps discover available implementations
- Compile-time type checking prevents errors

### 4. **Flexible and Maintainable**

- Works with any naming convention or project structure
- No assumptions about where implementations are located
- Simple to test and reason about

---

## Usage Example

```python
from domain.entities import Task
from domain.repositories import TaskRepository
from integration.repositories.motor_task_repository import MongoTaskRepository

# Single-line registration with explicit implementation
MotorRepository.configure(
    builder,
    entity_type=Task,
    key_type=str,
    database_name="lablet_cloud_manager",
    collection_name="tasks",
    domain_repository_type=TaskRepository,
    implementation_type=MongoTaskRepository,
)
```

This achieves the goal of single-line registration while maintaining explicitness and clarity.

---

## Testing Strategy

### Unit Tests

```python
def test_configure_with_custom_repository():
    """Test that custom repository implementation is registered correctly."""
    builder = WebApplicationBuilder()

    MotorRepository.configure(
        builder,
        entity_type=Task,
        key_type=str,
        database_name="test_db",
        domain_repository_type=TaskRepository,
        implementation_type=MongoTaskRepository,
    )

    # Should resolve to MongoTaskRepository (custom)
    repo = builder.services.get_service(TaskRepository)
    assert isinstance(repo, MongoTaskRepository)
    assert hasattr(repo, 'get_by_assignee_async')  # Custom method


def test_configure_without_custom_repository():
    """Test fallback to base MotorRepository when no implementation_type provided."""
    builder = WebApplicationBuilder()

    MotorRepository.configure(
        builder,
        entity_type=SomeEntity,
        key_type=str,
        database_name="test_db",
        domain_repository_type=SomeRepository,
    )

    # Should resolve to base MotorRepository
    repo = builder.services.get_service(SomeRepository)
    assert isinstance(repo, MotorRepository)
    assert type(repo).__name__ == 'MotorRepository'


def test_configure_invalid_implementation_type():
    """Test that invalid implementation_type raises ValueError."""
    builder = WebApplicationBuilder()

    class NotARepository:
        pass

    with pytest.raises(ValueError, match="must extend MotorRepository"):
        MotorRepository.configure(
            builder,
            entity_type=Task,
            key_type=str,
            database_name="test_db",
            domain_repository_type=TaskRepository,
            implementation_type=NotARepository,
        )
```

### Integration Tests

- Test with real MongoDB connection
- Verify mediator injection works
- Confirm domain events are published
- Test custom query methods

---

## Migration Path

### For Existing Applications

**Current Code**:

```python
MotorRepository.configure(builder, ...)
services.add_scoped(TaskRepository, MongoTaskRepository)
```

**After Enhancement (Backward Compatible)**:

```python
# Option 1: Keep current approach (still works)
MotorRepository.configure(builder, ...)
services.add_scoped(TaskRepository, MongoTaskRepository)

# Option 2: Use explicit implementation_type parameter (preferred)
MotorRepository.configure(
    builder,
    entity_type=Task,
    key_type=str,
    database_name="lablet_cloud_manager",
    collection_name="tasks",
    domain_repository_type=TaskRepository,
    implementation_type=MongoTaskRepository,
)
```

Both approaches would work, allowing gradual migration.

---

## Related Issues

- Original enhancement request documented in `NEUROGLIA_REPOSITORY_ENHANCEMENT.md`
- Issue tracking: [Link to neuroglia GitHub issue if created]

---

## Implementation Timeline

**Phase 1**: Core explicit parameter mechanism

- Add optional `implementation_type` parameter to `MotorRepository.configure()`
- Implement validation logic (ensure implementation extends MotorRepository)
- Update registration logic to use implementation_type when provided
- Add unit tests

**Phase 2**: Documentation & Examples

- Update neuroglia documentation
- Add cookbook examples showing explicit parameter usage
- Migration guide for existing applications

**Phase 3**: Community Adoption

- Gather feedback from users
- Refine error messages based on common mistakes
- Add more examples for common patterns
