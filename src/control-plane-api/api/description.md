## Overview

The **Control Plane API** is the central management service for Lablet Cloud Manager (LCM). It provides RESTful endpoints for managing AWS EC2-based Cisco Modeling Lab (CML) workers, lablet definitions, lablet instances, and lab operations.

**Key Features:**

- 🚀 CML Worker lifecycle management (provision, start, stop, terminate)
- 📦 Lablet Definitions - reusable lab templates with topologies
- 🧪 Lablet Instances - scheduled lab sessions with time-based access
- 🔬 Lab Operations - create, start, stop, wipe, delete CML labs
- 📊 Real-time monitoring via Server-Sent Events (SSE)
- 🔐 Dual authentication: OAuth2/OIDC (Keycloak) + JWT bearer tokens
- 🔒 Internal API endpoints for service-to-service communication (X-API-Key)

## Authentication

This API supports **three authentication methods**:

### 1. OAuth2 Authorization Code Flow (Browser)

For web applications and Swagger UI:

- Click "Authorize" button in Swagger UI
- Login via Keycloak SSO (AIX realm)
- Session managed server-side with httpOnly cookies

### 2. JWT Bearer Token (Programmatic)

For API clients, scripts, and automation:

```bash
# Obtain token from Keycloak
TOKEN=$(curl -X POST "http://localhost:8041/realms/aix/protocol/openid-connect/token" \
  -d "client_id=lcm-public" \
  -d "grant_type=password" \
  -d "username=user@example.com" \
  -d "password=your-password" | jq -r .access_token)

# Use token in API requests
curl -H "Authorization: Bearer $TOKEN" http://localhost:8030/api/workers/region/us-east-1/workers
```

### 3. X-API-Key (Service-to-Service)

For internal communication between LCM microservices:

- Used by resource-scheduler, lablet-controller, worker-controller
- Requires `X-API-Key` header with configured internal API key
- Access restricted to `/internal/*` endpoints

TODO

## Support & Documentation

- **Full Documentation**: [MkDocs Site](https://bvandewe.github.io/lablet-cloud-manager/)
- **Source Code**: [GitHub Repository](https://github.com/bvandewe/CML-Cloud-Manager)
