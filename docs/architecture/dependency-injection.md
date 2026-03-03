# Dependency Injection with Neuroglia

This application uses Neuroglia's dependency injection (DI) system, which provides constructor injection and service lifetime management.

## DI Container Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│              ServiceCollectionBuilder                            │
│         Registers services during startup                        │
└─────────────────────────────────────────────────────────────────┘
                               │
                               │ build()
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              ServiceProviderBase                                 │
│          Runtime service resolution                              │
└─────────────────────────────────────────────────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
       ┌───────────────────────┐  ┌──────────────────┐
       │    Controllers         │  │    Handlers      │
       │  (via framework)       │  │  (via Mediator)  │
       └───────────────────────┘  └──────────────────┘
```

## Service Lifetimes

### Singleton

**Lifetime**: One instance for entire application lifetime

**Use Cases**:

- Configuration objects
- Connection pools
- Shared caches
- Stateless services

```python
# Registration
services.add_singleton(AuthService, singleton=auth_service_instance)

# Or with factory
services.add_singleton(ConfigService)
```

### Scoped

**Lifetime**: One instance per request/scope

**Use Cases**:

- Repositories
- Database contexts
- Request-specific services

```python
# Registration
services.add_scoped(TaskRepository, MongoTaskRepository)

# Each request gets new instance
```

### Transient

**Lifetime**: New instance every time

**Use Cases**:

- Lightweight services
- Stateless operations
- Short-lived objects

```python
# Registration
services.add_transient(TaskValidator)

# New instance on each resolution
```

## Registration Patterns

### Interface → Implementation

```python
from domain.repositories import TaskRepository
from integration.repositories import MongoTaskRepository

# Register implementation for interface
services.add_scoped(TaskRepository, MongoTaskRepository)
```

### Concrete Class

```python
from infrastructure.session_store import SessionStore

# Register concrete class
services.add_singleton(SessionStore)
```

### Factory Function

```python
def create_session_store() -> SessionStore:
    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT
    )
    return SessionStore(redis_client)

# Register with factory
services.add_singleton(SessionStore, factory=create_session_store)
```

### Existing Instance

```python
# Create instance
session_store = SessionStore(redis_client)

# Register singleton instance
services.add_singleton(SessionStore, singleton=session_store)
```

## Application Setup

### Main Startup (src/main.py)

```python
from neuroglia.hosting.web import WebApplicationBuilder
from neuroglia.mediation import Mediator
from neuroglia.data.infrastructure.mongo import MotorRepository
from domain.repositories import TaskRepository
from integration.repositories.motor_task_repository import MongoTaskRepository
from infrastructure import RedisSessionStore, SessionStore
from api.services import AuthService

def create_app() -> FastAPI:
    builder = WebApplicationBuilder()

    # 1. Configure Mediator (auto-discovers handlers)
    Mediator.configure(builder, [
        "application.commands",
        "application.queries"
    ])

    # 2. Configure MongoDB repository
    MotorRepository.configure(
        builder,
        entity_type=Task,
        key_type=str,
        database_name="lablet_cloud_manager",
        collection_name="tasks"
    )

    # 3. Register services
    services = builder.services
    services.add_scoped(TaskRepository, MongoTaskRepository)

    session_store = RedisSessionStore() # Or InMemorySessionStore
    services.add_singleton(SessionStore, singleton=session_store)

    auth_service = AuthService(session_store)
    services.add_singleton(AuthService, singleton=auth_service)

    # 4. Add SubApps for API and UI
    builder.add_sub_app(...)

    # 5. Build the application
    app = builder.build_app_with_lifespan()

    return app
```

## Injection in Components

### Controllers

Controllers receive three standard dependencies:

```python
from neuroglia.mvc.controller_base import ControllerBase

class TasksController(ControllerBase):
    def __init__(
        self,
        service_provider: ServiceProviderBase,  # DI container
        mapper: Mapper,                         # Object mapping
        mediator: Mediator                      # CQRS mediator
    ):
        super().__init__(service_provider, mapper, mediator)

        # Access additional services via service locator
        # (only for infrastructure concerns)
        session_store = service_provider.get_service(SessionStore)
```

**Note**: Controllers typically use Mediator, not repositories directly.

### Command/Query Handlers

Handlers receive dependencies via constructor:

```python
from neuroglia.mediation import CommandHandler
from domain.repositories import TaskRepository
from application.commands import CreateTaskCommand

class CreateTaskCommandHandler(CommandHandler[CreateTaskCommand, OperationResult]):
    def __init__(
        self,
        task_repository: TaskRepository   # Injected dependency
    ):
        super().__init__()
        self.task_repository = task_repository
```

All constructor parameters are auto-resolved from DI container.

### Repositories

Repositories can inject database connections:

```python
from motor.motor_asyncio import AsyncIOMotorDatabase

class MongoTaskRepository(TaskRepository):
    def __init__(self, database: AsyncIOMotorDatabase):
        self.database = database
        self.collection = database["tasks"]
```

## Bridging Neuroglia DI to FastAPI

### The Challenge

- Neuroglia controllers use Neuroglia DI
- FastAPI route functions use `Depends()`
- Different dependency systems need integration

### Solution: Middleware Bridge

```python
# Create shared instance
auth_service_instance = AuthService(session_store)

# Register in Neuroglia DI
services.add_singleton(AuthService, singleton=auth_service_instance)

# Inject into FastAPI via middleware
@app.middleware("http")
async def inject_auth_service(request, call_next):
    request.state.auth_service = auth_service_instance
    response = await call_next(request)
    return response
```

### FastAPI Dependency Access

```python
from fastapi import Request, Depends

