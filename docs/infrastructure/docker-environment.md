# Docker Development Environment

This application uses Docker Compose to provide a complete development stack with all necessary services.

## Services Overview

The development environment includes:

- **Application** - FastAPI backend with hot-reload
- **UI Builder** - Parcel bundler for frontend assets
- **MongoDB** - NoSQL database for task persistence
- **MongoDB Express** - Web-based database admin UI
- **Keycloak** - Identity and access management (OAuth2/OIDC)
- **Redis** - Session store and caching
- **OpenTelemetry Collector** - Observability and tracing

## Quick Start

### Start All Services

```bash
make docker-up
```

This starts all services in detached mode (background).

### View Logs

```bash
# All services
make docker-logs

# Specific service
docker compose logs -f app
docker compose logs -f keycloak
```

### Stop Services

```bash
make docker-down
```

### Rebuild from Scratch

```bash
make docker-rebuild
```

## Service Details

### Application Service

**Container**: `lablet-cloud-manager`
**Port**: 8020
**Debug Port**: 5678

The main FastAPI application with:

- Hot-reload enabled (watches `/app/src` directory)
- Debug port for VS Code debugging
- Environment variables from `.env` file

**Access**:

- Application: http://localhost:8020
- API Docs: http://localhost:8020/api/docs
- Health Check: http://localhost:8020/health

**Configuration**:

```yaml
app:
  build:
    context: .
    dockerfile: Dockerfile
  ports:
    - "${APP_PORT:-8020}:8020"
    - "5678:5678"
  volumes:
    - ./src:/app/src
  environment:
    - PYTHONUNBUFFERED=1
    - RELOAD=true
  depends_on:
    - mongodb
    - redis
    - keycloak
```

### UI Builder Service

**Container**: `ui-builder`
**Purpose**: Automatic frontend asset building

Watches `src/ui/` directory and rebuilds on changes:

- Compiles SCSS to CSS
- Bundles JavaScript with Parcel
- Processes Nunjucks templates
- Outputs to `static/` directory

**No manual build needed** - saves automatically compile.

### MongoDB

**Container**: `mongodb`
**Port**: 27017
**Database**: `lablet_cloud_manager`

MongoDB 6.0 for task storage.

**Default Credentials**:

- Username: `root`
- Password: `neuroglia123`

**Connection String**:

```
mongodb://root:neuroglia123@localhost:27017/lablet_cloud_manager?authSource=admin
```

**Persistent Storage**: Docker volume `mongodb_data`

### MongoDB Express

**Container**: `mongo-express`
**Port**: 8081

Web-based MongoDB administration interface.

**Access**: http://localhost:8081

**Features**:

- Browse databases and collections
- View and edit documents
- Execute queries
- Import/export data

**Note**: Authentication disabled for development convenience.

### Keycloak

**Container**: `keycloak`
**Port**: 8090
**Version**: 22.0.5

Identity provider for OAuth2/OIDC authentication.

**Access**:

- Keycloak: http://localhost:8090
- Admin Console: http://localhost:8090/admin

**Admin Credentials**:

- Username: `admin`
- Password: `admin`

**Realm**: `lablet-cloud-manager`

**Configuration**:

- Automatic realm import on startup
- Realm config: `deployment/keycloak/lablet-cloud-manager-realm-export.json`
- Pre-configured test users (admin, manager, user)

**Persistent Storage**: Docker volume `keycloak_data`

### Redis

**Container**: `redis`
**Port**: 6379

Session storage and caching.

**Features**:

- Persistence enabled (AOF)
- No password (development only)
- Persistent volume: `redis_data`

**Connection**: `redis://localhost:6379`

### OpenTelemetry Collector

**Container**: `otel-collector`

Centralized telemetry collection for observability.

**Ports**:

- 4317 - OTLP gRPC receiver
- 4318 - OTLP HTTP receiver
- 8888 - Prometheus metrics endpoint
- 13133 - Health check endpoint

**Configuration**: `deployment/otel-collector-config.yaml`

**Features**:

- Trace collection
- Metrics collection
- Log aggregation
- Export to various backends

## Port Summary

| Service | Port | URL |
|---------|------|-----|
| Application | 8020 | http://localhost:8020 |
| API Docs | 8020 | http://localhost:8020/api/docs |
| Debug Port | 5678 | - |
| MongoDB | 27017 | mongodb://localhost:27017 |
| MongoDB Express | 8081 | http://localhost:8081 |
| Keycloak | 8090 | http://localhost:8090 |
| Redis | 6379 | redis://localhost:6379 |
| OTEL gRPC | 4317 | - |
| OTEL HTTP | 4318 | - |
| OTEL Metrics | 8888 | http://localhost:8888/metrics |
| OTEL Health | 13133 | http://localhost:13133 |

