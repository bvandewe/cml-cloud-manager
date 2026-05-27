# Lablet Cloud Manager - AI Agent Instructions

## Quick Start for AI Agents

**Critical First Steps:**

1. Always set `PYTHONPATH=src` or use Makefile commands
2. Run `make build-ui` before `make run` (UI assets required)
3. Commands/queries are self-contained (request + handler in same file)
4. Use Neuroglia DI patterns - never instantiate services directly

**Common Operations:**

```bash
make test              # Run tests (use this to validate changes)
make run               # Start locally (needs make build-ui first)
make dev               # Full Docker stack with logs
make lint && make format  # Code quality checks
```

## Architecture Overview

**Stack**: FastAPI + Neuroglia Framework (DDD/CQRS) + Bootstrap 5 SPA + Keycloak OAuth2/OIDC
**Purpose**: Manage AWS EC2-based Cisco Modeling Lab (CML) workers with monitoring, metrics collection, and lab orchestration
**Key Pattern**: Event-sourced aggregates with @dispatch handlers, CQRS via Mediator, dual authentication (cookie + JWT)

### Multi-SubApp Pattern

The application uses Neuroglia's SubApp pattern with **two mounted FastAPI apps**:

- **API SubApp** (`/api/*`): JSON REST endpoints with JWT/cookie auth (see `src/api/`)
- **UI SubApp** (`/*`): Bootstrap 5 SPA with Server-Side Events (see `src/ui/`)

Both apps are configured in `src/main.py::create_app()` via `WebApplicationBuilder` and mounted with route prefixes.

### Layer Architecture (Clean Architecture/DDD)

```
domain/          # Pure entities (CMLWorker, Task, LabRecord) with AggregateRoot pattern
application/     # CQRS: commands/queries/handlers, settings, background services
integration/     # MongoDB repositories (Motor), AWS EC2/CloudWatch client
infrastructure/  # Session stores (Redis/in-memory), technical adapters
api/             # API controllers, dependencies (auth), OpenAPI config
ui/              # UI controllers, Parcel-built frontend (src/*, package.json)
```

**Key Pattern**: Commands/Queries are **self-contained** - each file contains both the request class and its handler (e.g., `create_task_command.py` has `CreateTaskCommand` + `CreateTaskCommandHandler`). No separate `handlers/` directory.

**Finding CQRS handlers**: Don't look for a `handlers/` directory - handlers are co-located with requests in `application/commands/*.py` and `application/queries/*.py`.

**Example self-contained command:**

```python
# application/commands/create_task_command.py
@dataclass
class CreateTaskCommand(Command[OperationResult[TaskCreatedDto]]):
    title: str
    description: str

class CreateTaskCommandHandler(CommandHandler[CreateTaskCommand, OperationResult[TaskCreatedDto]]):
    def __init__(self, task_repository: TaskRepository):
        self._repository = task_repository

    async def handle_async(self, request: CreateTaskCommand, cancellation_token=None) -> OperationResult[TaskCreatedDto]:
        # Validate using helper methods
        if not request.title:
            return self.bad_request("Title is required")

        # Business logic
        task = Task.create(title=request.title, description=request.description)
        await self._repository.add_async(task, cancellation_token)

        # Return success using helper method
        return self.created(TaskCreatedDto(id=task.id(), title=task.state.title))
```

## Critical Domain Concepts

### CMLWorker Aggregate (`domain/entities/cml_worker.py`)

Represents an AWS EC2 instance running CML. Uses Neuroglia's `AggregateRoot` pattern with event-driven state transitions:

- **Instance type**: `m5zn.metal` (nested virtualization support) - **expensive** and slow to provision
- **Idle management**: Instances should be stopped after idle_timeout to reduce costs (detection mechanism TBD)
- **Licensing**: Valid CML license required for labs with >5 nodes
- **Event sourcing**: State changes via domain events (e.g., `CMLWorkerCreatedDomainEvent`, `CMLWorkerStatusUpdatedDomainEvent`)
- **State reconstruction**: `@dispatch` decorators handle events to update `CMLWorkerState`
- **Lifecycle**: created → provisioning → running → stopping → stopped → terminated