def get_auth_service(request: Request) -> AuthService:
    """Retrieve from request state."""
    return request.state.auth_service

async def get_current_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service)
) -> dict:
    """Use injected service."""
    return auth_service.authenticate(...)
```

## MongoDB Repository Configuration

### Using Neuroglia's MotorRepository

Neuroglia provides MongoDB support via its `MotorRepository`.

```python
from neuroglia.data.infrastructure.mongo import MotorRepository
from domain.entities import Task

# Configure during startup in main.py
MotorRepository.configure(
    builder,
    entity_type=Task,
    key_type=str,
    database_name="lablet_cloud_manager",
    collection_name="tasks"
)

# Register custom repository that extends it
services.add_scoped(TaskRepository, MongoTaskRepository)
```

### Custom Repository Implementation

The custom repository inherits from `MotorRepository` and `TracedRepositoryMixin` to get standard CRUD operations and automatic tracing.

```python
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.data.infrastructure.tracing_mixin import TracedRepositoryMixin
from domain.repositories import TaskRepository
from domain.entities import Task

class MongoTaskRepository(
    TracedRepositoryMixin,
    MotorRepository[Task, str],
    TaskRepository
):
    """MongoDB implementation of TaskRepository."""

    def __init__(self, mongo_client, serializer, mediator=None):
        super().__init__(
            client=mongo_client,
            database_name="lablet_cloud_manager",
            collection_name="tasks",
            serializer=serializer,
            mediator=mediator
        )

    async def get_by_department_async(self, department: str) -> list[Task]:
        """Custom query method."""
        cursor = self.collection.find({"department": department})
        tasks = [self._deserialize_entity(doc) async for doc in cursor]
        return tasks
```

## Service Locator Pattern

### When to Use

Only for infrastructure concerns in controllers:

- Session management
- Caching
- Third-party integrations
- Protocol-specific handlers

### Implementation

```python
class AuthController(ControllerBase):
    def __init__(self, service_provider, mapper, mediator):
        super().__init__(service_provider, mapper, mediator)

        # Service locator for infrastructure
        session_store = service_provider.get_service(SessionStore)
        if session_store is None:
            raise RuntimeError("SessionStore not registered")
        self.session_store = session_store
```

### Why Avoid in Handlers

❌ Handlers should use constructor injection
❌ Hidden dependencies make testing harder
❌ Service locator is an anti-pattern for business logic
✅ Use constructor injection for all handler dependencies

## Testing with DI

### Unit Testing Handlers

Mock dependencies in tests:

```python
from unittest.mock import Mock, AsyncMock

async def test_create_task_handler():
    # Mock dependencies
    mock_repository = Mock(TaskRepository)
    mock_repository.add_async = AsyncMock()

    # Create handler with mocks
    handler = CreateTaskCommandHandler(
        task_repository=mock_repository
    )

    # Test
    command = CreateTaskCommand(title="Test", description="Test", priority="high")
    await handler.handle_async(command)

    # Verify
    mock_repository.add_async.assert_called_once()
```

### Integration Testing

Use test DI container:

```python
def create_test_services():
    builder = ServiceCollectionBuilder()

    # Register test implementations
    builder.add_scoped(TaskRepository, InMemoryTaskRepository)

    return builder.build()

async def test_task_creation_integration():
    services = create_test_services()

    # Resolve handler from container
    handler = services.get_service(CreateTaskCommandHandler)

    # Test with real DI resolution
    command = CreateTaskCommand(...)
    result = await handler.handle_async(command, None)

    assert result is not None
```

## Common Patterns

### Conditional Registration

```python
if settings.USE_MONGODB:
    services.add_scoped(TaskRepository, MongoTaskRepository)
else:
    services.add_scoped(TaskRepository, InMemoryTaskRepository)
```

### Configuration Injection

```python
from application.settings import Settings

# Register configuration
settings = Settings()
services.add_singleton(Settings, singleton=settings)

# Inject into services
class EmailService:
    def __init__(self, settings: Settings):
        self.smtp_host = settings.SMTP_HOST
```

### Multiple Implementations

```python
# Register multiple named services
services.add_scoped(TaskRepository, MongoTaskRepository)
services.add_scoped(CachedTaskRepository)

# Resolve specific implementation
class TaskService:
    def __init__(
        self,
        primary_repo: TaskRepository,
        cached_repo: CachedTaskRepository
    ):
        self.primary = primary_repo
        self.cached = cached_repo
```

## Best Practices

✅ **Prefer constructor injection** - Clear dependencies
✅ **Use appropriate lifetimes** - Singleton/Scoped/Transient
✅ **Register interfaces** - Depend on abstractions
✅ **One responsibility per service** - Single purpose
✅ **Avoid service locator** - Except infrastructure in controllers
✅ **Test with mocks** - Unit test handlers independently
✅ **Document registrations** - Clear startup configuration

## Troubleshooting

### Service Not Found

**Error**: "Service of type X not found in service provider"

**Solution**: Ensure service registered in startup:

```python
services.add_scoped(TaskRepository, MongoTaskRepository)
```

### Circular Dependencies

**Error**: "Circular dependency detected"

**Solution**: Introduce interface or factory pattern:

```python
# Instead of A → B → A
# Use A → IB ← B
```

### Wrong Lifetime

**Symptom**: Stale data or connection errors
**Solution**: Choose correct lifetime:

- Singleton for stateless services
- Scoped for request-specific services
- Transient for lightweight objects

## Related Documentation

- [CQRS Pattern](./cqrs-pattern.md) - Command/query handlers
- [Data Layer](./data-layer.md) - Repository pattern and domain entities
- [Architecture Overview](./overview.md) - Core concepts and patterns
