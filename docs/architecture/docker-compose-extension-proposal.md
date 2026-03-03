# Docker Compose Shared Network Architecture

> **Status**: ✅ Implemented
> **Last Updated**: 2026-01-18

## Overview

The Mozart microservices ecosystem uses a **shared network pattern** that allows multiple projects (AIX, LCM) to share common infrastructure services while maintaining independent application services.

## Problem Statement (Solved)

Previously, `lablet-cloud-manager` (LCM) duplicated infrastructure services that are already defined in `aix`:

| Service | AIX Port | LCM Port | Now Shared? |
|---------|----------|----------|-------------|
| Keycloak | 8041 | 8021 | ✅ Yes |
| MongoDB | 27017 | 8022 | ✅ Yes |
| Redis | 6379 | 6379 | ✅ Yes |
| EventStore | 2113 | ❌ N/A | No (AIX-only) |
| Event Player | 8047 | 8024 | ✅ Yes |
| OTEL Collector | 4317 | 4317 | ✅ Yes |
| UI Builder | - | - | ✅ Yes |
| Mongo Express | - | 8023 | LCM-only |
| etcd | ❌ N/A | 2379 | LCM-only |
| Neo4j | 7474/7687 | ❌ N/A | AIX-only |
| Qdrant | 6333 | ❌ N/A | AIX-only |
| MinIO | 9000/9001 | ❌ N/A | AIX-only |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        mozart-net (external, bridge)                        │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    SHARED INFRASTRUCTURE (AIX)                       │   │
│  │    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │   │
│  │    │  Keycloak   │  │   MongoDB   │  │    Redis    │               │   │
│  │    │   :8041     │  │   :27017    │  │    :6379    │               │   │
│  │    └─────────────┘  └─────────────┘  └─────────────┘               │   │
│  │    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │   │
│  │    │ EventStore  │  │    OTEL     │  │   Events    │               │   │
│  │    │   :2113     │  │   :4317     │  │   Player    │               │   │
│  │    └─────────────┘  └─────────────┘  │    :8047    │               │   │
│  │                                       └─────────────┘               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌──────────────────────────────────┐  ┌──────────────────────────────┐   │
│  │       AIX SERVICES               │  │       LCM SERVICES           │   │
│  │  ┌──────────┐ ┌──────────┐      │  │  ┌──────────┐ ┌──────────┐  │   │
│  │  │  agent   │ │ knowledge│      │  │  │ control  │ │ resource │  │   │
│  │  │   host   │ │  manager │      │  │  │  plane   │ │ scheduler│  │   │
│  │  │  :8050   │ │  :8060   │      │  │  │  :8020   │ │  :8081   │  │   │
│  │  └──────────┘ └──────────┘      │  │  └──────────┘ └──────────┘  │   │
│  │  ┌──────────┐ ┌──────────┐      │  │  ┌──────────┐ ┌──────────┐  │   │
│  │  │  skills  │ │  cml-mcp │      │  │  │  lablet  │ │  worker  │  │   │
│  │  │ manager  │ │          │      │  │  │controller│ │controller│  │   │
│  │  │  :8070   │ │          │      │  │  │  :8082   │ │  :8083   │  │   │
│  │  └──────────┘ └──────────┘      │  │  └──────────┘ └──────────┘  │   │
│  └──────────────────────────────────┘  └──────────────────────────────┘   │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │               PROJECT-SPECIFIC INFRASTRUCTURE                         │  │
│  │    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │  │
│  │    │   Neo4j     │  │   Qdrant    │  │   MinIO     │  (AIX-only)    │  │
│  │    │   :7474     │  │   :6333     │  │   :9000     │                 │  │
│  │    └─────────────┘  └─────────────┘  └─────────────┘                 │  │
│  │    ┌─────────────┐                                                    │  │
│  │    │  lcm-etcd   │  (LCM-only)                                       │  │
│  │    │   :2379     │                                                    │  │
│  │    └─────────────┘                                                    │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Implemented Solution

### File Structure

```
Mozart/src/microservices/
├── aix/
│   ├── docker-compose.yml           # Full AIX stack (standalone)
│   ├── docker-compose.infra.yml     # ✅ Shared infrastructure
│   ├── docker-compose.local.yml     # ✅ Overlay to add AIX to mozart-net
│   └── .env
│
├── lablet-cloud-manager/
│   ├── docker-compose.yml           # Full LCM stack (standalone)
│   ├── docker-compose.shared.yml    # ✅ LCM services on mozart-net
│   ├── .env                         # Standalone configuration
│   └── .env-shared                  # ✅ Shared mode configuration
```

