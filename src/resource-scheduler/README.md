# Resource Scheduler Service

The Resource Scheduler is a stateless microservice responsible for **placement decisions** — assigning PENDING `LabletSession`s to available CML workers. It uses a leader-elected reconciliation loop to watch for new sessions and a bin-packing placement algorithm to select optimal workers.

## Responsibilities

- Watch for `PENDING` LabletSessions via etcd (reactive) and polling (fallback)
- Execute placement algorithm: **filter → score → select**
- Signal the Worker Controller for scale-up when no existing worker fits
- Periodic cleanup of terminated worker records
- Expose a dry-run placement preview API endpoint

## Architecture

```
api/
    controllers/
        admin_controller.py         # Admin endpoints (trigger-reconcile, leader-status, stats)
        scheduling_controller.py    # POST /scheduling/preview (dry-run)
    dependencies.py                 # FastAPI dependency injection
    services/
        auth.py                     # Keycloak JWT auth
        openapi_config.py           # Swagger/OpenAPI configuration
application/
    hosted_services/
        scheduler_hosted_service.py # Main scheduling reconciliation loop (WatchTriggeredHostedService)
        cleanup_hosted_service.py   # Periodic cleanup of terminated workers (LeaderElectedHostedService)
    services/
        placement_engine.py         # Bin-packing placement algorithm (filter → score → select)
    settings.py                     # Pydantic Settings with all configuration
    commands/                       # (scaffold — reserved for future CQRS commands)
    queries/                        # (scaffold — reserved for future CQRS queries)
    dtos/                           # (scaffold — reserved for future DTOs)
domain/                             # (scaffold — stateless service, no domain entities)
infrastructure/
    observability/                  # OpenTelemetry metrics (7 counters + 2 histograms)
    session_store.py                # Session management
integration/
    services/                      # Control Plane API client (via lcm-core)
    repositories/                  # (scaffold)
main.py                            # WebApplicationBuilder entry point
tests/
    unit/application/services/
        test_placement_engine.py           # Phase 1: Core placement tests
        test_placement_engine_phase2.py    # Phase 2: Multi-session, edge cases
        test_placement_engine_phase3.py    # Phase 3: Scale-up, utilization forecast
        test_scheduler_hosted_service_phase2.py  # Reconciliation loop tests
```

## Key Components

### SchedulerHostedService

Extends `WatchTriggeredHostedService[LabletSessionReadModel]` from `lcm-core`. Dual-mode operation:

- **Watch mode**: Reacts to etcd key changes under `/sessions/` prefix
- **Poll mode**: Periodically fetches all PENDING sessions from Control Plane API (30s default)

Leader-elected via etcd — only the leader instance runs the scheduling loop.

### PlacementEngine

Three-phase bin-packing algorithm:

1. **Filter Phase**: Reject workers that cannot host the session (license, capacity, resources, AMI compatibility, draining status)
2. **Score Phase**: Score remaining candidates (prefer fuller workers for bin-packing)
3. **Select Phase**: Pick highest-scoring worker

### TimeslotManagerHostedService

Leader-elected periodic service (Sprint H, [ADR-037](../../docs/architecture/adr/ADR-037-timeslot-management.md)) that manages timeslot lifecycle for PENDING sessions:

- **Approaching timeslot activation**: Detects PENDING sessions within the `timeslot_lead_time_minutes` window (default: 35 min) and writes etcd trigger keys to wake the SchedulerHostedService watch for immediate placement.
- **Expired timeslot enforcement**: Detects PENDING sessions whose `timeslot_start + grace_period` has passed and expires them via CPA, preventing indefinite PENDING state.

Uses a separate etcd leader election key (`/lcm/timeslot-manager/leader`) from SchedulerHostedService, so both can run as leader simultaneously on the same instance.

#### Timeslot Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TIMESLOT_MANAGER_ENABLED` | Enable/disable the timeslot manager | `true` |
| `TIMESLOT_MANAGER_INTERVAL_SECONDS` | Scan interval in seconds | `60` |
| `TIMESLOT_EXPIRY_GRACE_MINUTES` | Grace period before expiring missed timeslots | `5` |
| `TIMESLOT_LEAD_TIME_MINUTES` | Look-ahead window for approaching sessions | `35` |

### CleanupHostedService

Leader-elected periodic service that removes terminated worker records older than the configured retention period (default: 30 days).

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ETCD_HOST` | etcd server host | `localhost` |
| `ETCD_PORT` | etcd server port | `2379` |
| `CONTROL_PLANE_API_URL` | Control Plane API URL | `http://localhost:8080` |
| `RESOURCE_SCHEDULER_INSTANCE_ID` | Unique instance ID | Auto-generated |
| `LEADER_LEASE_TTL` | Leader lease TTL in seconds | `15` |
| `RECONCILE_INTERVAL` | Reconciliation interval in seconds | `30` |
| `KEYCLOAK_URL` | Keycloak base URL | `http://localhost:8180` |
| `KEYCLOAK_REALM` | Keycloak realm name | `lablet-cloud-manager` |
| `OTEL_EXPORTER_ENDPOINT` | OpenTelemetry collector endpoint | `http://localhost:4317` |
| `CLEANUP_INTERVAL` | Cleanup check interval in seconds | `3600` |
| `CLEANUP_RETENTION_DAYS` | Terminated worker retention (days) | `30` |

## Development

```bash
# Install dependencies
make install

# Run locally (requires etcd and Control Plane API)
make run

# Run tests
make test

# Lint
make lint
```

## API Endpoints

### Admin Endpoints (require admin role)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/admin/trigger-reconcile` | Trigger immediate reconciliation |
| `POST` | `/api/admin/resign-leadership` | Resign leadership (maintenance) |
| `GET` | `/api/admin/leader-status` | Current leader election status |
| `GET` | `/api/admin/stats` | Scheduling statistics |
| `GET` | `/api/admin/timeslots/status` | TimeslotManager statistics |
| `GET` | `/api/admin/timeslots/approaching` | PENDING sessions entering scheduling window |
| `GET` | `/api/admin/timeslots/expired` | Sessions with expired timeslots |
| `GET` | `/api/admin/timeslots/landscape` | 24-hour timeslot distribution histogram |
| `GET` | `/api/admin/scheduling-overview` | Pending sessions, retries, capacity |
| `GET` | `/api/admin/sub-services` | All sub-service health and stats |

### Scheduling Endpoints (authenticated users)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/scheduling/preview` | Dry-run placement preview |

### Standard Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/ready` | Readiness check |

## Related Documentation

- [Resource Scheduler Architecture](../../docs/architecture/components/resource-scheduler/index.md)
- [Background Task Scheduling](../../docs/architecture/background-scheduling.md)
