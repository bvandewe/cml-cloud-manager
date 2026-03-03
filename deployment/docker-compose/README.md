# Production Docker Compose Setup

This directory contains the production Docker Compose configuration for Lablet Cloud Manager.

## Architecture

The production setup uses a **multi-service architecture** with:

- **API Service** (`api`): Handles HTTP traffic and web requests on port `8020`
- **Worker Service** (`worker`): Runs background jobs (metrics collection, auto-import, lab refresh) on port `8021`

Both services share the same codebase but have different responsibilities:

- API service: Web traffic only, background jobs disabled
- Worker service: Background jobs enabled, can also serve health checks

## Quick Start

### 1. Configure Environment Variables

Edit `.env.prod` and update the following critical settings:

```bash
# Security - CHANGE THESE IN PRODUCTION!
JWT_SECRET_KEY=change-me-in-production-use-long-random-string
KEYCLOAK_ADMIN_PASSWORD=change-me-in-production
MONGODB_ROOT_PASSWORD=change-me-in-production
CML_WORKER_API_PASSWORD=change-me-in-production

# AWS Credentials
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key

# CML Worker Configuration
CML_WORKER_SECURITY_GROUP_IDS=["sg-xxxxxxxxxxxxxxxxx"]
CML_WORKER_SUBNET_ID=subnet-xxxxxxxxx
CML_WORKER_KEY_NAME=your-key-name
```

### 2. Start the Stack

```bash
cd /path/to/lablet-cloud-manager
docker-compose -f deployment/docker-compose/docker-compose.prod.yml --env-file deployment/docker-compose/.env.prod up -d
```

### 3. Access Services

**Main Entry Point (via Nginx):**

- **Lablet Cloud Manager**: http://localhost (port 80)
- **API**: http://localhost/api/
- **Health Check**: http://localhost/health

**Subdomain Access (configure /etc/hosts or DNS):**

- **Grafana**: http://grafana.localhost
- **Prometheus**: http://prometheus.localhost
- **Keycloak**: http://keycloak.localhost
- **Event Player**: http://event-player.localhost

**Direct Service Access (bypass nginx):**

- **Keycloak Admin**: http://localhost:8090 (kept for admin console)
- **MongoDB Express**: http://localhost:8081
- **Prometheus**: http://localhost:9090 (optional direct access)

**Note**: Most services are now accessed through nginx for better security and unified access.

### 4. View Logs

```bash
# All services
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs -f

# API service only
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs -f api

# Worker service only
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs -f worker
```

### 5. Stop the Stack

```bash
docker-compose -f deployment/docker-compose/docker-compose.prod.yml --env-file deployment/docker-compose/.env.prod down
```

## Port Mapping

| Service | Container Port | Host Port | Access Method |
|---------|---------------|-----------|---------------|
| **Nginx** | 80 | 80 | **Main entry point** |
| API | 8000 | - | Via nginx only |
| Worker | 8000 | - | Internal only |
| Keycloak | 8080 | 8090 | Direct + via nginx at /auth |
| MongoDB | 27017 | 27017 | Database connection |
| Mongo Express | 8081 | 8081 | Direct access |
| Redis | 6379 | 6379 | Internal only |
| Event Player | 8080 | - | Via nginx (event-player.localhost) |
| OTEL Collector (gRPC) | 4317 | 4317 | Internal only |
| OTEL Collector (HTTP) | 4318 | 4318 | Internal only |
| OTEL Collector (Metrics) | 8888 | 8888 | Internal metrics |
| OTEL Collector (Prometheus) | 8889 | - | Scraped by Prometheus |
| Grafana | 3000 | - | Via nginx (grafana.localhost) |
| Prometheus | 9090 | 9090 | Direct (optional) + via nginx |
| Tempo | 3200 | - | Internal only |
| Loki | 3100 | - | Internal only |

**Key Changes with Nginx:**

- Single entry point on port 80 instead of multiple exposed ports
- Services accessed via nginx proxy (improved security)
- Subdomain routing available (*.localhost)
- Rate limiting and security headers enforced

## Network Configuration

All services run on the `lablet-cloud-manager-net` Docker bridge network, allowing them to communicate using service names as hostnames.

## Service Dependencies

```
API Service depends on:
  - mongodb
  - keycloak
  - redis

Worker Service depends on:
  - mongodb
  - keycloak
  - redis

Event Player depends on:
  - keycloak

Mongo Express depends on:
  - mongodb
```

## Background Jobs Configuration

The **Worker service** is responsible for all background jobs:

- **Auto-import workers**: Discovers and imports existing CML workers from AWS (configurable interval)
- **Labs refresh**: Syncs lab data from all workers (configurable interval)
- **Worker metrics collection**: Polls metrics from workers and AWS CloudWatch (per-worker interval)

These jobs are **disabled on the API service** to prevent duplicate execution.

## Observability Stack

The production setup includes a complete observability stack:

### Components