### LCM Shared Compose (`docker-compose.shared.yml`)

This file defines ONLY LCM-unique services connecting to the external `mozart-net`:

```yaml
name: lablet-cloud-manager-shared

services:
  # LCM Microservices
  control-plane-api:
    # ... connects to mozart-keycloak, mozart-mongodb, mozart-redis
    networks:
      - mozart-net

  resource-scheduler:
    networks:
      - mozart-net

  lablet-controller:
    networks:
      - mozart-net

  worker-controller:
    networks:
      - mozart-net

  # LCM-specific infrastructure
  lcm-etcd:
    container_name: lcm-etcd
    networks:
      - mozart-net

networks:
  mozart-net:
    external: true
    name: mozart-net
```

### Makefile Commands

```makefile
# Shared mode targets (LCM on mozart-net)
SHARED_COMPOSE_FILE := docker-compose.shared.yml
SHARED_ENV_FILE := .env-shared
SHARED_COMPOSE := docker-compose -f $(SHARED_COMPOSE_FILE) --env-file $(SHARED_ENV_FILE)

check-mozart-net:  ## Check if mozart-net network exists
 @docker network inspect mozart-net >/dev/null 2>&1 || \
  (echo "Error: mozart-net not found. Start AIX infra first." && exit 1)

up-shared: check-mozart-net  ## Start LCM services using shared AIX infrastructure
 $(SHARED_COMPOSE) up -d

down-shared:  ## Stop LCM services (shared mode)
 $(SHARED_COMPOSE) down

logs-shared:  ## Show logs from LCM services (shared mode)
 $(SHARED_COMPOSE) logs -f

urls-shared:  ## Display URLs when running in shared mode
 @echo "LCM Microservices:"
 @echo "  Control Plane API: http://localhost:8020"
 @echo "Shared Infrastructure (AIX):"
 @echo "  Keycloak:          http://localhost:8041"
 @echo "  MongoDB:           mongodb://localhost:27017"
```

## Usage

### Mode 1: Standalone (Default)

Each project runs independently with its own infrastructure:

```bash
# LCM standalone (includes all infrastructure)
cd lablet-cloud-manager
make up          # Uses docker-compose.yml + .env

# AIX standalone (includes all infrastructure)
cd aix
make up          # Uses docker-compose.yml
```

### Mode 2: Shared Network (Development)

Projects share common infrastructure to reduce resource usage:

```bash
# Step 1: Start AIX shared infrastructure
cd aix
docker compose -f docker-compose.infra.yml up -d

# Step 2: Start LCM services on mozart-net
cd lablet-cloud-manager
make up-shared   # Uses docker-compose.shared.yml + .env-shared

# Step 3: (Optional) Start AIX services on mozart-net
cd aix
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

## Configuration Differences

### Container Name References

| Mode | Keycloak | MongoDB | Redis | OTEL |
|------|----------|---------|-------|------|
| Standalone | keycloak | mongodb | redis | otel-collector |
| Shared | mozart-keycloak | mozart-mongodb | mozart-redis | mozart-otel-collector |

### Port Mapping

| Service | Standalone Port | Shared Port |
|---------|-----------------|-------------|
| Keycloak | 8031 | 8041 |
| MongoDB | 8032 | 27017 |
| Redis | 8034 | 6379 |
| OTEL Collector | 4337 | 4317 |
| Events Player | 8035 | 8047 |

### Environment Variables (.env-shared)

Key differences in shared mode:

```bash
# Keycloak - Uses AIX's shared instance with AIX realm
KEYCLOAK_PORT=8041
KEYCLOAK_URL=http://localhost:8041
KEYCLOAK_URL_INTERNAL=http://mozart-keycloak:8080
KEYCLOAK_REALM=aix
KEYCLOAK_CLIENT_ID=lcm-public
EXPECTED_ISSUER="http://localhost:8041/realms/aix"
EXPECTED_AUDIENCE=["lcm"]

# MongoDB - Uses AIX's shared instance
MONGODB_PORT=27017
# Connection via mozart-mongodb container

