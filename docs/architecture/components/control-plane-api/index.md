# Control Plane API Architecture

**Version:** 1.2.0 (February 2026)
**Status:** Current Implementation

!!! note "Related Documentation"
    For development workflows and Makefile commands, see the [Development Guide](../../../development/ai-agent-guide.md).

---

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.2.0 | 2026-02 | Added CloudEvent ingestion endpoint, CollectAndGrade command, etcd state publishing (ADR-018) |
| 1.1.0 | 2026-02 | Added dual auth architecture, SSE event relay |
| 1.0.0 | 2026-01 | Initial architecture documentation |

---

## 1. Overview

The **Control Plane API** is the central gateway for the Lablet Cloud Manager system. It serves as the Backend-for-Frontend (BFF) providing:

- **REST API** for LabletDefinition, LabletInstance, and Worker CRUD operations
- **Bootstrap 5 SPA** with Server-Side Events (SSE) for real-time updates
- **OAuth2/OIDC Authentication** via Keycloak
- **CQRS Pattern** with Commands (writes) and Queries (reads) via Mediator
- **CloudEvents Publishing** for external system integration (fire-and-forget)
- **etcd State Publishing** for controller watches

!!! important "CQRS Location & Persistence Pattern"
    **Control Plane API is the ONLY service that implements CQRS commands/queries.**
    Controllers (resource-scheduler, worker-controller, lablet-controller) use Reconciliation Loops, not CQRS.

    **Event-Driven State-Based Persistence:**
    The system uses a hybrid persistence pattern where:

    - **State-Based Storage**: Aggregates are persisted as current state in MongoDB (not event-sourced)
    - **Domain Events**: AggregateRoot emits domain events on state changes for in-process side effects
    - **CloudEvents**: Domain events are automatically published to external event bus (fire-and-forget)
    - **etcd Publishing**: State changes are published to etcd for controller watching

!!! warning "ADR-015: No External API Calls"
    Control Plane API MUST NOT make external API calls (AWS, CML).
    It only interacts with MongoDB, etcd, and Redis (sessions).
    All external operations are delegated to controllers via state/intent in the database.

## 2. Entity Hierarchy

```mermaid
erDiagram
    CMLWorker ||--o{ LabRecord : hosts
    CMLWorker ||--o{ NodeDefinition : contains
    CMLWorker ||--o{ ImageDefinition : contains
    LabletDefinition ||--o{ LabletInstance : instantiates
    LabletInstance }o--|| CMLWorker : "assigned_to"
    LabletInstance ||--o| LabRecord : "maps_to"

    CMLWorker {
        string id PK
        string name
        string region
        string instance_type
        string instance_id
        WorkerStatus status
        string ip_address
        int idle_timeout
        datetime created_at
    }

    LabRecord {
        string id PK
        string lab_id
        string title
        string owner
        LabState state
        int node_count
        datetime created
    }

    LabletDefinition {
        string id PK
        string name
        string description
        string topology_yaml
        string[] required_nodes
        int estimated_duration
        boolean is_public
    }

    LabletInstance {
        string id PK
        string definition_id FK
        string worker_id FK
        string user_id
        InstanceState state
        datetime scheduled_start
        datetime scheduled_end
        dict port_mappings
    }

    NodeDefinition {
        string id PK
        string node_definition_id
        string label
        string description
        boolean is_custom
    }

    ImageDefinition {
        string id PK
        string image_id
        string node_definition_id FK
        string label
    }
```

## 3. Storage Strategy

| Entity | Storage | Access Pattern |
|--------|---------|----------------|
| **CMLWorker** | MongoDB | State-based aggregate with optimistic concurrency |
| **LabRecord** | MongoDB | Denormalized snapshot from CML API |
| **LabletDefinition** | MongoDB | Immutable versioned entity (see note below) |
| **LabletInstance** | MongoDB | State-based aggregate with status machine |
| **NodeDefinition** | MongoDB | Cached from CML Worker discovery |
| **ImageDefinition** | MongoDB | Cached from CML Worker discovery |
| **Sessions** | Redis | User session tokens (httpOnly cookies) |
| **State Keys** | etcd | Worker/instance state for controller watches |

