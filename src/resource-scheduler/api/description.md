# Resource Scheduler API

## Overview

The **Resource Scheduler** is a critical component of the Lablet Cloud Manager that handles **LabletInstance placement decisions**. It uses bin-packing algorithms to efficiently allocate lablet instances to CML workers, maximizing resource utilization while respecting capacity constraints.

**Key Responsibilities:**

- 📅 Schedule pending LabletInstances onto available CML workers
- ⚖️ Balance resource utilization across worker fleet
- 📈 Signal scale-up when capacity is insufficient
- 🕐 Handle timeslot-based scheduling for future reservations

## Architecture

### Leader Election

The Resource Scheduler uses **etcd-based leader election** to ensure only one instance makes placement decisions:

- **High Availability**: Multiple replicas supported with automatic failover
- **Consistency**: Only the leader schedules, preventing race conditions
- **Observability**: Leader status exposed via `/api/ready` and `/api/admin/leader-status`

### Reconciliation Pattern

```
SPEC (LabletInstance) ←→ OBSERVE (Worker capacity) → ACT (placement)
```

The scheduler continuously reconciles desired state with available capacity:

1. **Observe**: Query Control Plane API for pending LabletInstances
2. **Evaluate**: Run bin-packing algorithm to find optimal placement
3. **Act**: Assign LabletInstance to worker via Control Plane API internal endpoint

## Bin-Packing Algorithm

The scheduler uses a **First Fit Decreasing (FFD)** bin-packing algorithm:

1. Sort pending instances by resource requirements (largest first)
2. For each instance, find the first worker with sufficient capacity
3. If no worker fits, request scale-up via Control Plane API

### Resource Dimensions

- **CPU cores**: Estimated from lab topology
- **Memory (GB)**: Based on node definitions
- **Disk (GB)**: Lab storage requirements
- **License slots**: CML node count limits

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
| `/api/admin/stats` | GET | Scheduler statistics |
| `/api/admin/resign-leadership` | POST | Resign leadership for maintenance |

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RECONCILE_INTERVAL` | 30 | Seconds between reconciliation cycles |
| `TIMESLOT_LEAD_TIME_MINUTES` | 35 | Minutes before timeslot to start scheduling |
| `ETCD_HOST` | localhost | etcd host for leader election |
| `ETCD_PORT` | 2379 | etcd port |
| `LEADER_LEASE_TTL` | 15 | Leader lease TTL in seconds |
| `LEADER_KEY` | /lcm/resource-scheduler/leader | etcd key for leader election |
| `CONTROL_PLANE_API_URL` | - | URL of Control Plane API |
| `CONTROL_PLANE_API_KEY` | - | API key for internal endpoints |

## Communication

### Control Plane API Integration

The scheduler communicates with the Control Plane API using the internal API:

- **Read**: `GET /internal/lablet-instances` - Fetch pending instances
- **Read**: `GET /internal/workers` - Fetch available workers with capacity
- **Write**: `POST /internal/lablet-instances/{id}/schedule` - Assign instance to worker
- **Write**: `POST /internal/workers/scale-up` - Request new worker provisioning

### Authentication

All requests to Control Plane API use `X-API-Key` header authentication.

## Scheduling Logic

### Timeslot Handling

Instances with scheduled timeslots are processed based on lead time:

```python
# Schedule if timeslot starts within TIMESLOT_LEAD_TIME_MINUTES
if instance.timeslot_start - now <= lead_time:
    schedule_instance(instance)
```

### Priority Order

1. Instances with imminent timeslots (sorted by start time)
2. On-demand instances (sorted by creation time)

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
  "current_leader_id": "resource-scheduler-1"
}
```

## Observability

The scheduler provides operational visibility through:

- **Stats endpoint**: `/api/admin/stats` - Reconciliation cycles, placements made
- **Leader status**: `/api/admin/leader-status` - Current leader information
- **Structured logging**: JSON logs with trace context