## Environment Configuration

All ports and settings configurable via `.env` file:

```bash
# Application
APP_PORT=8020
DEBUG=true
LOG_LEVEL=INFO

# MongoDB
MONGODB_HOST=mongodb
MONGODB_PORT=27017
MONGODB_DATABASE=lablet_cloud_manager
MONGODB_USERNAME=root
MONGODB_PASSWORD=neuroglia123

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
SESSION_TTL=3600

# Keycloak
KEYCLOAK_HOST=http://keycloak:8080
KEYCLOAK_REALM=lablet-cloud-manager
KEYCLOAK_CLIENT_ID=lablet-cloud-manager-client
KEYCLOAK_CLIENT_SECRET=your-secret

# OpenTelemetry
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_SERVICE_NAME=lablet-cloud-manager
```

## Networking

All services communicate via `lablet-cloud-manager-net` bridge network.

**DNS Resolution**:

- Services accessible by container name
- Example: `mongodb://mongodb:27017` from app container

## Persistent Volumes

Data persisted across container restarts:

- `mongodb_data` - MongoDB database files
- `keycloak_data` - Keycloak realm and user data
- `redis_data` - Redis AOF persistence

### Backup Volumes

```bash
docker run --rm -v lablet-cloud-manager_mongodb_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/mongodb-backup.tar.gz /data
```

### Clean Volumes (⚠️ Destroys Data)

```bash
make docker-clean
# or
docker compose down -v
```

## Development Workflows

### Daily Development

```bash
# Terminal 1: Start services
make docker-up

# Terminal 2: Follow application logs
make docker-logs-app

# Code changes auto-reload
# UI changes auto-rebuild
```

### Debugging

```bash
# Start with debug enabled
make docker-up

# Attach debugger to port 5678
# VS Code: Use "Attach to Docker" launch configuration
```

### Testing

```bash
# Run tests in Docker
docker compose exec app poetry run pytest

# Run with coverage
docker compose exec app poetry run pytest --cov=src
```

### Database Access

```bash
# MongoDB shell
docker compose exec mongodb mongosh -u root -p neuroglia123

# Redis CLI
docker compose exec redis redis-cli

# MongoDB Express Web UI
open http://localhost:8081
```

## Troubleshooting

### Service Won't Start

**Check logs**:

```bash
docker compose logs <service-name>
```

**Check health**:

```bash
docker compose ps
```

**Restart service**:

```bash
docker compose restart <service-name>
```

### Port Conflicts

**Symptom**: "port is already allocated"

**Solution**: Change port in `.env`:

```bash
APP_PORT=8021  # Use different port
```

### Database Connection Errors

**Check MongoDB is running**:

```bash
docker compose ps mongodb
```

**Verify credentials** in `.env` match `docker-compose.yml`

**Test connection**:

```bash
docker compose exec mongodb mongosh -u root -p neuroglia123
```

### Hot-Reload Not Working

**Verify volume mount**:

```bash
docker compose config | grep volumes -A 5
```

**Should show**: `./src:/app/src`

**Restart container**:

```bash
docker compose restart app
```

### Clean Slate Rebuild

```bash
# Stop everything
make docker-down

# Remove volumes (⚠️ loses data)
docker compose down -v

# Rebuild images
make docker-rebuild

# Start fresh
make docker-up
```

## Production Considerations

⚠️ **This setup is for development only**

For production:

1. **Use orchestration** - Kubernetes, Docker Swarm
2. **External databases** - Managed MongoDB, Redis
3. **Environment secrets** - Use secrets manager
4. **HTTPS** - Terminate SSL at load balancer
5. **Resource limits** - Set memory/CPU limits
6. **Health checks** - Configure proper health endpoints
7. **Monitoring** - External observability platform
8. **Backups** - Automated database backups
9. **Scaling** - Multiple app instances
10. **Security** - Network policies, least privilege

## Related Documentation

- [Getting Started](../getting-started/installation.md) - Setup and installation
- [Frontend Build Process](../frontend/build-process.md) - UI build pipeline
- [Makefile Reference](../development/makefile-reference.md) - Docker commands
- [Authentication Flows](../security/authentication-flows.md) - Keycloak integration