!!! warning "LabletDefinition Versioning (Decision Pending)"
    LabletDefinition MUST be versioned so that LabletInstance always refers to a specific version.
    When a command "changes" a definition's state, it MUST create a **new entity** in the database
    (maintaining old versions while enabling automatic cleanup over time).

    **Design Decision Required:**

    - Version numbering scheme (semantic versioning vs auto-increment)
    - Retention policy for old versions
    - Migration strategy for existing data

    This will be documented in a separate ADR.

## 4. Layer Architecture

```
control-plane-api/
├── api/                          # HTTP Layer
│   ├── controllers/              # REST endpoints (auto-prefixed)
│   │   ├── workers_controller.py
│   │   ├── lablet_definitions_controller.py
│   │   ├── lablet_instances_controller.py
│   │   └── auth_controller.py
│   ├── dependencies.py           # DI for auth, sessions
│   └── services/
│       └── auth.py               # DualAuthService (Cookie + JWT)
│
├── application/                  # Business Logic Layer
│   ├── commands/                 # Write operations (self-contained)
│   │   ├── create_worker_command.py
│   │   ├── start_worker_command.py
│   │   └── create_lablet_instance_command.py
│   ├── queries/                  # Read operations (self-contained)
│   │   ├── get_workers_query.py
│   │   └── get_lablet_instances_query.py
│   ├── dtos/                     # Data Transfer Objects
│   ├── services/                 # Application services
│   │   ├── worker_monitoring_scheduler.py
│   │   └── sse_event_relay.py
│   ├── jobs/                     # Background tasks
│   │   ├── worker_metrics_collection_job.py
│   │   └── labs_refresh_job.py
│   └── settings.py               # Configuration (Pydantic Settings)
│
├── domain/                       # Core Domain Layer
│   ├── entities/                 # Aggregates
│   │   ├── cml_worker.py
│   │   ├── lab_record.py
│   │   ├── lablet_definition.py
│   │   └── lablet_instance.py
│   ├── events/                   # Domain events (@cloudevent)
│   ├── enums/                    # Value objects
│   │   ├── worker_status.py
│   │   └── instance_state.py
│   └── repositories/             # Abstract interfaces
│
├── integration/                  # External Service Adapters
│   ├── repositories/             # MongoDB implementations
│   │   ├── mongo_worker_repository.py
│   │   └── mongo_lablet_instance_repository.py
│   └── services/
│       ├── aws_ec2_api_client.py
│       ├── cml_api_client.py
│       └── control_plane_api_client.py
│
├── infrastructure/               # Technical Adapters
│   └── session_store.py          # Redis/InMemory session storage
│
├── ui/                           # Frontend Assets
│   ├── src/                      # Parcel source (JS, SCSS)
│   └── package.json
│
└── observability/                # Instrumentation
    └── otel_config.py
```

## 5. Authentication Architecture

The Control Plane API implements **Dual Authentication** supporting both browser-based and API-based access:

```mermaid
sequenceDiagram
    participant Browser
    participant API as Control Plane API
    participant Redis
    participant Keycloak

    Note over Browser,Keycloak: Cookie-Based Flow (Browser)

    Browser->>API: GET /api/auth/login
    API->>Keycloak: Redirect to OIDC authorize
    Keycloak-->>Browser: Login form
    Browser->>Keycloak: Credentials
    Keycloak->>API: Callback with code
    API->>Keycloak: Exchange code for tokens
    API->>Redis: Store tokens (session_id → tokens)
    API-->>Browser: Set-Cookie: session_id (httpOnly)

    Note over Browser,API: Subsequent requests
    Browser->>API: GET /api/workers (Cookie: session_id)
    API->>Redis: Lookup tokens by session_id
    API->>API: Validate JWT
    API-->>Browser: 200 OK

    Note over Browser,Keycloak: Bearer Token Flow (API Clients)

    Browser->>Keycloak: POST /token (client_credentials)
    Keycloak-->>Browser: access_token
    Browser->>API: GET /api/workers (Authorization: Bearer token)
    API->>Keycloak: Validate JWT (JWKS)
    API-->>Browser: 200 OK
```

### Security Model

