# Production Setup Quick Reference

## 🚀 Quick Start

```bash
# Start the full stack
docker-compose -f deployment/docker-compose/docker-compose.prod.yml --env-file deployment/docker-compose/.env.prod up -d

# View logs
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs -f

# Stop the stack
docker-compose -f deployment/docker-compose/docker-compose.prod.yml down
```

## 🌐 Service URLs

**Primary Access (via Nginx Reverse Proxy):**

| Service | URL | Credentials |
|---------|-----|-------------|
| Lablet Cloud Manager | http://localhost | Via Keycloak |
| API | http://localhost/api/ | Via Keycloak |
| Health Check | http://localhost/health | None |

**Subdomain Access (configure DNS or /etc/hosts):**

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://grafana.localhost | admin / admin |
| Prometheus | http://prometheus.localhost | None |
| Keycloak | http://keycloak.localhost | admin / [from .env.prod] |
| Event Player | http://event-player.localhost | Via Keycloak |

**Direct Service Access (bypass nginx):**

| Service | URL | Credentials |
|---------|-----|-------------|
| Keycloak Admin Console | http://localhost:8090 | admin / [from .env.prod] |
| MongoDB Express | http://localhost:8081 | None |
| Prometheus (direct) | http://localhost:9090 | None |
| Tempo | http://localhost:3200 | None |
| Loki | http://localhost:3100 | None |

## 📊 Observability Stack

### Grafana Dashboards

1. Navigate to http://localhost:3001
2. Go to **Explore** to query:
   - **Prometheus**: View metrics from API, Worker, and OTEL Collector
   - **Tempo**: View distributed traces with service maps
   - **Loki**: View logs with trace correlation

### Direct Access

- **Prometheus UI**: http://localhost:9090/graph
- **Prometheus Targets**: http://localhost:9090/targets
- **Tempo API**: http://localhost:3200/api/search
- **Loki API**: http://localhost:3100/ready

## 🔧 Configuration Files

### Application

- **Docker Compose**: `deployment/docker-compose/docker-compose.prod.yml`
- **Environment**: `deployment/docker-compose/.env.prod`

### Observability

- **OTEL Collector**: `deployment/otel/otel-collector-config.yaml`
- **Tempo**: `deployment/otel/tempo.yaml`
- **Prometheus**: `deployment/otel/prometheus.yml`
- **Loki**: `deployment/otel/loki-config.yaml`

### Grafana

- **Datasources**: `deployment/grafana/datasources/datasources.yaml`
- **Dashboards**: `deployment/grafana/dashboards/dashboards.yaml`

## 🐳 Docker Commands

```bash
# Check service status
docker-compose -f deployment/docker-compose/docker-compose.prod.yml ps

# View specific service logs
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs -f api
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs -f worker
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs -f otel-collector

# Restart a service
docker-compose -f deployment/docker-compose/docker-compose.prod.yml restart api

# Scale API (NOT worker!)
docker-compose -f deployment/docker-compose/docker-compose.prod.yml up -d --scale api=3

# Execute command in container
docker-compose -f deployment/docker-compose/docker-compose.prod.yml exec api /bin/sh

# Clean up everything (WARNING: removes volumes)
docker-compose -f deployment/docker-compose/docker-compose.prod.yml down -v
```

## 🔍 Health Checks

```bash
# Nginx (main entry point)
curl http://localhost/health

# API Health (via nginx)
curl http://localhost/health

# API Health (direct)
curl http://localhost:8000/health  # Won't work - not exposed

# Worker Health (internal only)
# Not accessible externally - access via docker exec

# OTEL Collector Health
curl http://localhost:13133

# Prometheus Health
curl http://localhost:9090/-/healthy

# Tempo Ready
curl http://localhost:3200/ready

# Loki Ready
curl http://localhost:3100/ready

# Grafana Health (via subdomain)
curl http://grafana.localhost/api/health
```

## 📝 Metrics Queries (Prometheus)

```promql
# API request rate
rate(http_server_requests_total{job="lablet-cloud-manager-api"}[5m])

# Worker job execution count
increase(background_job_executions_total{job="lablet-cloud-manager-worker"}[1h])

# Memory usage
process_resident_memory_bytes{job=~"lablet-cloud-manager-.*"}

# CPU usage
rate(process_cpu_seconds_total{job=~"lablet-cloud-manager-.*"}[5m])
```

## 🔎 Log Queries (Loki via Grafana)

```logql
# API logs
{job="lablet-cloud-manager-api"}

# Worker logs
{job="lablet-cloud-manager-worker"}

# Error logs only
{job=~"lablet-cloud-manager-.*"} |= "ERROR"

# Logs with trace correlation
{job="lablet-cloud-manager-api"} | json | trace_id != ""
```

## 🎯 Trace Queries (Tempo via Grafana)

1. Go to Grafana → Explore → Tempo
2. Use **TraceQL** queries:

```traceql
# Find traces from API service
{ service.name = "lablet-cloud-manager-api" }

# Find slow traces (>1s)
{ duration > 1s }

# Find traces with errors
{ status = error }

# Find traces for specific endpoint
{ http.target = "/api/workers" }
```

## 🚨 Troubleshooting

### Services won't start

```bash
# Check if ports are in use
lsof -i :8020 :8021 :8090 :3001 :9090

# Check logs for errors
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs --tail=50
```

### OTEL Collector not receiving data

```bash
# Check collector logs
docker-compose -f deployment/docker-compose/docker-compose.prod.yml logs otel-collector

# Verify endpoints are accessible
curl -X POST http://localhost:4318/v1/traces
```

### Grafana datasources not working

```bash
# Check if backend services are up
curl http://localhost:9090/-/healthy  # Prometheus
curl http://localhost:3200/ready      # Tempo
curl http://localhost:3100/ready      # Loki

# Restart Grafana
docker-compose -f deployment/docker-compose/docker-compose.prod.yml restart grafana
```

### No metrics in Prometheus

```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets | jq

# Check if OTEL Collector is exporting
curl http://localhost:8889/metrics
```

## 🔐 Security Checklist

Before production deployment:

- [ ] Change `KEYCLOAK_ADMIN_PASSWORD` in `.env.prod`
- [ ] Change `JWT_SECRET_KEY` in `.env.prod`
- [ ] Change `MONGODB_ROOT_PASSWORD` in `.env.prod`
- [ ] Change `CML_WORKER_API_PASSWORD` in `.env.prod`
- [ ] Set proper AWS credentials or use IAM roles
- [ ] Configure HTTPS/TLS with reverse proxy
- [ ] Set up firewall rules
- [ ] Enable Grafana authentication
- [ ] Review CORS settings
- [ ] Enable audit logging

## 📦 Backup & Restore

### MongoDB Backup

```bash
docker-compose -f deployment/docker-compose/docker-compose.prod.yml exec mongodb \
  mongodump --out=/data/backup --authenticationDatabase=admin \
  -u root -p <password>

docker cp $(docker-compose -f deployment/docker-compose/docker-compose.prod.yml ps -q mongodb):/data/backup ./backup-$(date +%Y%m%d)
```

### Volume Backup

```bash
# Backup all volumes
docker run --rm -v lablet-cloud-manager_mongodb_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/mongodb_data.tar.gz -C /data .
```

## 📚 Additional Resources

- Full documentation: [README.md](README.md)
- Verification checklist: [VERIFICATION.md](VERIFICATION.md)
- Local development: See root `docker-compose.yml`