### Lab Management & Resource Hierarchy

**Critical relationships**:

- **Worker-to-Lab**: One worker hosts **multiple labs** (user-created or imported)
- **Lab lifecycle**: Independent state machine - users can create/modify/start/wipe/stop/delete labs
- **Resource consumption**: Labs consume worker resources (CPU/memory/storage) - monitor via **CML native telemetry API** (preferred over CloudWatch)
- **Node definitions**: Workers include standard + custom node definitions, each with image definitions (features/state)
- **Separation of concerns**: Worker and lab lifecycles must be managed separately

**Orchestration principle**: Transparent - no worker-side changes required for management operations

### Worker Monitoring System

Background monitoring coordinated by `WorkerMonitoringScheduler` (see `notes/WORKER_MONITORING_ARCHITECTURE.md`):

1. **Auto-discovery**: Scans for active workers on startup via `get_active_workers_async()`
2. **Job scheduling**: Uses `BackgroundTaskScheduler` (APScheduler wrapper) to schedule `WorkerMetricsCollectionJob` per worker
3. **Reactive notifications**: `WorkerNotificationHandler` observes metrics events and processes them
4. **Separation of concerns**: Metrics collection (compute layer) vs. workload monitoring (CML labs)
5. **Telemetry sources**: CML native API (preferred) for lab-level metrics; CloudWatch for EC2-level metrics
6. **Regular polling**: Resource utilization must be monitored continuously (CPU/memory/storage at both worker and lab levels)

**Startup lifecycle** (`src/main.py::lifespan_with_monitoring`):

- Creates service scope to access repositories
- Instantiates monitoring scheduler with dependencies
- Auto-starts monitoring for active workers
- Schedules global labs refresh job (30-minute interval)

**Background Jobs** (see `application/jobs/*.py`):

- `WorkerMetricsCollectionJob`: Per-worker metrics polling (EC2 + CML + CloudWatch)
- `LabsRefreshJob`: Global lab data refresh every 30 minutes

Use `@backgroundjob` decorator with task_type="recurrent" for recurring tasks:

```python
@backgroundjob(task_type="recurrent", interval=300)
class MyBackgroundJob(BackgroundJobBase):
    async def execute_async(self, context):
        # Job logic here
```

## Authentication Architecture

**Dual Authentication** (`api/services/auth.py::DualAuthService`):

- **Cookie-based** (Primary): Backend-for-Frontend (BFF) pattern with httpOnly cookies, Keycloak OIDC flow
- **Bearer Token** (API): JWT tokens for programmatic access (Swagger UI, API clients)

**Security Model** (see `notes/AUTHENTICATION_ARCHITECTURE.md`):

- Tokens **never exposed to browser JavaScript** (httpOnly cookies prevent XSS)
- CSRF protection via SameSite cookies
- Session storage: Redis (production) or in-memory (dev) via `infrastructure/session_store.py`
- **RBAC enforcement**: Both UI and API must enforce role-based access control at application layer

**Auth Flow**:

1. Browser → `/api/auth/login` → redirect to Keycloak
2. Keycloak callback → exchange code for tokens → store server-side
3. Set httpOnly cookie with session ID
4. API requests → validate session → retrieve tokens → call protected endpoints

**Dependency Injection** (`api/dependencies.py`):

```python
async def get_current_user(
    session_id: Optional[str] = Cookie(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_optional)
) -> dict:
```

Checks cookie first, then bearer token. Auth service retrieved from `request.state.auth_service` (injected by middleware).

## Development Workflows

### Essential Commands (Makefile)

```bash
make install          # Install Python deps with Poetry
make install-ui       # Install Node.js deps for UI
make build-ui         # Build Parcel frontend → static/
make run              # Run app locally (requires build-ui first)
make dev              # Docker Compose: build + start services with logs
make up               # Docker Compose: start services in background
make urls             # Show all service URLs

make test             # Run pytest suite
make test-cov         # Run tests with coverage report
make lint             # Run Ruff linting
make format           # Format with Black
make install-hooks    # Install pre-commit hooks
```

**Local Development** (without Docker):

