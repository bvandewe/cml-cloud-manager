# Implementation Patterns Cheat Sheet

**Purpose**: Quick reference for implementing features in Lablet Cloud Manager
**Audience**: Human developers and AI agents
**Status**: Based on actual implementation (November 2025)

---

## Table of Contents

1. [Application Bootstrap & DI](#application-bootstrap--di)
2. [Domain Layer Patterns](#domain-layer-patterns)
3. [Application Layer Patterns](#application-layer-patterns)
4. [API Layer Patterns](#api-layer-patterns)
5. [Integration Layer Patterns](#integration-layer-patterns)
6. [Background Jobs](#background-jobs)
7. [Real-Time Updates (SSE)](#real-time-updates-sse)
8. [Authentication](#authentication)
9. [Common Pitfalls](#common-pitfalls)

---

## Application Bootstrap & DI

### Main Application Setup (`src/main.py`)

**Pattern**: Neuroglia `WebApplicationBuilder` with SubApp mounting

```python
def create_app() -> FastAPI:
    builder = WebApplicationBuilder(app_settings=app_settings)

    # 1. Configure core Neuroglia services
    Mediator.configure(builder, [
        "application.commands",
        "application.queries",
        "application.events.domain",
        "application.events.integration",
    ])

    Mapper.configure(builder, [
        "application.commands",
        "application.queries",
        "application.mapping",
        "integration.models",
    ])

    JsonSerializer.configure(builder, [
        "domain.entities",
        "domain.models",
        "integration.models",
    ])

    CloudEventPublisher.configure(builder)
    CloudEventIngestor.configure(builder, ["application.events.integration"])
    Observability.configure(builder)

    # 2. Configure repositories (one per aggregate)
    MotorRepository.configure(
        builder,
        entity_type=CMLWorker,
        key_type=str,
        database_name="lablet_cloud_manager",
        collection_name="cml_workers",
        domain_repository_type=CMLWorkerRepository,
        implementation_type=MongoCMLWorkerRepository,
    )

    # 3. Configure integration services
    AwsEc2Client.configure(builder)
    CMLApiClientFactory.configure(builder)

    # 4. Configure background scheduler
    BackgroundTaskScheduler.configure(
        builder,
        modules=["application.jobs"],  # Auto-scan for @backgroundjob
    )

    # 5. Configure hosted services
    SSEEventRelayHostedService.configure(builder)

    # 6. Configure authentication
    DualAuthService.configure(builder)

    # 7. Add SubApps
    builder.add_sub_app(SubAppConfig(
        path="/api",
        name="api",
        title=f"{app_settings.app_name} API",
        controllers=["api.controllers"],  # Controllers must be exported in __init__.py
        docs_url="/docs",
    ))

    builder.add_sub_app(SubAppConfig(
        path="/",
        name="ui",
        title=app_settings.app_name,
        controllers=["ui.controllers"],  # Controllers must be exported in __init__.py
        static_files={"/static": str(static_dir)},
        docs_url=None,
    ))

    # 8. Build app with lifespan
    app = builder.build_app_with_lifespan(
        title="Cml Cloud Manager",
        description="...",
        version="1.0.0",
        debug=True,
    )

    # 9. Add middlewares
    DualAuthService.configure_middleware(app)
    app.add_middleware(CloudEventMiddleware, service_provider=app.state.services)

    return app
```

**Key Points**:

- Use `builder.add_sub_app()` for mounting separate API/UI apps
- **CRITICAL**: Controllers must be exported in `__init__.py` for auto-discovery (common mistake)
- Configure repositories via `MotorRepository.configure()` for auto event publishing
- Background jobs auto-discovered via `@backgroundjob` decorator
- Middlewares added AFTER building app

---

## Domain Layer Patterns

### 1. Aggregate Root with Event Sourcing

**File**: `src/domain/entities/cml_worker.py`

**Pattern**: `AggregateRoot` + `AggregateState` + `@dispatch` event handlers

```python
from neuroglia.data.abstractions import AggregateRoot, AggregateState
from multipledispatch import dispatch

class CMLWorkerState(AggregateState[str]):
    """State class - all persisted fields and event handlers."""
    id: str
    name: str
    status: CMLWorkerStatus
    # ... all state fields

    def __init__(self) -> None:
        super().__init__()
        # Initialize all fields with defaults
        self.id = ""
        self.name = ""
        self.status = CMLWorkerStatus.PENDING

    # Event handlers for state reconstruction (belong to State, not Root)
    @dispatch(CMLWorkerCreatedDomainEvent)
    def on(self, event: CMLWorkerCreatedDomainEvent) -> None:
        """Apply created event to state."""
        self.id = event.aggregate_id
        self.name = event.name
        self.aws_region = event.aws_region
        self.status = event.status
        self.created_at = event.created_at

    @dispatch(CMLWorkerStatusUpdatedDomainEvent)
    def on(self, event: CMLWorkerStatusUpdatedDomainEvent) -> None:
        """Apply status updated event."""
        self.status = event.new_status
        self.updated_at = event.updated_at

        if event.new_status == CMLWorkerStatus.PENDING:
            self.start_initiated_at = event.transition_initiated_at
        elif event.new_status == CMLWorkerStatus.STOPPING:
            self.stop_initiated_at = event.transition_initiated_at

class CMLWorker(AggregateRoot[CMLWorkerState, str]):
    """Aggregate root with domain behavior methods."""

    def __init__(
        self,
        name: str,
        aws_region: str,
        instance_type: str,
        created_by: str | None = None,
        worker_id: str | None = None,
    ) -> None:
        """Initialize new worker."""
        super().__init__()
        aggregate_id = worker_id or str(uuid4())
        created_time = datetime.now(timezone.utc)

        # Register event and apply to state
        self.state.on(
            self.register_event(
                CMLWorkerCreatedDomainEvent(
                    aggregate_id=aggregate_id,
                    name=name,
                    aws_region=aws_region,
                    instance_type=instance_type,
                    status=CMLWorkerStatus.PENDING,
                    created_at=created_time,
                )
            )
        )

    # Factory method pattern for import
    @staticmethod
    def import_from_existing_instance(
        name: str,
        aws_region: str,
        aws_instance_id: str,
        # ... other params
    ) -> "CMLWorker":
        """Import existing EC2 instance as worker."""
        worker = object.__new__(CMLWorker)
        AggregateRoot.__init__(worker)

        event = CMLWorkerImportedDomainEvent(...)
        worker.state.on(worker.register_event(event))
        return worker

    # Domain behavior method
    def update_status(self, new_status: CMLWorkerStatus) -> bool:
        """Change worker status."""
        if self.state.status == new_status:
            return False

        old_status = self.state.status
        now = datetime.now(timezone.utc)

        # Register event - state.on() applies it
        self.state.on(
            self.register_event(
                CMLWorkerStatusUpdatedDomainEvent(
                    aggregate_id=self.id(),
                    old_status=old_status,
                    new_status=new_status,
                    updated_at=now,
                    transition_initiated_at=now,
                )
            )
        )
        return True
```

**Key Points**:

- **State class**: All persisted fields + `@dispatch` event handlers
- **Aggregate root**: Domain behavior methods that register events
- **Event application**: Call `self.state.on(self.register_event(...))` pattern
- **Event handlers**: `@dispatch` methods in `AggregateState` (NOT in `AggregateRoot`)
- **Never mutate state directly** - always register events and apply via `state.on()`

### 2. Domain Events

**File**: `src/domain/events/cml_worker.py`

```python
from dataclasses import dataclass
from datetime import datetime
from neuroglia.data.abstractions import DomainEvent
from neuroglia.eventing.cloud_events.decorators import cloudevent
from domain.enums import CMLWorkerStatus

# Domain event WITH CloudEvent publishing (opt-in)
@cloudevent("cml_worker.created.v1")
@dataclass
class CMLWorkerCreatedDomainEvent(DomainEvent):
    """Event emitted when worker is created."""
    aggregate_id: str
    name: str
    aws_region: str
    instance_type: str
    status: CMLWorkerStatus
    created_at: datetime

    def __init__(
        self,
        aggregate_id: str,
        name: str,
        aws_region: str,
        instance_type: str,
        status: CMLWorkerStatus,
        created_at: datetime
    ) -> None:
        super().__init__(aggregate_id)
        self.aggregate_id = aggregate_id
        self.name = name
        self.aws_region = aws_region
        self.instance_type = instance_type
        self.status = status
        self.created_at = created_at

# Domain event WITHOUT CloudEvent publishing (internal only)
@dataclass
class CMLWorkerValidatedEvent(DomainEvent):
    """Internal validation event - not published as CloudEvent."""
    aggregate_id: str
    validation_result: bool
```

**Key Points**:

- Use `@dataclass` for events
- Include all relevant data (no references to aggregates)
- Inherit from `DomainEvent`
- Events are immutable
- **CloudEvent Publishing** (opt-in): Add `@cloudevent("event.type.v1")` decorator to publish events as CloudEvents to external systems
  - Use semantic versioning in event type (e.g., "cml_worker.created.v1")
  - Only add decorator for events that should be published externally
  - Events without decorator remain internal to the application
- Must call `super().__init__(aggregate_id)` in event constructors

### 3. Repository Interface

**File**: `src/domain/repositories/cml_worker_repository.py`

```python
from abc import ABC, abstractmethod
from domain.entities.cml_worker import CMLWorker

class CMLWorkerRepository(ABC):
    """Abstract repository for CML Worker aggregate."""

    @abstractmethod
    async def get_by_id_async(self, worker_id: str) -> CMLWorker | None:
        """Retrieve worker by ID."""
        pass

    @abstractmethod
    async def get_active_workers_async(self) -> list[CMLWorker]:
        """Retrieve all non-terminated workers."""
        pass

    @abstractmethod
    async def add_async(self, worker: CMLWorker) -> None:
        """Add new worker."""
        pass

    @abstractmethod
    async def update_async(self, worker: CMLWorker) -> None:
        """Update existing worker."""
        pass
```

**Key Points**:

- Define interface in `domain/repositories/`
- Implementation in `integration/repositories/`
- Methods end with `_async` suffix
- No implementation details in domain layer

---

## Application Layer Patterns

### 1. Commands (Write Operations)

**File**: `src/application/commands/create_cml_worker_command.py`

**Pattern**: Self-contained command + handler in same file

```python
from dataclasses import dataclass
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler

@dataclass
class CreateCMLWorkerCommand(Command[OperationResult[dict]]):
    """Command to create new CML Worker."""
    name: str
    aws_region: str
    instance_type: str
    ami_id: str | None = None

class CreateCMLWorkerCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateCMLWorkerCommand, OperationResult[dict]]
):
    """Handler for create worker command."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        cml_worker_repository: CMLWorkerRepository,
        aws_ec2_client: AwsEc2Client,
        settings: Settings,
    ):
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)
        self.cml_worker_repository = cml_worker_repository
        self.aws_ec2_client = aws_ec2_client
        self.settings = settings

    async def handle_async(
        self, request: CreateCMLWorkerCommand
    ) -> OperationResult[dict]:
        """Handle command execution."""

        # 1. Validate input
        if not request.name:
            return self.bad_request("Name is required")

        # 2. Business logic
        worker = CMLWorker.create(
            name=request.name,
            aws_region=request.aws_region,
            instance_type=request.instance_type
        )

        # 3. Persist aggregate
        await self.cml_worker_repository.add_async(worker)

        # 4. Return success using helper method
        return self.created({"id": worker.id(), "name": worker.state.name})
```

**Helper Methods** (from `CommandHandlerBase`, which inherits them from neuroglia.mediator's `RequestHandler`):

- `self.ok(data)` - 200 OK
- `self.created(data)` - 201 Created
- `self.accepted(data)` - 202 Accepted
- `self.no_content()` - 204 No Content
- `self.bad_request(message)` - 400 Bad Request
- `self.unauthorized(message)` - 401 Unauthorized
- `self.forbidden(message)` - 403 Forbidden
- `self.not_found(title, detail)` - 404 Not Found
- `self.conflict(message)` - 409 Conflict
- `self.internal_server_error(message)` - 500 Internal Server Error

**Key Points**:

- Command and handler in **same file**
- Command is a `@dataclass` inheriting from `Command[OperationResult[T]]`
- Handler inherits from `CommandHandlerBase` + `CommandHandler`
- Use helper methods for responses (NOT `OperationResult.success()`)
- Mediator calls take **single argument only** (the request)

### 2. Queries (Read Operations)

**File**: `src/application/queries/get_cml_workers_query.py`

**Pattern**: Self-contained query + handler in same file

```python
from dataclasses import dataclass
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

@dataclass
class GetCMLWorkersQuery(Query[OperationResult[list[dict]]]):
    """Query to retrieve workers."""
    aws_region: AwsRegion
    status: CMLWorkerStatus | None = None

class GetCMLWorkersQueryHandler(
    QueryHandler[GetCMLWorkersQuery, OperationResult[list[dict]]]
):
    """Handler for get workers query."""

    def __init__(self, worker_repository: CMLWorkerRepository):
        super().__init__()
        self.worker_repository = worker_repository

    async def handle_async(
        self, request: GetCMLWorkersQuery
    ) -> OperationResult[list[dict]]:
        """Execute query."""
        try:
            # Get workers from repository
            if request.status:
                workers = await self.worker_repository.get_by_status_async(request.status)
            else:
                workers = await self.worker_repository.get_active_workers_async()

            # Filter by region
            filtered = [w for w in workers if w.state.aws_region == request.aws_region.value]

            # Convert to DTOs
            result = [
                {
                    "id": w.state.id,
                    "name": w.state.name,
                    "status": w.state.status.value,
                    # ... other fields
                }
                for w in filtered
            ]

            # Return success using helper method
            return self.ok(result)

        except Exception as e:
            logger.error(f"Error retrieving workers: {e}", exc_info=True)
            return self.internal_server_error(str(e))
```

**Helper Methods** (inherited from neuroglia.mediation's `RequestHandler`):

QueryHandler inherits the same helper methods as CommandHandler:

- `self.ok(data)` - 200 OK
- `self.bad_request(message)` - 400 Bad Request
- `self.not_found(title, detail)` - 404 Not Found
- `self.internal_server_error(message)` - 500 Internal Server Error
- All other helper methods available

**Key Points**:

- Similar to commands but for read operations
- **Must use helper methods** (e.g., `self.ok()`, `self.not_found()`) - DO NOT use `OperationResult.success()` or `OperationResult.fail()`
- QueryHandler inherits helper methods from `RequestHandler` (same as CommandHandler)
- Focus on data transformation/filtering
- Use try-except blocks to handle errors gracefully

### 3. Domain Event Handlers

**File**: `src/application/events/domain/cml_worker_events.py`

**Pattern**: Translate domain events to SSE broadcasts

```python
from neuroglia.mediation import DomainEventHandler

class CMLWorkerCreatedDomainEventHandler(
    DomainEventHandler[CMLWorkerCreatedDomainEvent]
):
    """Handle worker created event."""

    def __init__(self, sse_relay: SSEEventRelay, repository: CMLWorkerRepository):
        self._sse_relay = sse_relay
        self._repository = repository

    async def handle_async(self, notification: CMLWorkerCreatedDomainEvent) -> None:
        """Broadcast SSE event to UI."""

        # Broadcast specific event
        await self._sse_relay.broadcast_event(
            event_type="worker.created",
            data={
                "worker_id": notification.aggregate_id,
                "name": notification.name,
                "status": notification.status.value,
                "created_at": notification.created_at.isoformat() + "Z",
            },
            source="domain.cml_worker",
        )

        # Optionally broadcast full snapshot
        await _broadcast_worker_snapshot(
            self._repository,
            self._sse_relay,
            notification.aggregate_id,
            reason="created"
        )

        return None
```

**Key Points**:

- One handler per domain event type
- Handlers registered automatically by Neuroglia
- Use SSEEventRelay to broadcast to UI
- Domain events → SSE events (UI notifications)
- **Commands should NOT broadcast SSE directly** - let domain events handle it

### 4. Mediator Usage

**Calling commands/queries**:

```python
# ✅ CORRECT - Single argument only
result = await self.mediator.execute_async(
    CreateCMLWorkerCommand(name="test", aws_region="us-east-1", instance_type="m5.xlarge")
)

# Check results
if result.is_success:  # NOT is_successful
    data = result.data  # NOT content
    print(f"Success: {data}")
else:
    error = result.error_message  # NOT errors
    print(f"Failed: {error}")
```

**Repository method calls**:

```python
# Repository methods do NOT accept cancellation_token
worker = await repository.get_by_id_async(worker_id)
await repository.update_async(worker)
await repository.add_async(new_worker)

# Mediator calls also single argument
result = await mediator.execute_async(GetWorkerQuery(worker_id="123"))
```

---

## API Layer Patterns

### 1. Controllers

**File**: `src/api/controllers/workers_controller.py`

**Pattern**: Neuroglia `ControllerBase` with method decorators

```python
from classy_fastapi.decorators import get, post, delete
from neuroglia.mvc.controller_base import ControllerBase
from fastapi import Depends

class WorkersController(ControllerBase):
    """API controller for worker operations."""

    def __init__(self, service_provider, mapper, mediator):
        ControllerBase.__init__(self, service_provider, mapper, mediator)

    @get(
        "/region/{aws_region}/workers",
        response_model=list[dict],
        status_code=200,
        responses=ControllerBase.error_responses,
    )
    async def list_cml_workers(
        self,
        aws_region: AwsRegion,
        status: CMLWorkerStatus | None = None,
        token: str = Depends(get_current_user),
    ) -> Any:
        """List workers in region."""
        query = GetCMLWorkersQuery(aws_region=aws_region, status=status)
        return self.process(await self.mediator.execute_async(query))

    @post(
        "/region/{aws_region}/workers",
        response_model=dict,
        status_code=201,
        responses=ControllerBase.error_responses,
    )
    async def create_new_cml_worker(
        self,
        aws_region: AwsRegion,
        request: CreateCMLWorkerRequest,
        token: str = Depends(require_roles("admin")),
    ) -> Any:
        """Create new worker (admin only)."""
        command = CreateCMLWorkerCommand(
            name=request.name,
            aws_region=aws_region,
            instance_type=request.instance_type
        )
        return self.process(await self.mediator.execute_async(command))
```

**Key Points**:

- Inherit from `ControllerBase`
- Use `@get`, `@post`, `@delete` decorators (NOT `@app.get`)
- Use `self.process()` to convert `OperationResult` to HTTP response
- Auth via `Depends(get_current_user)` or `Depends(require_roles("admin"))`
- **CRITICAL**: Controllers auto-discovered when registered in `SubAppConfig` BUT must be exported in `__init__.py`

**Controller Registration Requirement**:

Controllers are NOT automatically discovered by filename. You MUST export them in `__init__.py`:

```python
# src/api/controllers/__init__.py
from .workers_controller import WorkersController
from .tasks_controller import TasksController

__all__ = [
    "WorkersController",
    "TasksController",
]
```

Without this export, controllers will be silently ignored (frequent mistake).

### 2. Dependency Injection in Controllers vs Handlers

**CRITICAL DIFFERENCE**: Controllers and application handlers use different DI patterns.

#### Controllers: Standard Constructor + Service Provider Pattern

Controllers inherit from `ControllerBase` which provides a **fixed constructor signature**:

```python
class WorkersController(ControllerBase):
    def __init__(
        self,
        service_provider: ServiceProviderBase,  # REQUIRED - for runtime DI
        mapper: Mapper,                          # REQUIRED - for mapping
        mediator: Mediator                       # REQUIRED - for CQRS
    ):
        """Controllers CANNOT add custom dependencies to constructor."""
        ControllerBase.__init__(self, service_provider, mapper, mediator)
        # ❌ WRONG - Cannot add custom parameters like:
        # def __init__(self, ..., aws_client: AwsEc2Client):  # Will fail!
```

**Why this limitation?**

- Neuroglia's controller discovery auto-wires these three services
- Framework cannot resolve custom dependencies in constructor
- Solution: Use `self.service_provider.get_required_service()` at runtime

**Accessing dependencies via service_provider**:

```python
class DiagnosticsController(ControllerBase):
    def __init__(
        self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator
    ):
        super().__init__(service_provider, mapper, mediator)
        # DON'T resolve services here - do it in methods

    @get("/intervals")
    async def get_intervals(self, user: dict = Depends(get_current_user)):
        """Get services at runtime when needed."""

        # ✅ CORRECT - Resolve from service_provider in method
        scheduler = self.service_provider.get_required_service(BackgroundTaskScheduler)
        health_service = self.service_provider.get_required_service(SystemHealthService)

        # Use services
        jobs = scheduler.list_tasks()
        status = await health_service.check_health()

        return {"jobs": jobs, "status": status}
```

**Best Practices for Controllers**:

- ✅ Always use standard 3-parameter constructor
- ✅ Resolve dependencies in methods via `self.service_provider.get_required_service()`
- ✅ Resolve only when needed (lazy loading)
- ✅ Use mediator for business logic (delegate to commands/queries)
- ❌ Don't add custom constructor parameters
- ❌ Don't resolve services in constructor (premature)
- ❌ Don't implement business logic in controllers (use commands/queries)

#### Application Handlers: Full Constructor Injection

Command/Query handlers support **full constructor dependency injection**:

```python
class CreateCMLWorkerCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateCMLWorkerCommand, OperationResult[dict]]
):
    """Handlers CAN declare all dependencies in constructor."""

    def __init__(
        self,
        # Standard mediator services
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        # ✅ Custom dependencies - ALL resolved at construction time
        cml_worker_repository: CMLWorkerRepository,
        aws_ec2_client: AwsEc2Client,
        cml_api_client_factory: CMLApiClientFactory,
        background_task_scheduler: BackgroundTaskScheduler,
        settings: Settings,
    ):
        """All dependencies auto-injected by Neuroglia Mediator."""
        super().__init__(mediator, mapper, cloud_event_bus, cloud_event_publishing_options)

        # Store injected services as instance variables
        self.cml_worker_repository = cml_worker_repository
        self.aws_ec2_client = aws_ec2_client
        self.cml_client_factory = cml_api_client_factory
        self.scheduler = background_task_scheduler
        self.settings = settings

    async def handle_async(self, request: CreateCMLWorkerCommand) -> OperationResult[dict]:
        """Use pre-injected dependencies directly."""

        # ✅ Use instance variables - already injected
        worker = CMLWorker.create(...)
        await self.cml_worker_repository.add_async(worker)

        instance_id = self.aws_ec2_client.create_instance(
            region=request.aws_region,
            ...
        )

        return self.created({"id": worker.id(), "instance_id": instance_id})
```

**Why handlers have full DI?**

- Handlers registered with Neuroglia's Mediator system
- Mediator inspects constructor signatures and resolves ALL dependencies
- Services injected once at handler instantiation
- More efficient - no repeated service lookups

**Best Practices for Handlers**:

- ✅ Declare ALL dependencies in constructor
- ✅ Store as instance variables for use in `handle_async()`
- ✅ Let Neuroglia's DI container resolve dependencies automatically
- ✅ Use type hints for automatic resolution
- ❌ Don't use `service_provider.get_required_service()` (not needed)
- ❌ Don't manually instantiate services (breaks DI pattern)

#### Comparison Table

| Aspect | Controllers | Application Handlers |
|--------|------------|---------------------|
| **Constructor Signature** | Fixed 3 parameters (service_provider, mapper, mediator) | Flexible - declare all needed dependencies |
| **Custom Dependencies** | ❌ Cannot add to constructor | ✅ Add any registered service |
| **Dependency Resolution** | Runtime via `service_provider.get_required_service()` | Construction time via DI container |
| **When Services Created** | Lazy (on first use in method) | Eager (at handler instantiation) |
| **Service Caching** | Manual (store in instance var if needed) | Automatic (instance variables) |
| **DI System** | FastAPI/Neuroglia controller discovery | Neuroglia Mediator DI |
| **Typical Pattern** | Thin orchestration layer (call mediator) | Business logic implementation |

#### Why Two Different Patterns?

**Controllers** (service_provider pattern):

- FastAPI integration requires specific constructor signature
- Controllers are lightweight HTTP adapters (should be thin)
- Business logic delegated to commands/queries via mediator
- Runtime service resolution keeps controllers flexible

**Handlers** (full constructor injection):

- Pure application layer components (no HTTP concerns)
- Need many domain/integration services for business logic
- Full DI makes dependencies explicit and testable
- Construction-time injection is more efficient for repeated use

#### Common Mistake: Trying to Add Dependencies to Controllers

```python
# ❌ WRONG - This will FAIL at runtime
class WorkersController(ControllerBase):
    def __init__(
        self,
        service_provider: ServiceProviderBase,
        mapper: Mapper,
        mediator: Mediator,
        aws_client: AwsEc2Client,  # ❌ Framework can't resolve this!
    ):
        super().__init__(service_provider, mapper, mediator)
        self.aws_client = aws_client

# ✅ CORRECT - Use service_provider in methods
class WorkersController(ControllerBase):
    def __init__(
        self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator
    ):
        super().__init__(service_provider, mapper, mediator)

    @get("/health")
    async def check_aws_health(self):
        # Resolve at runtime
        aws_client = self.service_provider.get_required_service(AwsEc2Client)
        return {"healthy": aws_client.health()}
```

### 3. Authentication Dependencies

**File**: `src/api/dependencies.py`

```python
from fastapi import Cookie, Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security_optional = HTTPBearer(auto_error=False)

async def get_current_user(
    request: Request,
    session_id: str | None = Cookie(None),
    credentials: HTTPAuthorizationCredentials | None = Security(security_optional),
) -> dict:
    """Get user from cookie OR bearer token."""
    auth_service = request.state.auth_service  # Injected by middleware
    return await auth_service.get_current_user(session_id, credentials)

def require_roles(*required_roles: str):
    """Dependency factory for role-based access."""
    async def check_roles(user: dict = Depends(get_current_user)) -> dict:
        user_roles = user.get("roles", [])
        if not any(role in user_roles for role in required_roles):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return check_roles
```

**Usage in controllers**:

```python
# Any authenticated user
async def get_data(token: str = Depends(get_current_user)):
    pass

# Admin only
async def create_data(token: str = Depends(require_roles("admin"))):
    pass
```

### 3. Request/Response Models

**File**: `src/api/models/cml_worker_requests.py`

```python
from pydantic import BaseModel, Field

class CreateCMLWorkerRequest(BaseModel):
    """Request model for creating worker."""
    name: str = Field(..., min_length=1, max_length=100)
    instance_type: str = Field(..., pattern=r"^[a-z0-9.]+$")
    ami_id: str | None = None
    ami_name: str | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "name": "cml-worker-01",
                "instance_type": "m5.xlarge",
                "ami_name": "cml-2.9.0"
            }
        }
```

---

## Integration Layer Patterns

### 1. Repository Implementation

**File**: `src/integration/repositories/motor_cml_worker_repository.py`

**Pattern**: Extend Neuroglia `MotorRepository`

```python
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.data.infrastructure.tracing_mixin import TracedRepositoryMixin

class MongoCMLWorkerRepository(
    TracedRepositoryMixin,
    MotorRepository[CMLWorker, str],
    CMLWorkerRepository
):
    """MongoDB repository with auto event publishing."""

    def __init__(
        self,
        client: AsyncIOMotorClient,
        database_name: str,
        collection_name: str,
        serializer: JsonSerializer,
        entity_type: type[CMLWorker] | None = None,
        mediator: Mediator | None = None,
    ):
        super().__init__(
            client=client,
            database_name=database_name,
            collection_name=collection_name,
            serializer=serializer,
            entity_type=entity_type,
            mediator=mediator,
        )

    async def get_by_aws_instance_id_async(self, instance_id: str) -> CMLWorker | None:
        """Custom query method."""
        document = await self.collection.find_one({"aws_instance_id": instance_id})
        if document:
            return self._deserialize_entity(document)
        return None

    async def get_active_workers_async(self) -> list[CMLWorker]:
        """Get all non-terminated workers."""
        cursor = self.collection.find({
            "status": {"$ne": CMLWorkerStatus.TERMINATED.value}
        })
        workers = []
        async for document in cursor:
            workers.append(self._deserialize_entity(document))
        return workers
```

**Key Points**:

- Inherit from `TracedRepositoryMixin` (first) for auto-tracing
- Inherit from `MotorRepository[Entity, KeyType]`
- Inherit from domain repository interface
- `mediator` parameter enables auto domain event publishing
- Add custom query methods as needed
- Use `self._deserialize_entity()` for document → entity conversion

### 2. External API Client

**File**: `src/integration/services/aws_ec2_api_client.py`

**Pattern**: Singleton service with `.configure()` method

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neuroglia.hosting.web import WebApplicationBuilder

@dataclass
class AwsAccountCredentials:
    aws_access_key_id: str
    aws_secret_access_key: str

class AwsEc2Client:
    """AWS EC2 API client."""

    def __init__(self, aws_account_credentials: AwsAccountCredentials):
        self.aws_account_credentials = aws_account_credentials
        self._ec2_clients = {}  # Cached boto3 clients per region

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Register client as singleton in DI container."""
        from application.settings import Settings

        def factory(sp):
            settings = sp.get_required_service(Settings)
            credentials = AwsAccountCredentials(
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
            return AwsEc2Client(credentials)

        builder.services.try_add_singleton(AwsEc2Client, factory=factory)

    def _get_ec2_client(self, region: AwsRegion):
        """Get or create boto3 client for region."""
        if region not in self._ec2_clients:
            self._ec2_clients[region] = boto3.client(
                "ec2",
                region_name=region.value,
                aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
                aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
            )
        return self._ec2_clients[region]

    def create_instance(self, region: AwsRegion, **kwargs) -> str:
        """Create EC2 instance and return instance ID."""
        client = self._get_ec2_client(region)
        try:
            response = client.run_instances(**kwargs)
            return response["Instances"][0]["InstanceId"]
        except ClientError as e:
            raise self._parse_aws_error(e, "create_instance")

    def _parse_aws_error(self, error: ClientError, operation: str) -> Exception:
        """Convert boto3 errors to domain exceptions."""
        error_code = error.response.get("Error", {}).get("Code", "Unknown")

        if error_code == "UnauthorizedOperation":
            return EC2AuthenticationException(f"AWS auth failed: {operation}")
        elif error_code == "InstanceLimitExceeded":
            return EC2QuotaExceededException(f"Instance quota exceeded")
        else:
            return EC2InstanceOperationException(f"Operation failed: {operation}")
```

**Key Points**:

- Use `@staticmethod` `configure()` method for DI registration
- Factory pattern for service instantiation
- Cache expensive resources (boto3 clients)
- Convert external exceptions to domain exceptions
- Use `TYPE_CHECKING` for avoiding circular imports

### 3. API Client Patterns: Singleton vs Factory

The application uses **two different patterns** for external API clients, each suited to specific use cases:

#### Pattern 1: Singleton Client (AWS EC2 Client)

**File**: `src/integration/services/aws_ec2_api_client.py`

**When to use**: Static configuration known at application startup, shared across all operations

```python
class AwsEc2Client:
    """Singleton client with credentials configured at startup."""

    def __init__(self, aws_account_credentials: AwsAccountCredentials):
        self.aws_account_credentials = aws_account_credentials
        self._ec2_clients = {}  # Thread-safe: dict for per-region client caching

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Register as singleton - ONE instance for entire application."""
        credentials = AwsAccountCredentials(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        ec2_client = AwsEc2Client(aws_account_credentials=credentials)
        builder.services.add_singleton(AwsEc2Client, singleton=ec2_client)

# Usage in handlers - inject singleton directly
class CreateWorkerCommandHandler:
    def __init__(self, aws_ec2_client: AwsEc2Client):
        self.aws_ec2_client = aws_ec2_client  # Same instance everywhere

    async def handle_async(self, request):
        # Use singleton client - credentials same for all AWS operations
        instance_id = self.aws_ec2_client.create_instance(region, ...)
```

**Characteristics**:

- ✅ **Thread-safe**: Single instance shared across async operations (safe with asyncio)
- ✅ **Credentials known at startup**: AWS keys configured via environment variables
- ✅ **No per-operation variation**: All operations use same AWS account
- ✅ **Efficient**: Reuses boto3 client connections (cached per region)
- ✅ **Simple DI**: Inject singleton directly into handlers

#### Pattern 2: Factory Pattern (CML API Client)

**File**: `src/integration/services/cml_api_client.py`

**When to use**: Runtime parameters vary per operation (different endpoints, credentials)

```python
class CMLApiClient:
    """Client instance with runtime-specific configuration."""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url  # DIFFERENT for each worker
        self.username = username
        self.password = password
        self._token: str | None = None  # Per-instance auth state

class CMLApiClientFactory:
    """Factory creates new client instances with runtime parameters."""

    def __init__(self, default_username: str, default_password: str):
        self.default_username = default_username
        self.default_password = default_password

    def create(self, base_url: str, username: str | None = None) -> CMLApiClient:
        """Create NEW client instance for specific worker endpoint."""
        return CMLApiClient(
            base_url=base_url,  # Runtime parameter - different per worker
            username=username or self.default_username,
            password=self.default_password,
        )

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Register factory as singleton, NOT the client instances."""
        factory = CMLApiClientFactory(
            default_username=settings.cml_worker_api_username,
            default_password=settings.cml_worker_api_password,
        )
        builder.services.add_singleton(CMLApiClientFactory, singleton=factory)

# Usage in handlers - inject factory, create instances at runtime
class DeleteLabCommandHandler:
    def __init__(self, cml_api_client_factory: CMLApiClientFactory):
        self._cml_client_factory = cml_api_client_factory  # Factory injected

    async def handle_async(self, request):
        worker = await repository.get_by_id_async(request.worker_id)

        # Create NEW client instance for THIS worker's endpoint
        cml_client = self._cml_client_factory.create(
            base_url=worker.state.https_endpoint  # Runtime parameter!
        )

        # Use worker-specific client
        await cml_client.delete_lab(request.lab_id)
```

**Characteristics**:

- ✅ **Thread-safe**: Each async operation gets its own client instance
- ✅ **Runtime parameters**: Base URL varies per worker (not known at startup)
- ✅ **Isolated state**: Each client has own authentication token, no shared state
- ✅ **Flexibility**: Can override username/password per worker if needed
- ✅ **Factory pattern**: DI injects factory, handlers create instances on-demand

#### Comparison Table

| Aspect | Singleton (AwsEc2Client) | Factory (CMLApiClient) |
|--------|--------------------------|------------------------|
| **DI Registration** | `add_singleton(AwsEc2Client, singleton=instance)` | `add_singleton(CMLApiClientFactory, singleton=factory)` |
| **Handler Injection** | Inject client directly | Inject factory |
| **Instance Creation** | Once at startup | Per operation at runtime |
| **Configuration** | Static (env vars) | Dynamic (worker endpoints) |
| **State Management** | Shared (cached boto3 clients) | Isolated (per-worker tokens) |
| **Thread Safety** | Yes (dict caching safe in asyncio) | Yes (no shared state) |
| **Use Case** | Single API with static config | Multiple endpoints with runtime config |
| **Example** | One AWS account for all operations | Different CML worker per operation |

#### Decision Criteria

**Use Singleton Pattern when**:

- ✅ Configuration is **static** (known at application startup)
- ✅ All operations use the **same endpoint/credentials**
- ✅ Client is **expensive to create** (connection pooling benefits)
- ✅ Client is **thread-safe** for concurrent use

**Use Factory Pattern when**:

- ✅ Configuration is **dynamic** (varies per operation)
- ✅ Operations target **different endpoints** (multiple workers)
- ✅ Each operation needs **isolated state** (auth tokens)
- ✅ Flexibility for **per-operation overrides** needed

### 4. Custom Exceptions

**File**: `src/integration/exceptions.py`

```python
class IntegrationException(Exception):
    """Base exception for integration layer."""
    pass

class EC2AuthenticationException(IntegrationException):
    """AWS authentication failed."""
    pass

class EC2InstanceNotFoundException(IntegrationException):
    """EC2 instance not found."""
    pass

class EC2QuotaExceededException(IntegrationException):
    """AWS quota limit reached."""
    pass
```

---

## Background Jobs

### Pattern: `@backgroundjob` Decorator

**File**: `src/application/jobs/worker_metrics_collection_job.py`

```python
from application.services.background_scheduler import (
    RecurrentBackgroundJob,
    backgroundjob
)

@backgroundjob(
    task_type="recurrent",
    interval=app_settings.worker_metrics_poll_interval  # seconds
)
class WorkerMetricsCollectionJob(RecurrentBackgroundJob):
    """Recurrent job for collecting metrics."""

    def __init__(self, aws_ec2_client: AwsEc2Client | None = None):
        """Constructor - dependencies optional (will be injected)."""
        self.aws_ec2_client = aws_ec2_client
        self._service_provider = None

    def __getstate__(self):
        """Pickle serialization - exclude unpicklable objects."""
        state = self.__dict__.copy()
        state["aws_ec2_client"] = None
        state["_service_provider"] = None
        return state

    def __setstate__(self, state):
        """Pickle deserialization."""
        self.__dict__.update(state)

    def configure(self, service_provider=None, **kwargs):
        """Called by scheduler to inject dependencies."""
        self._service_provider = service_provider

        if not self.aws_ec2_client and service_provider:
            self.aws_ec2_client = service_provider.get_required_service(AwsEc2Client)

    async def run_every(self, *args, **kwargs) -> None:
        """Main job execution - called at interval."""

        # Create service scope for scoped dependencies
        scope = self._service_provider.create_scope()
        try:
            # Get scoped services (repositories, mediator)
            repository = scope.get_required_service(CMLWorkerRepository)
            mediator = scope.get_required_service(Mediator)

            # Execute job logic
            workers = await repository.get_active_workers_async()

            # Process concurrently with semaphore
            semaphore = asyncio.Semaphore(10)

            async def process_worker(worker):
                async with semaphore:
                    result = await mediator.execute_async(
                        RefreshWorkerMetricsCommand(
                            worker_id=worker.id(),
                            initiated_by="background_job"
                        )
                    )
                    return result

            tasks = [process_worker(w) for w in workers]
            await asyncio.gather(*tasks, return_exceptions=True)

        finally:
            scope.dispose()
```

**Key Points**:

- Use `@backgroundjob(task_type="recurrent", interval=N)` decorator
- Inherit from `RecurrentBackgroundJob`
- Implement `__getstate__`/`__setstate__` for APScheduler pickling
- Implement `configure()` for dependency injection
- Main logic in `run_every()` method
- **Use mediator to delegate to commands** - don't duplicate logic
- Use `asyncio.Semaphore` for controlled concurrency
- Always create service scope for scoped dependencies
- Jobs auto-discovered from `modules=["application.jobs"]`

---

## Real-Time Updates (SSE)

### ⚠️ Horizontal Scaling Limitation

**Current Implementation**: In-memory client registry (not distributed)

**Deployment Constraint**:

- ✅ **SAFE**: Single replica (`replicaCount: 1` in Helm values)
- ❌ **BREAKS**: Multiple replicas (`replicaCount > 1`)

**Why**: SSE clients register in process memory (`self._clients` dict). With multiple pods:

- Client connects to Pod A, registers in Pod A's memory
- Domain event published by command on Pod B
- Pod B broadcasts to its local registry (empty) → Client misses event
- SSE stream receives nothing (silent failure)

**Current Scale**: Safe for:

- <100 workers managed
- <50 concurrent SSE clients
- <100 events/minute throughput
- Single instance deployment

**Workarounds** (if scaling before Redis Pub/Sub implemented):

- Use sticky sessions (route same client to same pod via load balancer)
- Configure session affinity based on client IP or cookie
- Accept missed events for clients on wrong pod

**Future Enhancement**: Implement Redis Pub/Sub pattern when scaling requirements emerge:

- Events published once to Redis channel
- All pods subscribe to channel
- Each pod broadcasts to its local clients
- No client affinity required
- Works with any load balancer

**Scaling Triggers** (when to implement distributed SSE):

- Need to scale to >1 replica for performance
- >50 concurrent SSE clients
- >200 workers under management
- Multi-region deployment required

**Related**: Session storage already uses Redis (`RedisSessionStore`) for horizontal scaling. SSE is the remaining stateful component.

**See Also**: `notes/REDIS_SESSION_STORE.md` for Redis infrastructure setup

---

### 1. SSE Event Relay Service

**File**: `src/application/services/sse_event_relay.py`

```python
from neuroglia.hosting.abstractions import HostedService

class SSEEventRelay:
    """Broadcast events to connected SSE clients."""

    def __init__(self):
        self._clients: dict[str, SSEClientSubscription] = {}
        self._lock = asyncio.Lock()

    async def register_client(
        self,
        worker_ids: set[str] | None = None,
        event_types: set[str] | None = None,
    ) -> tuple[str, asyncio.Queue]:
        """Register new SSE client with optional filters."""
        client_id = str(uuid4())
        subscription = SSEClientSubscription(
            client_id=client_id,
            worker_ids=worker_ids,
            event_types=event_types
        )
        async with self._lock:
            self._clients[client_id] = subscription
        return client_id, subscription.event_queue

    async def broadcast_event(
        self,
        event_type: str,
        data: dict,
        source: str = "lablet-cloud-manager"
    ) -> None:
        """Broadcast event to matching clients."""
        event_message = {
            "type": event_type,
            "source": source,
            "time": datetime.now(timezone.utc).isoformat() + "Z",
            "data": data,
        }

        async with self._lock:
            matching = [
                sub for sub in self._clients.values()
                if sub.matches_event(event_type, data)
            ]

        for subscription in matching:
            try:
                await asyncio.wait_for(
                    subscription.event_queue.put(event_message),
                    timeout=0.1
                )
            except asyncio.TimeoutError:
                logger.warning(f"Client {subscription.client_id} queue full")

class SSEEventRelayHostedService(HostedService):
    """Hosted service wrapper for SSE relay."""

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Register as singleton and hosted service."""
        relay = SSEEventRelay()
        builder.services.add_singleton(SSEEventRelay, factory=lambda _: relay)

        # Register as hosted service
        def factory(sp):
            return SSEEventRelayHostedService(relay)
        builder.services.add_hosted_service(SSEEventRelayHostedService, factory=factory)
```

### 2. SSE Endpoint (Controller)

**File**: `src/api/controllers/events_controller.py`

```python
from sse_starlette.sse import EventSourceResponse

class EventsController(ControllerBase):

    @get("/stream")
    async def event_stream(
        self,
        request: Request,
        token: str = Depends(get_current_user),
    ):
        """SSE stream endpoint."""
        sse_relay = self.service_provider.get_required_service(SSEEventRelay)

        client_id, queue = await sse_relay.register_client()

        async def event_generator():
            try:
                # Send connection established
                yield {"event": "connected", "data": '{"status": "connected"}'}

                # Stream events from queue
                while True:
                    event_message = await queue.get()
                    yield {
                        "event": event_message["type"],
                        "data": json.dumps(event_message)
                    }
            except asyncio.CancelledError:
                await sse_relay.unregister_client(client_id)
                raise

        return EventSourceResponse(event_generator())
```

### 3. Frontend SSE Client

**File**: `src/ui/src/scripts/services/sse-client.js`

```javascript
class SSEClient {
    constructor() {
        this.eventSource = null;
        this.handlers = new Map();
        this.reconnectAttempts = 0;
        this.maxReconnectDelay = 30000;
    }

    connect() {
        this.eventSource = new EventSource('/api/events/stream');

        this.eventSource.onopen = () => {
            this.reconnectAttempts = 0;
            this._notifyStatus('connected');
        };

        this.eventSource.onerror = () => {
            this.eventSource.close();
            this._scheduleReconnect();
        };

        // Register event listeners
        this.eventSource.addEventListener('worker.metrics.updated', event => {
            const data = JSON.parse(event.data);
            this.emit('worker.metrics.updated', data.data);
        });
    }

    on(eventType, handler) {
        if (!this.handlers.has(eventType)) {
            this.handlers.set(eventType, []);
        }
        this.handlers.get(eventType).push(handler);
    }

    emit(eventType, data) {
        const handlers = this.handlers.get(eventType) || [];
        handlers.forEach(handler => handler(data));
    }
}

export default new SSEClient();
```

**Key Points**:

- Domain event handlers broadcast to SSE relay
- SSE endpoint returns `EventSourceResponse`
- Frontend auto-reconnects with exponential backoff
- Event filtering on server side (worker_ids, event_types)

---

## Authentication

### Pattern: Dual Authentication (Cookie + JWT)

**File**: `src/api/services/dual_auth_service.py`

```python
class DualAuthService:
    """Supports cookie-based (OAuth2) and JWT bearer authentication."""

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Register auth service in DI container."""
        def factory(sp):
            settings = sp.get_required_service(Settings)
            session_store = sp.get_required_service(SessionStore)
            return DualAuthService(settings, session_store)

        builder.services.add_singleton(DualAuthService, factory=factory)

    @staticmethod
    def configure_middleware(app: FastAPI) -> None:
        """Add middleware to inject auth service in request state."""
        @app.middleware("http")
        async def inject_auth_service(request: Request, call_next):
            auth_service = request.app.state.services.get_required_service(DualAuthService)
            request.state.auth_service = auth_service
            return await call_next(request)

    async def get_current_user(
        self,
        session_id: str | None,
        bearer_token: str | None
    ) -> dict:
        """Authenticate via cookie OR bearer token."""

        # Try session cookie first
        if session_id:
            user_info = await self.session_store.get(session_id)
            if user_info:
                return user_info

        # Try bearer token
        if bearer_token:
            return self._validate_jwt(bearer_token)

        raise HTTPException(status_code=401, detail="Not authenticated")
```

**Key Points**:

- Cookie-based for browser (OAuth2/OIDC flow via Keycloak)
- JWT bearer for API clients (Swagger UI, programmatic access)
- Middleware injects auth service in `request.state`
- Dependencies retrieve auth service from request state
- Session storage: Redis (production) or in-memory (dev)

---

## Common Pitfalls

### ❌ Wrong: Manual SSE Broadcasting in Commands

```python
# ❌ WRONG - Don't do this
class RefreshWorkerCommandHandler:
    async def handle_async(self, request):
        worker.update_telemetry(metrics)
        await repository.update_async(worker)

        # ❌ Manual SSE broadcast (bypasses domain events)
        await self._sse_relay.broadcast_event("worker.metrics.updated", {...})
```

### ✅ Correct: Let Domain Events Handle SSE

```python
# ✅ CORRECT
class RefreshWorkerCommandHandler:
    async def handle_async(self, request):
        worker.update_telemetry(metrics)  # Records domain event
        await repository.update_async(worker)  # Publishes event
        # Domain event handler automatically broadcasts SSE ✓
```

### ❌ Wrong: Passing Extra Arguments to Mediator or Repository

```python
# ❌ WRONG - Mediator takes single argument only
result = await self.mediator.execute_async(command, cancellation_token)  # TypeError!
result = await self.mediator.execute_async(command, context)  # TypeError!

# ❌ WRONG - Repository methods don't accept cancellation_token
worker = await repository.get_by_id_async(worker_id, cancellation_token)  # TypeError!
await repository.update_async(worker, cancellation_token)  # TypeError!
```

### ✅ Correct: Single Arguments Only

```python
# ✅ CORRECT - Mediator: single argument (the request)
result = await self.mediator.execute_async(command)
result = await self.mediator.execute_async(query)

# ✅ CORRECT - Repository: single argument per method signature
worker = await repository.get_by_id_async(worker_id)
await repository.update_async(worker)
await repository.add_async(new_worker)
```

### ❌ Wrong: Using OperationResult.success() in Commands/Queries

```python
# ❌ WRONG - Do not use in CommandHandler or QueryHandler
from neuroglia.core import OperationResult
return OperationResult.success(data)  # AttributeError: no 'success' method
return OperationResult.fail(message)  # AttributeError: no 'fail' method
```

### ✅ Correct: Use Helper Methods (Commands AND Queries)

```python
# ✅ CORRECT - Both CommandHandler and QueryHandler inherit helper methods
return self.ok(data)  # 200
return self.created(data)  # 201
return self.bad_request("Error message")  # 400
return self.not_found("Resource", "Resource not found")  # 404
return self.internal_server_error("Error details")  # 500
```

### ❌ Wrong: Checking Result with Wrong Properties

```python
# ❌ WRONG
if result.is_successful:  # Should be is_success
    content = result.content  # Should be data
    errors = result.errors  # Should be error_message
```

### ✅ Correct: Proper OperationResult API

```python
# ✅ CORRECT
if result.is_success:  # NOT is_successful
    data = result.data  # NOT content
else:
    error = result.error_message  # NOT errors
```

### ❌ Wrong: Inline Imports in Functions

```python
# ❌ WRONG - Inline import
def handle_async(self, command):
    from integration.enums import AwsRegion  # ❌
    region = AwsRegion(command.region)
```

### ✅ Correct: Module-Level Imports

```python
# ✅ CORRECT - All imports at top
from integration.enums import AwsRegion

def handle_async(self, command):
    region = AwsRegion(command.region)  # ✅
```

**Exception**: TYPE_CHECKING imports are acceptable

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.entities import CMLWorker  # ✅ For type hints only
```

---

## Quick Reference: File Locations

```
src/
├── main.py                          # Application bootstrap
├── domain/
│   ├── entities/                    # Aggregates (e.g., CMLWorker)
│   ├── events/                      # Domain events
│   ├── repositories/                # Repository interfaces
│   ├── enums/                       # Domain enums
│   └── models/                      # Domain value objects
├── application/
│   ├── commands/                    # Write operations (command + handler)
│   ├── queries/                     # Read operations (query + handler)
│   ├── events/domain/               # Domain event handlers → SSE
│   ├── events/integration/          # Integration event handlers
│   ├── jobs/                        # Background jobs (@backgroundjob)
│   ├── services/                    # Application services
│   │   ├── background_scheduler.py  # APScheduler wrapper
│   │   └── sse_event_relay.py       # SSE broadcasting
│   └── settings.py                  # Configuration
├── api/
│   ├── controllers/                 # REST API endpoints
│   ├── dependencies.py              # FastAPI dependencies (auth)
│   ├── models/                      # Request/response models
│   └── services/                    # API-specific services
├── integration/
│   ├── repositories/                # Repository implementations (MongoDB)
│   ├── services/                    # External API clients (AWS, CML)
│   ├── models/                      # DTOs for external systems
│   ├── enums/                       # Integration enums
│   └── exceptions.py                # Integration exceptions
├── infrastructure/
│   └── services/                    # Technical services (caching, throttling)
└── ui/
    ├── controllers/                 # UI controllers (SSE, static files)
    └── src/                         # Frontend code (Parcel build)
```

---

## Summary Checklist

### Creating a New Feature

1. **Domain Event** → `domain/events/`
2. **Aggregate Method** → Update `domain/entities/` with event recording
3. **Event Handler** → Add `@dispatch` method in aggregate
4. **Command/Query** → Create in `application/commands/` or `application/queries/`
5. **Command Handler** → Same file, use helper methods for responses
6. **Repository Method** (if needed) → Add to interface + implementation
7. **Domain Event Handler** → Create in `application/events/domain/` for SSE
8. **Controller Endpoint** → Add to `api/controllers/`
9. **Export Controller** → **MUST** add to `api/controllers/__init__.py` (critical step!)
10. **Request Model** → Define in `api/models/`
11. **Tests** → Add unit tests for handler, integration tests for endpoint

### Dependencies

- **Mediator calls**: Single argument only (the request)
- **Repository methods**: Single argument per method signature (no cancellation_token)
- **Helper methods**: `self.ok()`, `self.created()`, `self.bad_request()`, etc.
- **DI registration**: Use `.configure()` static method
- **SSE broadcasting**: Only in domain event handlers, never in commands

---

**Document Version**: 1.0
**Last Updated**: November 20, 2025
**Based On**: Actual implementation code (not notes/ folder)
