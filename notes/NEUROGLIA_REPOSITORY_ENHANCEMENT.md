# Neuroglia Framework Enhancement: MotorRepository Domain Layer Registration

## Current Issue

When using `MotorRepository.configure()`, it only registers the repository as `Repository[TEntity, TKey]` and `MotorRepository[TEntity, TKey]`. However, domain-driven design projects typically define abstract repository interfaces in the domain layer (e.g., `TaskRepository`, `CustomerRepository`) to maintain separation of concerns.

This forces users to manually add a factory registration for each domain repository interface:

```python
# Current workaround required
MotorRepository.configure(
    builder,
    entity_type=Task,
    key_type=str,
    database_name="lablet_cloud_manager",
    collection_name="tasks",
)

# Additional factory needed for domain layer interface
def get_task_repository(sp) -> TaskRepository:
    return sp.get_required_service(MotorRepository[Task, str])

services.add_scoped(TaskRepository, implementation_factory=get_task_repository)
```

## Proposed Enhancement

Add an optional `domain_repository_type` parameter to `MotorRepository.configure()` that automatically registers the domain repository interface.

### Enhanced API

```python
@staticmethod
def configure(
    builder: ApplicationBuilderBase,
    entity_type: type[TEntity],
    key_type: type[TKey],
    database_name: str,
    collection_name: Optional[str] = None,
    connection_string_name: str = "mongo",
    domain_repository_type: Optional[type] = None,  # NEW PARAMETER
) -> ApplicationBuilderBase:
```

### Implementation

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
    """
    Configure the application to use MotorRepository for a specific entity type.

    This static method provides a fluent API for registering Motor repositories
    with the dependency injection container, following Neuroglia's configuration patterns.

    Args:
        builder: Application builder instance
        entity_type: The entity type this repository will manage
        key_type: The type of the entity's unique identifier
        database_name: Name of the MongoDB database
        collection_name: Optional collection name (defaults to lowercase entity name)
        connection_string_name: Name of connection string in settings (default: "mongo")
        domain_repository_type: Optional domain-layer repository interface to register
                                (e.g., TaskRepository, CustomerRepository). When provided,
                                this abstract interface will be registered to resolve to
                                the same MotorRepository instance, maintaining DDD separation.

    Returns:
        The configured application builder (for fluent chaining)

    Example:

        # Basic usage without domain interface
        MotorRepository.configure(
            builder,
            entity_type=Task,
            key_type=str,
            database_name="lablet_cloud_manager"
        )

        # DDD usage with domain repository interface
        from domain.repositories import TaskRepository

        MotorRepository.configure(
            builder,
            entity_type=Task,
            key_type=str,
            database_name="lablet_cloud_manager",
            collection_name="tasks",
            domain_repository_type=TaskRepository  # Automatically registers domain interface
        )

        # Now handlers can depend on TaskRepository:
        class CreateTaskCommandHandler(CommandHandler):
            def __init__(self, repository: TaskRepository):  # Uses domain interface
                self.repository = repository  # Gets MotorRepository with mediator

    """
    # Get connection string from settings
    connection_string = builder.settings.connection_strings.get(connection_string_name, None)
    if connection_string is None:
        raise Exception(f"Missing '{connection_string_name}' connection string in application settings")

    # Import Motor client here to avoid circular imports
    from motor.motor_asyncio import AsyncIOMotorClient

    # Register AsyncIOMotorClient as singleton (shared across all repositories)
    builder.services.try_add_singleton(
        AsyncIOMotorClient,
        singleton=AsyncIOMotorClient(connection_string),
    )

    # Determine collection name (default to lowercase entity name)
    if collection_name is None:
        collection_name = entity_type.__name__.lower()
        # Remove common suffixes
        if collection_name.endswith("dto"):
            collection_name = collection_name[:-3]

    # Factory function to create MotorRepository with proper entity type
    def create_motor_repository(sp):
        # Try to get mediator, but allow it to be None (for testing or when not configured)
        mediator = sp.get_service(Mediator)  # Returns None if not registered
        return MotorRepository(
            client=sp.get_required_service(AsyncIOMotorClient),
            database_name=database_name,
            collection_name=collection_name,
            serializer=sp.get_required_service(JsonSerializer),
            entity_type=entity_type,
            mediator=mediator,
        )

    # Factory function to resolve abstract Repository interface
    def get_repository_interface(sp):
        return sp.get_required_service(MotorRepository[entity_type, key_type])

    # Register the concrete MotorRepository with SCOPED lifetime
    builder.services.add_scoped(
        MotorRepository[entity_type, key_type],
        implementation_factory=create_motor_repository,
    )

    # Register the abstract Repository interface that handlers expect (also SCOPED)
    builder.services.add_scoped(
        Repository[entity_type, key_type],
        implementation_factory=get_repository_interface,
    )

    # NEW: Register domain repository interface if provided
    if domain_repository_type is not None:
        def get_domain_repository(sp):
            return sp.get_required_service(MotorRepository[entity_type, key_type])

        builder.services.add_scoped(
            domain_repository_type,
            implementation_factory=get_domain_repository,
        )
        logger.debug(
            f"Registered domain repository interface {domain_repository_type.__name__} "
            f"-> MotorRepository[{entity_type.__name__}, {key_type.__name__}]"
        )

    return builder
```

### Usage After Enhancement

```python
from domain.repositories import TaskRepository

# Single line configuration - automatically registers both framework and domain interfaces
MotorRepository.configure(
    builder,
    entity_type=Task,
    key_type=str,
    database_name="lablet_cloud_manager",
    collection_name="tasks",
    domain_repository_type=TaskRepository,  # Domain layer interface
)

# No additional factory registration needed!
# TaskRepository automatically resolves to MotorRepository[Task, str] with mediator
```

## Benefits

1. **Cleaner Configuration**: Single `configure()` call instead of configure + factory
2. **DDD Alignment**: Explicitly supports domain layer repository interfaces
3. **Reduced Boilerplate**: Eliminates repetitive factory functions
4. **Type Safety**: Domain interfaces remain strongly typed
5. **Consistency**: Ensures domain interface gets same instance (with mediator) as framework interface
6. **Backward Compatible**: Optional parameter doesn't break existing code

## Migration Path

Existing code continues to work unchanged. Users can opt-in to the enhancement:

**Before:**

```python
MotorRepository.configure(builder, Task, str, "db")
def factory(sp) -> TaskRepository:
    return sp.get_required_service(MotorRepository[Task, str])
services.add_scoped(TaskRepository, implementation_factory=factory)
```

**After:**

```python
MotorRepository.configure(
    builder, Task, str, "db",
    domain_repository_type=TaskRepository
)
```

## Related Enhancements

Consider similar enhancements for:

- `EnhancedMongoRepository.configure()`
- Other repository implementations (SQL, etc.)
- Generic pattern for all infrastructure registrations that map to domain interfaces

## Testing Considerations

1. Verify mediator injection works through domain interface
2. Test that domain events are properly published
3. Ensure scoped lifetime is maintained
4. Confirm type hints work correctly with IDE/mypy
5. Validate backward compatibility with existing code

## Documentation Updates Required

1. Update `MotorRepository.configure()` docstring
2. Add example to DDD patterns guide
3. Update migration guide for existing projects
4. Add note about domain layer separation of concerns