1. `make install && make install-ui` - Install dependencies
2. `make build-ui` - Build frontend assets (required before running)
3. `make run` - Starts Uvicorn with reload at `http://localhost:8000`
4. Set `PYTHONPATH=src` when running Python commands directly

**Docker Development**:

- `make dev` - Full stack with live logs (app, MongoDB, Redis, Keycloak, OTEL Collector)
- App runs with debugpy on port 5678 (VS Code attach config available)
- Environment variables in `.env` override defaults in `docker-compose.yml`

### Testing Patterns (`pytest.ini`)

**Markers**: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.asyncio`, `@pytest.mark.command`, `@pytest.mark.query`

**Test discovery**: `tests/` directory, `PYTHONPATH=src` configured in pytest.ini

**Coverage**: Run `make test-cov` to generate HTML report in `htmlcov/`

## Neuroglia Framework Specifics

### CRITICAL: Mediator & RequestHandler API Patterns

**This is a recurring source of errors - READ CAREFULLY:**

#### Mediator.execute_async() Signature

**ALWAYS** call with **ONLY ONE ARGUMENT** (the request):

```python
# ✅ CORRECT - One argument only
result = await self.mediator.execute_async(GetWorkerQuery(worker_id="123"))
result = await self.mediator.execute_async(CreateTaskCommand(title="Task"))

# ❌ WRONG - DO NOT pass cancellation_token to mediator
result = await self.mediator.execute_async(query, cancellation_token)  # TypeError!
```

**Why this matters**: `Mediator.execute_async(request)` takes only 1 parameter. The `cancellation_token` is passed to **repository methods**, not mediator calls.

#### RequestHandler Helper Methods (Commands, Queries, Events)

All handlers inherit from `RequestHandler` which provides **HTTP status code helper methods**. These are available in `CommandHandler`, `QueryHandler`, and `EventHandler`:

**Available Methods** (return `OperationResult[T]`):

- `self.ok(data)` - 200 OK with data
- `self.created(data)` - 201 Created
- `self.accepted(data)` - 202 Accepted
- `self.no_content()` - 204 No Content
- `self.bad_request(message)` - 400 Bad Request
- `self.unauthorized(message)` - 401 Unauthorized
- `self.forbidden(message)` - 403 Forbidden
- `self.not_found(title, detail)` - 404 Not Found
- `self.conflict(message)` - 409 Conflict
- `self.unprocessable_entity(message)` - 422 Unprocessable Entity
- `self.internal_server_error(message)` - 500 Internal Server Error
- `self.service_unavailable(message)` - 503 Service Unavailable

**Pattern - Command/Query Handlers:**

```python
from neuroglia.mediation import Command, CommandHandler

@dataclass
class CreateTaskCommand(Command[OperationResult[dict]]):
    title: str
    description: str

class CreateTaskCommandHandler(CommandHandler[CreateTaskCommand, OperationResult[dict]]):
    def __init__(self, task_repository: TaskRepository):
        self._repository = task_repository

    async def handle_async(self, request: CreateTaskCommand, cancellation_token=None) -> OperationResult[dict]:
        # ✅ Use helper methods, NOT OperationResult.success/fail

        # Validate input
        if not request.title:
            return self.bad_request("Title is required")

        # Check existence
        existing = await self._repository.get_by_title_async(request.title)
        if existing:
            return self.conflict("Task with this title already exists")

        # Create entity
        task = Task.create(title=request.title, description=request.description)

        # Save (repository methods DO accept cancellation_token)
        await self._repository.add_async(task, cancellation_token)

        # Return success
        return self.ok({"id": task.id(), "title": task.state.title})
```

**Pattern - Checking Results:**

```python
# When calling commands/queries via mediator, check results:
result = await self.mediator.execute_async(GetWorkerQuery(worker_id="123"))

# ✅ CORRECT - Use .is_success (no "ful")
if result.is_success:
    data = result.data  # Access data via .data
    print(f"Success: {data}")
else:
    error = result.error_message  # Access error via .error_message
    print(f"Failed: {error}")

# ❌ WRONG - These don't exist
if result.is_successful:  # AttributeError!
    content = result.content  # AttributeError!
    errors = result.errors  # AttributeError!
