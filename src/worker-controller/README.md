# Worker Controller Service

The Worker Controller is responsible for **CML Worker reconciliation** - managing the infrastructure lifecycle of CML workers by reconciling desired worker state (spec) against actual cloud infrastructure state.

## Domain: Infrastructure Layer (Cloud Provider SPI)

The Worker Controller operates at the **infrastructure layer**, talking exclusively to the **Cloud Provider SPI**:

- **AWS EC2 API** - Instance lifecycle (describe, start, stop, terminate)
- **AWS CloudWatch API** - Infrastructure metrics (CPU, memory, network, disk)
- **CML System API** - Worker-level system information and license management

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                WORKER CONTROLLER - RECONCILIATION PATTERN                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐   │
│   │       SPEC       │     │     OBSERVE      │     │       ACT        │   │
│   │   (Desired)      │     │    (Actual)      │     │   (Reconcile)    │   │
│   └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘   │
│            │                        │                        │              │
│            ▼                        ▼                        ▼              │
│   ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐   │
│   │ CMLWorker        │     │ EC2 + CML State  │     │ • Launch EC2     │   │
│   │ • status=RUNNING │     │ • EC2 running    │     │ • Register lic.  │   │
│   │ • license=ENT    │ ←→  │ • CML ready      │  →  │ • Update status  │   │
│   │ • region=us-e-1  │     │ • No license     │     │ • Collect metrics│   │
│   └──────────────────┘     └──────────────────┘     └──────────────────┘   │
│                                                                              │
│   Source: MongoDB         Source: AWS + CML API      Target: Both          │
│   (via Control Plane)     (direct observation)       (via Control Plane)   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Responsibilities

- **Worker Reconciliation**: Compare desired worker state with actual EC2/CML state
- **Metrics Collection**: Poll AWS CloudWatch and CML system stats
- **License Management**: Register/deregister CML licenses based on worker spec
- **Auto-Import**: Discover tagged EC2 instances and create worker records
- **Scale-Up Execution**: Launch new EC2 instances when requested
- **Scale-Down Execution**: Stop/terminate EC2 instances when marked for removal

## Domain Separation

| Service | Abstraction Layer | SPI (Service Provider Interface) |
|---------|-------------------|----------------------------------|
| **Worker Controller** | Infrastructure (Compute) | Cloud Provider SPI (EC2, CloudWatch, CML System API) |
| **Lablet Controller** | Application (Workload) | CML Labs SPI (Labs, Nodes, Interfaces, Links API) |

Both controllers follow the same **reconciliation pattern** (SPEC → OBSERVE → ACT), but at different abstraction layers.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     WORKER CONTROLLER                            │
│               (Infrastructure Layer - Compute)                   │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                  LEADER ELECTION (etcd)                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                            │                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                 RECONCILIATION LOOP                       │  │
│  │     For each CMLWorker: SPEC ←→ OBSERVE → ACT            │  │
│  └──────────────────────────────────────────────────────────┘  │
│                            │                                    │
│                            ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              CLOUD PROVIDER SPI                           │  │
│  │                                                           │  │
│  │  ┌────────────────┐ ┌────────────────┐ ┌──────────────┐  │  │
│  │  │  AWS EC2 API   │ │ AWS CloudWatch │ │ CML System   │  │  │
│  │  │                │ │                │ │ API          │  │  │
│  │  │ • Describe     │ │ • CPU metrics  │ │ • /system_   │  │  │
│  │  │ • Start/Stop   │ │ • Memory       │ │   information│  │  │
│  │  │ • Terminate    │ │ • Network I/O  │ │ • /system_   │  │  │
│  │  │ • Create       │ │ • Disk         │ │   stats      │  │  │
│  │  └────────────────┘ └────────────────┘ │ • License    │  │  │
│  │                                        └──────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                            │                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   CONTROL PLANE API                       │  │
│  │         (All mutations via API - ADR-001)                 │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Reconciliation Examples

| Desired (Spec) | Actual (Observed) | Action |
|----------------|-------------------|--------|
| Worker status=RUNNING | EC2 stopped | Start EC2 instance |
| Worker status=RUNNING | EC2 running, CML unlicensed | Register CML license |
| Worker status=RUNNING | EC2 running, CML licensed | Update metrics, no action |
| Worker status=STOPPED | EC2 running | Stop EC2 instance |
| Worker status=TERMINATED | EC2 exists | Terminate EC2 instance |
| Worker imported=false | EC2 tagged for import | Create worker record |

## Key Design Decision

**API-Centric Mutations (ADR-001):** The Worker Controller does NOT write directly to MongoDB or etcd. All state changes are made via the Control Plane API:

- `PUT /api/internal/workers/{id}/status` - Update worker lifecycle state
- `PUT /api/internal/workers/{id}/metrics` - Update infrastructure metrics
- `POST /api/internal/workers/{id}/license-status` - Update license registration
- `POST /api/internal/workers/import` - Import discovered EC2 instances

## Development

```bash
# Install dependencies
make install

# Run locally
make run

# Run tests
make test

# Lint and format
make lint
make format
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `CONTROL_PLANE_API_URL` | Control Plane API endpoint | `http://localhost:8020` |
| `ETCD_HOST` | etcd host for leader election | `localhost` |
| `ETCD_PORT` | etcd port | `2379` |
| `AWS_ACCESS_KEY_ID` | AWS access key | - |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | - |
| `AWS_REGION` | AWS region | `us-east-1` |
| `RECONCILE_INTERVAL` | Reconciliation loop interval (seconds) | `30` |
| `METRICS_POLL_INTERVAL` | CloudWatch metrics poll interval (seconds) | `60` |
| `HEALTH_PORT` | Health check endpoint port | `8083` |
| `CML_WORKER_API_USERNAME` | CML system API username | - |
| `CML_WORKER_API_PASSWORD` | CML system API password | - |
| `CML_WEBSOCKET_ENABLED` | Enable WebSocket-based real-time monitoring (ADR-041) | `true` |
| `CML_WEBSOCKET_METRICS_REPORT_INTERVAL` | Seconds between metrics reports to CPA via WebSocket | `10` |
| `CML_WEBSOCKET_RECONNECT_MAX_INTERVAL` | Max reconnect backoff in seconds | `30` |
| `CML_WEBSOCKET_MAX_RECONNECT_ATTEMPTS` | Max consecutive failures before FAILED state | `3` |
| `CML_WEBSOCKET_HEALTH_TIMEOUT` | Seconds without messages before connection is unhealthy | `60` |

## Related Documents

- [Architecture Design](../../docs/architecture/lablet-resource-manager-architecture.md)
- [ADR-001: API-Centric State Management](../../docs/architecture/adr/ADR-001-api-centric-state-management.md)
- [Multi-Service Architecture](../../notes/MULTI_SERVICE_ARCHITECTURE_REFACTORING.md)
