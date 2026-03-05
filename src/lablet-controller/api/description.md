# Lablet Controller API

## Overview

The **Lablet Controller** manages the lifecycle of **LabletInstances** - the running CML labs that users interact with. It bridges the gap between the desired state (LabletInstance spec) and actual CML lab state on worker instances.

**Key Responsibilities:**

- 🧪 Manage CML lab lifecycle (import, start, stop, wipe, delete)
- 🔄 Reconcile LabletInstance specs with actual lab state
- 🌐 Allocate and manage port mappings for external access
- ⏰ Handle scheduled start/stop based on timeslots
- 📊 Sync lab records to Control Plane API

## Domain: Application Layer (Workloads)

The Lablet Controller operates at the **workload layer**, managing:

- CML Labs (create, start, stop, wipe, delete)
- Lab topology and node configurations
- Port mapping for external access
- Scheduled start/stop based on timeslots
- Lab-level metrics collection

## Architecture

### Leader Election

Uses **etcd-based leader election** for high availability:

- Only the leader performs reconciliation
- Automatic failover on leader failure
- Status exposed via `/api/ready` endpoint

### Reconciliation Pattern

```
SPEC (LabletInstance) ←→ OBSERVE (CML Lab state) → ACT (reconcile)
```

The controller continuously reconciles:

1. **Observe**: Query scheduled LabletInstances from Control Plane API
2. **Compare**: Check actual CML lab state on assigned workers
3. **Act**: Perform necessary operations (import, start, stop, etc.)
4. **Report**: Update instance status via Control Plane API

## CML Labs SPI

The controller communicates with CML workers via the **CML Labs SPI** (Service Provider Interface):

### Lab Operations

| Operation | Description |
|-----------|-------------|
| `import_lab` | Import lab topology from YAML/JSON |
| `start_lab` | Start all nodes in the lab |
| `stop_lab` | Stop all nodes in the lab |
| `wipe_lab` | Reset lab to initial state |
| `delete_lab` | Remove lab from worker |

### State Queries

| Query | Description |
|-------|-------------|
| `get_lab_state` | Current lab state (STARTED, STOPPED, etc.) |
| `get_nodes` | List of nodes with connection info |
| `get_interfaces` | Network interfaces per node |
| `get_links` | Links between nodes |

## API Endpoints

### Operations (`/api`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Liveness probe (always returns healthy) |
| `/api/ready` | GET | Readiness probe (includes leader status) |
| `/api/info` | GET | Service information and stats |

### Admin (`/api/admin`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/trigger-reconcile` | POST | Force immediate reconciliation (leader only) |
| `/api/admin/leader-status` | GET | Current leader election status |
| `/api/admin/stats` | GET | Reconciler statistics |
| `/api/admin/resign-leadership` | POST | Resign leadership for maintenance |

## LabletInstance Lifecycle

```
pending → scheduled → importing → starting → running → stopping → stopped → terminated
                          ↓           ↓           ↓
                       error       error      paused (scheduled)
```

### States

| State | Description |
|-------|-------------|
| `pending` | Waiting for scheduler placement |
| `scheduled` | Assigned to a worker, waiting for import |
| `importing` | Lab topology being imported to CML |
| `starting` | Lab nodes starting up |
| `running` | Lab active and accessible |
| `stopping` | Lab nodes shutting down |
| `stopped` | Lab stopped but preserved on worker |
| `paused` | Scheduled pause (timeslot ended) |
| `terminated` | Lab deleted from worker |
| `error` | Operation failed, requires intervention |

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RECONCILE_INTERVAL` | 30 | Seconds between reconciliation cycles |
| `SCALE_DOWN_GRACE_PERIOD_MINUTES` | 30 | Grace period before scale-down |
| `WORKER_BOOTUP_DELAY_MINUTES` | 20 | Wait time for worker to be ready |
| `LABS_REFRESH_INTERVAL` | 1800 | Interval for lab records refresh (seconds) |
| `CML_WORKER_API_USERNAME` | - | Default CML API username |
| `CML_WORKER_API_PASSWORD` | - | Default CML API password |
| `ETCD_HOST` | localhost | etcd host for leader election |
| `ETCD_PORT` | 2379 | etcd port |
| `LEADER_LEASE_TTL` | 15 | Leader lease TTL in seconds |
| `LEADER_KEY` | /lcm/lablet-controller/leader | etcd key for leader election |
| `CONTROL_PLANE_API_URL` | - | URL of Control Plane API |
| `CONTROL_PLANE_API_KEY` | - | API key for internal endpoints |

## Communication

### Control Plane API Integration

The controller communicates with the Control Plane API using the internal API:

- **Read**: `GET /internal/lablet-instances` - Fetch scheduled instances
- **Read**: `GET /internal/lablet-definitions/{id}` - Fetch definition details
- **Read**: `GET /internal/workers` - Get worker details and connectivity
- **Write**: `POST /internal/lablet-instances/{id}/transition` - Update instance state
- **Write**: `POST /internal/lablet-instances/{id}/allocate-ports` - Allocate ports
- **Write**: `POST /internal/lab-records/sync` - Sync lab records

### Authentication

All requests to Control Plane API use `X-API-Key` header authentication.

## Health & Readiness

### Health Check (`/api/health`)

Always returns `200 OK` if the service is running.

### Readiness Check (`/api/ready`)

Returns `200 OK` only when:

- etcd connection is healthy
- Control Plane API is reachable
- Service is initialized

Includes leader status in response:

```json
{
  "status": "ready",
  "is_leader": true,
  "current_leader_id": "lablet-controller-1"
}
```

## Observability

The controller provides operational visibility through:

- **Stats endpoint**: `/api/admin/stats` - Reconciliation cycles, lab operations
- **Leader status**: `/api/admin/leader-status` - Current leader information
- **Structured logging**: JSON logs with trace context