```

**OperationResult API Reference:**

- `.is_success: bool` - Check if operation succeeded
- `.data: T` - Access result data (on success)
- `.error_message: str` - Access error message (on failure)
- `.status_code: int` - HTTP status code
- `.detail: str` - Additional error details
- `.type: str` - Error type
- `.instance: str` - Error instance identifier

#### Common Mistakes to Avoid

1. **❌ DO NOT import or use `OperationResult` for construction:**

   ```python
   from neuroglia.core import OperationResult  # This is ProblemDetails, not a result wrapper!
   return OperationResult.success(data)  # AttributeError: no 'success' method
   return OperationResult.fail(message)  # AttributeError: no 'fail' method
   ```

2. **❌ DO NOT pass cancellation_token to mediator:**

   ```python
   result = await self.mediator.execute_async(command, cancellation_token)  # TypeError!
   ```

3. **❌ DO NOT use wrong attribute names:**

   ```python
   if result.is_successful:  # Should be is_success
   data = result.content  # Should be data
   errors = result.errors  # Should be error_message
   ```

4. **✅ DO use helper methods consistently:**

   ```python
   return self.ok({"key": "value"})
   return self.not_found("Resource", "Resource not found")
   return self.bad_request("Invalid input")
   ```

#### Repository vs Mediator Parameter Patterns

**Repository methods** accept `cancellation_token`:

```python
worker = await self._repository.get_by_id_async(worker_id, cancellation_token)
await self._repository.update_async(worker, cancellation_token)
await self._repository.add_async(worker, cancellation_token)
```

**Mediator calls** do NOT accept `cancellation_token`:

```python
result = await self.mediator.execute_async(GetWorkerQuery(worker_id="123"))
result = await self.mediator.execute_async(UpdateWorkerCommand(worker_id="123", name="Updated"))
```

### Dependency Injection

Services registered in `src/main.py::create_app()`:

```python
builder.services.add_singleton(TaskRepository, MongoTaskRepository)
builder.services.add_scoped(CMLWorkerRepository, MongoCMLWorkerRepository)
builder.services.configure(DualAuthService.configure)  # Factory method pattern
```

**Scoped services**: Repositories, Mediator (per-request lifecycle)
**Singletons**: Settings, AWS client, notification handlers, schedulers

**Accessing services in code**:

```python
# In controllers/handlers - inject via __init__
def __init__(self, service_provider, mapper, mediator, repository: TaskRepository):
    self._repository = repository