- **Grafana**: Unified dashboard for visualizing metrics, traces, and logs
  - Pre-configured datasources for Tempo, Prometheus, and Loki
  - Access at http://localhost:3001 (admin/admin)
  - Features trace correlation, service maps, and log search

- **Tempo**: Distributed tracing backend
  - Stores and queries distributed traces
  - Receives OTLP traces from applications via OTEL Collector
  - Integrated with Prometheus for service graphs

- **Prometheus**: Metrics storage and query engine
  - Scrapes metrics from OTEL Collector (on port 8889)
  - Scrapes API and Worker services directly
  - 30-day retention period

- **Loki**: Log aggregation system
  - Receives logs from OTEL Collector
  - Indexed by trace IDs for correlation
  - 7-day retention period

- **OTEL Collector**: Central telemetry hub
  - Receives traces, metrics, and logs from applications
  - Exports to Tempo (traces), Prometheus (metrics), and Loki (logs)
  - Configuration: `deployment/otel/otel-collector-config.yaml`

### Configuration Files

All observability configurations are in `deployment/otel/`:

- `otel-collector-config.yaml`: OTEL Collector pipelines
- `tempo.yaml`: Tempo storage and ingester settings
- `prometheus.yml`: Prometheus scrape configurations
- `loki-config.yaml`: Loki retention and ingestion settings

Grafana datasources are auto-provisioned from `deployment/grafana/datasources/`.

### Viewing Telemetry

1. **Metrics**: http://localhost:3001 → Explore → Prometheus
2. **Traces**: http://localhost:3001 → Explore → Tempo
3. **Logs**: http://localhost:3001 → Explore → Loki
4. **Raw Prometheus**: http://localhost:9090

## Differences from Local Development

| Aspect | Local Dev | Production |
|--------|-----------|------------|
| Compose file | `docker-compose.yml` (root) | `deployment/docker-compose/docker-compose.prod.yml` |
| Env file | `.env` (root) | `deployment/docker-compose/.env.prod` |
| Architecture | Single `app` service | Separate `api` + `worker` services |
| Ports | 8030, 8031, 8032, etc. | 8020, 8021, 8090, etc. |
| Debug | Enabled (debugpy on port 5678) | Disabled |
| Hot reload | Enabled (--reload, ui-builder) | Disabled |
| Workers | 1 uvicorn worker | 1 uvicorn worker |
| UI building | Live watch mode | Pre-built (must run `make build-ui` first) |

**IMPORTANT**: The local development setup is completely independent and unaffected by this production configuration.

## Healthchecks

Both API and worker services include health check endpoints:

```bash
# Check API health
curl http://localhost:8020/health

# Check Worker health
curl http://localhost:8021/health
```

Health checks run every 30 seconds with a 40-second startup grace period.

## Scaling

To scale horizontally:

```bash
# Scale API service (web traffic)
docker-compose -f deployment/docker-compose/docker-compose.prod.yml --env-file deployment/docker-compose/.env.prod up -d --scale api=3

# DO NOT scale worker service (would cause duplicate background jobs)
```

**Note**: Only scale the API service. The worker service should remain as a single instance to avoid duplicate background job execution.

## Troubleshooting

### Services won't start

Check if ports are already in use:

```bash
lsof -i :8020  # API port
lsof -i :8021  # Worker port
lsof -i :8090  # Keycloak port
```

### Can't connect to MongoDB

Verify connection string in container:

```bash
docker-compose -f deployment/docker-compose/docker-compose.prod.yml exec api env | grep CONNECTION_STRINGS
```

### Background jobs not running

Check worker service logs:

```bash
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs -f worker | grep -E "(Job|Scheduler|Background)"
```

### Authentication issues

Verify Keycloak realm import:

```bash
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs keycloak | grep "lablet-cloud-manager"
```

## Security Considerations

1. **Change all default passwords** in `.env.prod`
2. **Use AWS IAM roles** instead of access keys when deploying to AWS
3. **Enable HTTPS** with a reverse proxy (nginx, Traefik, etc.)
4. **Restrict network access** using Docker network policies or firewall rules
5. **Set proper CORS origins** in production (not `*`)
6. **Use secrets management** (Docker Secrets, AWS Secrets Manager, etc.)
7. **Enable audit logging** for Keycloak and MongoDB
8. **Regularly update base images** and dependencies

## Maintenance

### Backup MongoDB data

```bash
docker-compose -f deployment/docker-compose/docker-compose.prod.yml exec mongodb mongodump --out=/data/backup
docker cp $(docker-compose -f deployment/docker-compose/docker-compose.prod.yml ps -q mongodb):/data/backup ./mongodb-backup
```

### Update images

```bash
docker-compose -f deployment/docker-compose/docker-compose.prod.yml pull
docker-compose -f deployment/docker-compose/docker-compose.prod.yml up -d
```

### Clean up

```bash
# Remove stopped containers
docker-compose -f deployment/docker-compose/docker-compose.prod.yml down

# Remove volumes (WARNING: deletes all data)
docker-compose -f deployment/docker-compose/docker-compose.prod.yml down -v
```