| Aspect | Implementation |
|--------|---------------|
| **Session Storage** | Redis (production) or in-memory (dev) |
| **Token Exposure** | Never exposed to browser JS (httpOnly cookies) |
| **CSRF Protection** | SameSite cookie attribute |
| **Token Refresh** | Server-side refresh before expiry |
| **RBAC** | Keycloak realm roles mapped to permissions |

## 6. Background Services

The Control Plane API runs several background services:

### Worker Monitoring Scheduler

Coordinates per-worker metrics collection:

```python
class WorkerMonitoringScheduler:
    """
    Lifecycle:
    1. On startup: Query active workers
    2. For each worker: Schedule WorkerMetricsCollectionJob
    3. On worker state change: Add/remove jobs dynamically
    """

    async def start_async(self):
        workers = await self._get_active_workers()
        for worker in workers:
            self._scheduler.add_job(
                WorkerMetricsCollectionJob(worker.id),
                trigger='interval',
                seconds=self._settings.metrics_poll_interval
            )
```

### SSE Event Relay

Broadcasts real-time updates to connected clients:

```python
class SSEEventRelay:
    """
    - Clients subscribe with optional filters (worker_ids, event_types)
    - Events broadcast to all matching subscribers
    - Common events: worker_status, worker_metrics, lab_status
    """
```

## 7. API Design

### Controller Routing

Neuroglia auto-generates route prefixes from controller class names:

| Controller Class | Route Prefix |
|-----------------|--------------|
| `WorkersController` | `/workers/*` |
| `LabletDefinitionsController` | `/lablet-definitions/*` |
| `LabletInstancesController` | `/lablet-instances/*` |
| `AuthController` | `/auth/*` |

!!! warning "Prefix Convention"
    Do NOT add prefix in `@route` decorators - the controller name IS the prefix.

    ```python
    # ✅ Correct
    @route(HttpMethod.GET, "/{worker_id}")  # → GET /workers/{worker_id}

    # ❌ Wrong (double prefix)
    @route(HttpMethod.GET, "/workers/{worker_id}")  # → GET /workers/workers/{worker_id}
    ```

### CQRS Pattern

All operations use the Mediator pattern:

```python
# In controller
result = await self.mediator.execute_async(
    GetWorkersQuery(status_filter=WorkerStatus.RUNNING)
)
return self.process(result)

# In handler
class GetWorkersQueryHandler(QueryHandler[GetWorkersQuery, OperationResult[list[WorkerDto]]]):
    async def handle_async(self, request, cancellation_token=None):
        workers = await self._repository.get_all_async(cancellation_token)
        return self.ok([WorkerDto.from_entity(w) for w in workers])
```

## 8. External Integrations

### AWS EC2 Client

```python
class AwsEc2Client:
    """
    Singleton service with boto3 client pooling.

    Operations:
    - describe_instances() - Query instance state
    - start_instances() - Start stopped instances
    - stop_instances() - Stop running instances
    - terminate_instances() - Terminate instances
    - get_cloudwatch_metrics() - CPU, memory, network, disk
    """
```

### CML API Client

```python
class CMLApiClient:
    """
    Per-worker client for CML REST API.

    Endpoints:
    - /api/v0/system_information - No auth, worker info
    - /api/v0/system_stats - Auth required, resource usage
    - /api/v0/labs - Lab lifecycle operations
    - /api/v0/node_definitions - Available node types
    """
```

### CloudEvent Ingestion (LDS Integration)

The Control Plane API receives CloudEvents from external systems via the `/api/events/pub` endpoint.

```mermaid
sequenceDiagram
    participant LDS as Lab Delivery System
    participant CPA as Control Plane API
    participant Handler as EventHandler
    participant MongoDB
    participant etcd

    LDS->>CPA: POST /api/events/pub<br/>CloudEvent (application/cloudevents+json)

    alt Event: com.cisco.lds.session.started
        CPA->>Handler: HandleLdsSessionStarted
        Handler->>MongoDB: Update instance state = RUNNING
        Handler->>etcd: PUT /lcm/instances/{id}/state = RUNNING
    else Event: com.cisco.lds.session.ended
        CPA->>Handler: HandleLdsSessionEnded
        Handler->>MongoDB: Update instance state = STOPPING
        Handler->>etcd: PUT /lcm/instances/{id}/state = STOPPING
    end

    CPA-->>LDS: 202 Accepted
```