# In background jobs - get from service provider
scope = self._service_provider.create_scope()
repository = scope.get_required_service(CMLWorkerRepository)
```

### Controller Routing (`notes/NEUROGLIA_CONTROLLER_PREFIX_FINDINGS.md`)

Neuroglia auto-generates route prefixes from class names:

- `TasksController` → `/tasks/*`
- `UIController` → `/ui/*` (not root!)

**Override to serve at root**:

```python
class UIController(ControllerBase):
    def __init__(self, service_provider, mapper, mediator):
        super().__init__(service_provider, mapper, mediator)
        self.prefix = ""  # Override auto-generated prefix
```

### CQRS with Mediator

**Commands** (write operations): `application/commands/*.py`

```python
from neuroglia.mediation import Command, CommandHandler

@dataclass
class CreateTaskCommand(Command[OperationResult[TaskCreatedDto]]):
    title: str
    description: str

class CreateTaskCommandHandler(CommandHandler[CreateTaskCommand, OperationResult[TaskCreatedDto]]):
    async def handle_async(self, request: CreateTaskCommand, cancellation_token=None) -> OperationResult[TaskCreatedDto]:
        # Validate
        if not request.title:
            return self.bad_request("Title is required")

        # Business logic
        task = Task.create(title=request.title, description=request.description)
        await self._repository.add_async(task, cancellation_token)

        # Return using helper method
        return self.created(TaskCreatedDto(id=task.id(), title=task.state.title))
```

**Queries** (read operations): `application/queries/*.py` - same pattern

**Usage in controllers**:

```python
# ✅ CORRECT - Single argument only
result = await self.mediator.execute_async(CreateTaskCommand(title="...", description="..."))
return self.process(result)  # Controllers use process() to convert to HTTP response
```

### Event Sourcing with @dispatch

Domain events handled via `multipledispatch`:

```python
@dispatch(CMLWorkerCreatedDomainEvent)
def on(self, event: CMLWorkerCreatedDomainEvent) -> None:
    self.id = event.worker_id
    self.name = event.name
    self.status = CMLWorkerStatus.PENDING
```

Events automatically published via CloudEvent middleware when aggregate saved.

## AWS Integration

**Client**: `integration/services/aws_ec2_api_client.py::AwsEc2Client`

- EC2 instance management (create, start, stop, terminate)
- CloudWatch metrics (CPU, memory, network, disk)
- Tag-based instance discovery
- Singleton service with boto3 client pooling

**CML API Client**: `integration/services/cml_api_client.py::CMLApiClient`

- CML REST API integration for worker instances
- System information (`/api/v0/system_information`) - no auth required
- System stats (`/api/v0/system_stats`) - requires auth
- Lab management endpoints (list, create, start, stop, wipe, delete)
- Node definitions and image definitions queries

**Required AWS Environment Variables** (see `notes/AWS_IAM_PERMISSIONS_REQUIRED.md`):

```bash
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
CML_WORKER_AMI_NAME_DEFAULT        # AMI name filter
CML_WORKER_INSTANCE_TYPE_DEFAULT   # e.g., m5.xlarge
CML_WORKER_SECURITY_GROUP_ID
CML_WORKER_SUBNET_ID
```

## Configuration & Settings

**Main config**: `src/application/settings.py::Settings` (extends `ApplicationSettings`)

- Environment variables override defaults (e.g., `APP_PORT`, `KEYCLOAK_URL`)
- Redis session store: Set `REDIS_ENABLED=true` and `REDIS_URL=redis://host:6379/0`
- Worker monitoring: `WORKER_MONITORING_ENABLED=true`, `WORKER_METRICS_POLL_INTERVAL=300`

**Keycloak setup**: `deployment/keycloak/` contains realm import JSON

- Default realm: `lablet-cloud-manager`
- Default client: `lablet-cloud-manager-public` (public client for Authorization Code Flow)

## UI Development

**Frontend Stack**: Bootstrap 5 + Vanilla JS + Parcel bundler
**Source**: `src/ui/src/` (JS modules, SCSS)
**Build**: `cd ui && npm run build` → outputs to `static/`
**Dev mode**: `cd ui && npm run dev` (hot reload on port 1234)

**Server-Side Events (SSE)**: UI subscribes to `/api/events/stream` for real-time worker status/metrics updates (see `application/services/sse_event_relay.py`)

**Real-time event broadcasting**:

- SSE clients register with `SSEEventRelay` service
- Optional filtering by worker_ids and event_types
- Events published to all matching subscribed clients
- Common event types: worker_status, worker_metrics, lab_status

## Common Pitfalls

1. **Forgot to build UI**: Run `make build-ui` before `make run` or app won't serve static assets
2. **PYTHONPATH issues**: Always run from project root with `PYTHONPATH=src` or use `make` commands
3. **Neuroglia controllers at wrong path**: Override `self.prefix` in `__init__` if not using default naming
4. **Auth middleware missing**: Ensure `DualAuthService.configure()` called in `create_app()` before mounting subapps
5. **Background jobs not running**: Check `WORKER_MONITORING_ENABLED=true` and verify APScheduler logs
6. **Aggregate state not updating**: Ensure `@dispatch` decorators present and events emitted via `record_event()`

## Architecture Evolution & Migration Path

**Current state**: Imperative commands/queries (CQRS pattern)
**Target state**: Hybrid model with Resource-Oriented Architecture (ROA)

**Migration strategy** (implement gradually):

- Preserve existing command/query patterns for immediate operations
- Add declarative resource definitions (desired state specifications)
- Implement autonomous watchers for resource observation
- Build reconciliation loops to align actual state with desired state
- Maintain backward compatibility during transition

**Guiding principles**:

- **Portable**: Cloud-native 12-factor app (local → Docker → Kubernetes deployment)
- **Observable**: OpenTelemetry integration (metrics, traces, logs)
- **Actionable**: CloudEvents for event-driven integration
- **Maintainable**: Clean Architecture with clear layer boundaries

## Documentation

**Required updates for any feature change**:

- `CHANGELOG.md` - User-facing changes under "Unreleased" section
- `README.md` - Update if user workflows change
- `Makefile` - Add/update commands if new workflows introduced
- `docs/` (MkDocs) - Architectural decisions, feature guides, troubleshooting

**Documentation as code**: Architecture and design decisions must be documented continuously in `notes/*.md` and `docs/`

- **Architecture diagrams**: `docs/architecture/` (MkDocs site)
- **Design decisions**: `notes/*.md` (e.g., `AUTHENTICATION_ARCHITECTURE.md`, `WORKER_MONITORING_ARCHITECTURE.md`)
- **API docs**: Auto-generated at `/api/docs` (Swagger UI) when app running
- **Build docs**: `make docs-serve` (MkDocs dev server on port 8000)

## Code Style & Contribution Guidelines

**Formatters**: Black (line length 120 - see `pyproject.toml`), isort (Black profile)
**Linter**: Ruff with rules E, F, W, I, UP
**Pre-commit**: Install with `make install-hooks` - runs Black, isort, Ruff, detect-secrets on commit

- **Enforcement**: Pre-commit hooks required; exceptions must be documented with rationale

### Import Guidelines

**All imports MUST be at module level (top of file)**:

- Place all `import` and `from ... import` statements at the beginning of the file
- Organize imports in standard order: stdlib → third-party → local (enforced by isort)
- **No inline imports** inside functions, methods, or classes except for:
  - Circular dependency resolution (document with comment explaining why)
  - `TYPE_CHECKING` imports for type hints (use `if TYPE_CHECKING:` block)

**Correct pattern:**

```python
# Standard library
import logging
from dataclasses import dataclass

# Third-party
from neuroglia.mediation import Command, CommandHandler

# Local application
from domain.repositories import CMLWorkerRepository
from integration.enums import AwsRegion

class CreateWorkerCommandHandler(CommandHandler):
    def handle_async(self, command):
        region = AwsRegion(command.region)  # ✅ Import at top
```

**Incorrect pattern:**

```python
class CreateWorkerCommandHandler(CommandHandler):
    def handle_async(self, command):
        from integration.enums import AwsRegion  # ❌ Inline import
        region = AwsRegion(command.region)
```

**TYPE_CHECKING exception (acceptable):**

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.entities import CMLWorker  # ✅ Acceptable for type hints only
```

**Benefits of module-level imports**:

- Explicit dependency declaration at file start
- Better readability and maintainability
- Easier to detect circular dependencies
- Faster repeated execution (no repeated import overhead)
- Clearer for static analysis tools

**Commit conventions**:

- **Style**: `<type>: <description>` (feat, fix, docs, refactor, test, chore)
- **Message format**: Max 5 lines, group related changes logically
- **DCO**: All commits must be signed off (`git commit -s`)
- **Atomic commits**: One logical change per commit (easier to review/revert)

**Example commit**:

```
feat: add idle timeout detection for workers

- Add idle_timeout field to CMLWorker entity
- Implement detection via last_activity timestamp
- Schedule periodic idle check background job
- Update settings to configure timeout threshold
```

## graphify

For any question about this repo's architecture, structure, components, or how to add/modify/find
code, your first action should be `graphify query "<question>"` when `graphify-out/graph.json`
exists. Use `graphify path "<A>" "<B>"` for relationship questions and `graphify explain "<concept>"`
for focused-concept questions. These return a scoped subgraph, usually much smaller than the full
report or raw grep output.

Triggers: "how do I…", "where is…", "what does … do", "add/modify a <component>",
"explain the architecture", or anything that depends on how files or classes relate.

If `graphify-out/wiki/index.md` exists, use it for broad navigation. Read `graphify-out/GRAPH_REPORT.md`
only for broad architecture review or when query/path/explain do not surface enough context. Only read
source files when (a) modifying/debugging specific code, (b) the graph lacks the needed detail, or
(c) the graph is missing or stale.

Type `/graphify` in Copilot Chat to build or update the graph.
