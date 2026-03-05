# Worker Controller API

## Overview

The **Worker Controller** manages the lifecycle of **CML Workers** - the AWS EC2 instances that run Cisco Modeling Labs. It handles observation, monitoring, discovery, and state synchronization of compute resources.

**Key Responsibilities:**

- 🔍 Observe and monitor CML worker instances
- 📊 Collect metrics from AWS CloudWatch and CML native API
- 🔄 Sync worker state to Control Plane API
- 🆕 Auto-discover and import EC2 instances running CML
- ⏸️ Detect idle workers and trigger auto-pause
- 📝 Sync lab records from workers to Control Plane

## Domain: Infrastructure Layer (Compute Resources)

The Worker Controller operates at the **infrastructure layer**, managing:

- EC2 instance observation (state, metrics)
- Compute metrics collection (CPU, memory, disk)
- CML system health monitoring
- Worker discovery from AWS
- Idle detection and activity tracking

## Architecture

### Leader Election

Uses **etcd-based leader election** for high availability:

- Only the leader performs observation and reconciliation
- Automatic failover on leader failure
- Status exposed via `/api/ready` endpoint

### Observation Pattern

```
OBSERVE (EC2 + CML state) → COMPARE (expected state) → REPORT (Control Plane API)
```

The controller continuously observes infrastructure:

1. **Observe**: Query EC2 state and CML system stats
2. **Collect**: Gather metrics from CloudWatch and CML API
3. **Detect**: Identify idle workers based on activity
4. **Report**: Update worker status/metrics via Control Plane API

## Cloud Provider SPI

### AWS EC2 Observations

| Operation | Description |
|-----------|-------------|
| `describe_instances` | Get EC2 instance state |
| `get_metrics` | Fetch CloudWatch metrics |
| `discover_instances` | Find CML instances by AMI tag |

### CML System Queries

| Query | Description |
|-------|-------------|
| `system_information` | CML version, build info |
| `system_stats` | CPU, memory, disk usage |
| `list_labs` | Labs running on worker |
| `get_lab_details` | Lab nodes and state |

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
| `/api/admin/trigger-reconcile` | POST | Force immediate observation cycle (leader only) |
| `/api/admin/leader-status` | GET | Current leader election status |
| `/api/admin/stats` | GET | Reconciler statistics |
| `/api/admin/resign-leadership` | POST | Resign leadership for maintenance |

## CMLWorker Lifecycle

```
pending → provisioning → starting → running → stopping → stopped → terminating → terminated
                ↓                       ↓
              error                  paused (idle)
```

### States

| State | Description |
|-------|-------------|
| `pending` | Worker creation requested |
| `provisioning` | EC2 instance launching |
| `starting` | EC2 instance starting, CML initializing |
| `running` | Worker active and ready for labs |
| `stopping` | EC2 instance stopping |
| `stopped` | EC2 instance stopped (cost savings) |
| `paused` | Auto-paused due to idle detection |
| `terminating` | EC2 instance being terminated |
| `terminated` | Worker permanently removed |
| `error` | Operation failed, requires intervention |

## Idle Detection

The controller monitors worker activity and detects idle workers:

### Detection Criteria

- No running labs
- No recent API activity
- No console connections
- Idle duration exceeds threshold

### Idle Threshold

Configurable via `IDLE_THRESHOLD_MINUTES` (default: 30 minutes)

## Worker Discovery

The controller can auto-discover EC2 instances running CML:

### Discovery Process

1. Query EC2 instances by AMI name pattern
2. Filter to running instances with CML tags
3. Import new workers via Control Plane API
4. Skip already-known workers

### Configuration

| Variable | Description |
|----------|-------------|
| `WORKER_DISCOVERY_ENABLED` | Enable/disable discovery |
| `WORKER_DISCOVERY_INTERVAL` | Seconds between discovery scans |
| `WORKER_DISCOVERY_AMI_NAME` | AMI name pattern (e.g., `CML-*`) |
| `WORKER_DISCOVERY_REGIONS` | Comma-separated regions to scan |

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `RECONCILE_INTERVAL` | 30 | Seconds between observation cycles |
| `METRICS_POLL_INTERVAL` | 60 | Seconds between metrics collection |
| `LABS_SYNC_INTERVAL` | 300 | Seconds between lab record sync |
| `IDLE_CHECK_INTERVAL` | 60 | Seconds between idle checks |
| `IDLE_THRESHOLD_MINUTES` | 30 | Minutes of inactivity before idle |
| `AWS_REGION` | us-east-1 | AWS region for operations |
| `AWS_ACCESS_KEY_ID` | - | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | - | AWS credentials |
| `CML_WORKER_API_USERNAME` | admin | CML API username |
| `CML_WORKER_API_PASSWORD` | - | CML API password |
| `ETCD_HOST` | localhost | etcd host for leader election |
| `ETCD_PORT` | 2379 | etcd port |
| `LEADER_LEASE_TTL` | 15 | Leader lease TTL in seconds |
| `LEADER_KEY` | /lcm/worker-controller/leader | etcd key for leader election |
| `CONTROL_PLANE_API_URL` | - | URL of Control Plane API |
| `CONTROL_PLANE_API_KEY` | - | API key for internal endpoints |

## Communication

### Control Plane API Integration

The controller communicates with the Control Plane API using the internal API:

- **Read**: `GET /internal/workers` - Fetch workers to observe
- **Write**: `PUT /internal/workers/{id}/status` - Update worker status
- **Write**: `PUT /internal/workers/{id}/metrics` - Update worker metrics
- **Write**: `POST /internal/workers/{id}/activity` - Record worker activity
- **Write**: `POST /internal/workers/{id}/detect-idle` - Trigger idle detection
- **Write**: `POST /internal/workers/bulk-import` - Import discovered workers
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
- AWS credentials are valid
- Service is initialized

Includes leader status in response:

```json
{
  "status": "ready",
  "is_leader": true,
  "current_leader_id": "worker-controller-1"
}
```

## Observability

The controller provides operational visibility through:

- **Stats endpoint**: `/api/admin/stats` - Observation cycles, metrics collected
- **Leader status**: `/api/admin/leader-status` - Current leader information
- **Structured logging**: JSON logs with trace context