#### Supported CloudEvent Types (FR-2.2.6)

| Event Type | Source | Description | Action |
|------------|--------|-------------|--------|
| `com.cisco.lds.session.started` | Lab Delivery System | Training session has started | Transition READY → RUNNING |
| `com.cisco.lds.session.ended` | Lab Delivery System | Training session has ended | Trigger lab grading and cleanup |

#### Endpoint Specification

```http
POST /api/events/pub
Content-Type: application/cloudevents+json

{
  "specversion": "1.0",
  "type": "com.cisco.lds.session.started",
  "source": "/lds/sessions",
  "id": "event-uuid",
  "time": "2026-01-15T10:00:00Z",
  "data": {
    "session_id": "session-uuid",
    "lablet_instance_id": "instance-uuid",
    "user_id": "user-uuid"
  }
}
```

!!! note "ADR-018: Lab Delivery System Integration"
    See [ADR-018](../../../architecture/decisions/ADR-018-lab-delivery-system-integration.md) for the full
    integration design including READY state machine and CollectAndGrade workflow.

## 9. CQRS Commands Reference

Key commands implemented in Control Plane API:

| Command | Purpose | Outcome |
|---------|---------|---------|
| `CreateWorkerCommand` | Register new CML worker | Worker in PENDING state |
| `StartWorkerCommand` | Request worker startup | desired_state = RUNNING |
| `StopWorkerCommand` | Request worker stop | desired_state = STOPPED |
| `CreateLabletInstanceCommand` | Create new instance | Instance in PENDING state |
| `ScheduleLabletInstanceCommand` | Assign worker to instance | Instance in SCHEDULED state |
| `InstantiateLabletInstanceCommand` | Import/start lab on worker | Instance in INSTANTIATING/READY |
| `CollectAndGradeCommand` | Trigger grading workflow | Instance in GRADED state |
| `TerminateLabletInstanceCommand` | Cleanup and terminate | Instance in TERMINATED state |

### CollectAndGrade Command (FR-2.2.7)

Triggers the grading workflow for a running lablet instance:

```python
@dataclass
class CollectAndGradeCommand(Command[OperationResult[GradingResultDto]]):
    """Collect lab state and submit for grading."""
    instance_id: str
    grading_criteria: dict | None = None  # Optional custom criteria


class CollectAndGradeCommandHandler(CommandHandler):
    async def handle_async(self, request, cancellation_token=None):
        # 1. Get instance from repository
        instance = await self._repository.get_by_id_async(request.instance_id)

        if not instance:
            return self.not_found("LabletInstance", f"Instance {request.instance_id} not found")

        if instance.state.status != LabletInstanceStatus.RUNNING:
            return self.bad_request("Instance must be RUNNING to collect and grade")

        # 2. Trigger grading (publishes domain event)
        instance.collect_and_grade(request.grading_criteria)

        # 3. Persist
        await self._repository.update_async(instance, cancellation_token)

        return self.accepted(GradingResultDto(instance_id=request.instance_id, status="GRADING"))
```

## 10. Configuration

Key environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `KEYCLOAK_URL` | Keycloak server URL | Required |
| `KEYCLOAK_REALM` | OIDC realm | `lablet-cloud-manager` |
| `CONNECTION_STRINGS` | MongoDB connection | Required |
| `REDIS_URL` | Redis URL (sessions) | Optional |
| `WORKER_MONITORING_ENABLED` | Enable background monitoring | `true` |
| `WORKER_METRICS_POLL_INTERVAL` | Metrics collection interval (sec) | `300` |
| `ETCD_ENDPOINTS` | etcd cluster endpoints | `localhost:2379` |

## 11. Related Documentation

- [Authentication Flows](../../../security/authentication-flows.md)
- [Worker Monitoring](../worker-monitoring.md)
- [Real-Time Updates](../realtime-updates.md)
- [CML Worker Domain Model](../cml-worker-domain-model.md)
- [ADR-018: Lab Delivery System Integration](../../../architecture/decisions/ADR-018-lab-delivery-system-integration.md)