# Redis - Uses AIX's shared instance
REDIS_PORT=6379
REDIS_KEY_PREFIX=lcm-session:  # Namespaced to avoid collisions

# OTEL - Uses AIX's shared collector
OTEL_EXPORTER_OTLP_ENDPOINT=http://mozart-otel-collector:4317
```

## Keycloak Realm Configuration

In shared mode, LCM uses the **AIX realm** (`aix`) instead of a separate `lablet-cloud-manager` realm. This enables:

- Single Sign-On (SSO) across AIX and LCM applications
- Shared user management and role definitions
- Simplified authentication configuration

### Required: Add LCM Clients to AIX Realm

The LCM clients must be added to the AIX realm export. See:

- [`deployment/keycloak/lcm-clients-for-aix-realm.json`](../../deployment/keycloak/lcm-clients-for-aix-realm.json)

#### Client Scopes to Add

| Scope | Description |
|-------|-------------|
| `lcm-audience` | Adds `lcm` audience to access tokens |

#### Clients to Add

| Client ID | Type | Description |
|-----------|------|-------------|
| `lcm-public` | Public | Browser-based OAuth2 Authorization Code flow |
| `lcm-backend` | Confidential | API backend with service account |
| `lcm-service` | Confidential | Service account for microservice communication |

### Manual Import Steps

1. Access Keycloak Admin: <http://localhost:8041>
2. Select the `aix` realm
3. Navigate to **Client Scopes** → **Create**
4. Add the `lcm-audience` scope from the JSON file
5. Navigate to **Clients** → **Create**
6. Add each client (`lcm-public`, `lcm-backend`, `lcm-service`)
7. Configure redirect URIs and client secrets as needed

### Automated Import (Recommended)

Add the LCM client definitions directly to `aix-realm-export.json`:

1. Copy `clientScopes` entries to the AIX realm's `clientScopes` array
2. Copy `clients` entries to the AIX realm's `clients` array
3. Restart Keycloak to reimport the realm

## Benefits

1. **Resource Efficiency**: Single instance of Keycloak, MongoDB, Redis instead of duplicates
2. **Consistent Configuration**: Same infrastructure versions across projects
3. **Cross-Project Communication**: Services can communicate via mozart-net
4. **Easier Debugging**: Single OTEL collector for all traces/metrics
5. **Single Sign-On (SSO)**: Shared AIX realm enables SSO across all Mozart applications

## Troubleshooting

### mozart-net Not Found

```bash
# Create manually if AIX infra not running
docker network create mozart-net

# Or start AIX infrastructure
cd ../aix && docker compose -f docker-compose.infra.yml up -d
```

### Container Name Conflicts

If switching between modes, clean up old containers:

```bash
make down           # Stop standalone mode
make down-shared    # Stop shared mode
docker compose down --remove-orphans
```

### Redis Key Collisions

Shared mode uses namespaced Redis keys (`lcm-session:` prefix) to avoid collisions with AIX sessions.

### Keycloak Realm Missing

### LCM Clients Not in AIX Realm

If authentication fails with "invalid audience" or similar errors:

1. Verify LCM clients are added to AIX realm (see `lcm-clients-for-aix-realm.json`)
2. Check that `lcm-audience` client scope exists
3. Ensure clients have the correct audience mapper

## Migration Path

To migrate from standalone to shared mode:

1. Stop standalone services: `make down`
2. Start AIX infrastructure: `cd ../aix && docker compose -f docker-compose.infra.yml up -d`
3. Add LCM clients to AIX realm (see Keycloak section above)
4. Start LCM in shared mode: `make up-shared`
5. Verify connectivity: `make urls-shared`

## Related Files

- [docker-compose.shared.yml](../../docker-compose.shared.yml) - LCM services for shared mode
- [.env-shared](../../.env-shared) - Shared mode environment configuration
- [lcm-clients-for-aix-realm.json](../../deployment/keycloak/lcm-clients-for-aix-realm.json) - LCM client definitions for AIX realm
- [AIX docker-compose.infra.yml](../../../aix/docker-compose.infra.yml) - Shared infrastructure
- [AIX docker-compose.local.yml](../../../aix/docker-compose.local.yml) - AIX overlay for mozart-net
- [AIX aix-realm-export.json](../../../aix/deployment/keycloak/aix-realm-export.json) - AIX realm with shared clients
