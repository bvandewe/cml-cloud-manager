# Control Plane API Guide

## Overview

The Lablet Cloud Manager Control Plane API provides a comprehensive REST API for managing Cisco Modeling Lab (CML) workers, lablet definitions, and lablet instances. This guide covers the main API endpoints, authentication patterns, and usage examples.

## Base URLs

| Environment | Base URL |
|-------------|----------|
| Local Development | `http://localhost:8000/api` |
| Docker Compose | `http://localhost:8010/api` |
| Production | `https://lablet.your-domain.com/api` |

## Authentication

The API supports dual authentication mechanisms:

### Cookie-Based Authentication (UI)

Used by the web UI with Keycloak OIDC integration:

1. Browser initiates login: `GET /api/auth/login`
2. Keycloak authentication flow
3. Server sets httpOnly cookie with session ID
4. Subsequent requests include cookie automatically

### Bearer Token Authentication (API)

Used for programmatic access:

```bash
curl -X GET "http://localhost:8000/api/workers" \
  -H "Authorization: Bearer <JWT_TOKEN>"
```

Tokens can be obtained from Keycloak using the password grant or client credentials flow.

## Core Endpoints

### Workers

Manage CML worker instances (AWS EC2 instances running CML):

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/workers` | List all workers |
| `GET` | `/api/workers/{id}` | Get worker details |
| `POST` | `/api/workers` | Create/import a worker |
| `POST` | `/api/workers/{id}/start` | Start a stopped worker |
| `POST` | `/api/workers/{id}/stop` | Stop a running worker |
| `DELETE` | `/api/workers/{id}` | Terminate a worker |

#### Example: List Workers

```bash
curl -X GET "http://localhost:8000/api/workers" \
  -H "Authorization: Bearer $TOKEN"
```

Response:

```json
{
  "workers": [
    {
      "id": "worker-abc123",
      "name": "cml-worker-prod-01",
      "status": "running",
      "aws_instance_id": "i-0abc123def456789",
      "aws_region": "us-west-2",
      "ip_address": "10.0.1.50",
      "cml_service_status": "available",
      "license_status": "registered"
    }
  ]
}
```

### Lablet Definitions

Manage lab templates that can be instantiated:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/lablet-definitions` | List all definitions |
| `GET` | `/api/lablet-definitions/{id}` | Get definition details |
| `POST` | `/api/lablet-definitions` | Create a new definition |
| `POST` | `/api/lablet-definitions/{id}/sync` | Sync definition from CML |
| `PUT` | `/api/lablet-definitions/{id}` | Update a definition |
| `DELETE` | `/api/lablet-definitions/{id}` | Delete a definition |

#### Example: Create Lablet Definition

```bash
curl -X POST "http://localhost:8000/api/lablet-definitions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "python-networking-lab",
    "version": "1.0.0",
    "description": "Basic Python networking exercises",
    "cml_lab_yaml": "...",
    "resource_requirements": {
      "cpu_cores": 4,
      "memory_gb": 8,
      "storage_gb": 50,
      "node_count": 5
    },
    "lifecycle": {
      "default_duration_minutes": 120,
      "max_duration_minutes": 240,
      "idle_timeout_minutes": 30
    },
    "port_definitions": [
      {
        "name": "console_1",
        "device_name": "router1",
        "console_type": "serial"
      }
    ]
  }'
```

### Lablet Instances

Manage running lab instances:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/lablet-instances` | List all instances |
| `GET` | `/api/lablet-instances/{id}` | Get instance details |
| `POST` | `/api/lablet-instances` | Create a new instance |
| `POST` | `/api/lablet-instances/{id}/start-collection` | Start assessment collection |
| `POST` | `/api/lablet-instances/{id}/start-grading` | Start grading |
| `POST` | `/api/lablet-instances/{id}/extend` | Extend timeslot |
| `POST` | `/api/lablet-instances/{id}/terminate` | Terminate instance |

#### Lablet Instance Lifecycle

```
PENDING → SCHEDULED → INSTANTIATING → RUNNING → COLLECTING → GRADING → STOPPING → STOPPED → ARCHIVED → TERMINATED
                                                                              ↘ TERMINATED (from any state)
```

#### Example: Create Lablet Instance

```bash
curl -X POST "http://localhost:8000/api/lablet-instances" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "definition_id": "def-python-101",
    "owner_id": "student-12345",
    "timeslot_start": "2025-01-20T09:00:00Z",
    "timeslot_end": "2025-01-20T11:00:00Z",
    "reservation_id": "res-ext-12345"
  }'
```

Response:

```json
{
  "id": "inst-abc123",
  "definition_id": "def-python-101",
  "definition_name": "Python Networking Lab",
  "status": "pending",
  "owner_id": "student-12345",
  "timeslot_start": "2025-01-20T09:00:00Z",
  "timeslot_end": "2025-01-20T11:00:00Z",
  "created_at": "2025-01-19T14:30:00Z"
}
```

### Events (Server-Sent Events)

Subscribe to real-time events:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/events/stream` | SSE event stream |

#### Query Parameters

- `worker_ids` - Filter by worker IDs (comma-separated)
- `event_types` - Filter by event types (comma-separated)

#### Example: Subscribe to Events

```javascript
const eventSource = new EventSource('/api/events/stream');

eventSource.addEventListener('worker_status', (event) => {
  const data = JSON.parse(event.data);
  console.log('Worker status changed:', data);
});

eventSource.addEventListener('lablet_instance_status', (event) => {
  const data = JSON.parse(event.data);
  console.log('Instance status changed:', data);
});
```

### Diagnostics

Health and readiness endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/diagnostics/health` | Health check (liveness) |
| `GET` | `/api/diagnostics/ready` | Readiness check |

#### Example: Health Check

```bash
curl -X GET "http://localhost:8000/api/diagnostics/health"
```

Response:

```json
{
  "status": "healthy",
  "timestamp": "2025-01-19T14:30:00Z",
  "version": "1.0.0"
}
```

## Error Handling

The API uses RFC 7807 Problem Details for error responses:

```json
{
  "type": "https://httpstatuses.io/400",
  "title": "Bad Request",
  "status": 400,
  "detail": "Invalid definition_id format",
  "instance": "/api/lablet-instances"
}
```

### Common Error Codes

| Status | Meaning |
|--------|---------|
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Authentication required |
| 403 | Forbidden - Insufficient permissions |
| 404 | Not Found - Resource doesn't exist |
| 409 | Conflict - Resource state conflict |
| 422 | Unprocessable Entity - Validation error |
| 500 | Internal Server Error |
| 503 | Service Unavailable |

## Rate Limiting

The API implements rate limiting per authenticated user:

- **Default limit**: 1000 requests per minute
- **Burst allowance**: 100 requests

Rate limit headers are included in responses:

```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 995
X-RateLimit-Reset: 1642608000
```

## Pagination

List endpoints support pagination:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `limit` | Maximum items per page | 50 |
| `offset` | Number of items to skip | 0 |
| `sort` | Sort field | `created_at` |
| `order` | Sort order (`asc`/`desc`) | `desc` |

#### Example: Paginated Request

```bash
curl "http://localhost:8000/api/lablet-instances?limit=10&offset=20&sort=status&order=asc"
```

## Filtering

List endpoints support filtering by status and other fields:

```bash
# Filter by status
curl "http://localhost:8000/api/lablet-instances?status=running"

# Filter by owner
curl "http://localhost:8000/api/lablet-instances?owner_id=student-12345"

# Include terminated (normally excluded)
curl "http://localhost:8000/api/lablet-instances?include_terminated=true"
```

## Webhooks & CloudEvents

The API publishes CloudEvents for integration:

### Event Types

| Event Type | Trigger |
|------------|---------|
| `io.lablet.instance.created` | Instance created |
| `io.lablet.instance.scheduled` | Instance scheduled to worker |
| `io.lablet.instance.running` | Instance started successfully |
| `io.lablet.instance.collecting` | Collection started |
| `io.lablet.instance.grading` | Grading started |
| `io.lablet.instance.graded` | Grading completed |
| `io.lablet.instance.terminated` | Instance terminated |

### CloudEvent Format

```json
{
  "specversion": "1.0",
  "type": "io.lablet.instance.running",
  "source": "https://lablet-cloud-manager.io",
  "id": "evt-abc123",
  "time": "2025-01-19T14:30:00Z",
  "datacontenttype": "application/json",
  "data": {
    "instance_id": "inst-abc123",
    "worker_id": "worker-xyz789",
    "cml_lab_id": "lab-123456"
  }
}
```

## OpenAPI Specification

The full OpenAPI 3.0 specification is available at:

- **Swagger UI**: `http://localhost:8000/api/docs`
- **ReDoc**: `http://localhost:8000/api/redoc`
- **JSON Spec**: `http://localhost:8000/api/openapi.json`

## SDK & Client Libraries

### Python

```python
import httpx

class LabletClient:
    def __init__(self, base_url: str, token: str):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"}
        )

    async def list_instances(self, status: str = None):
        params = {"status": status} if status else {}
        response = await self.client.get("/lablet-instances", params=params)
        response.raise_for_status()
        return response.json()

    async def create_instance(self, definition_id: str, owner_id: str,
                               timeslot_start: str, timeslot_end: str):
        response = await self.client.post("/lablet-instances", json={
            "definition_id": definition_id,
            "owner_id": owner_id,
            "timeslot_start": timeslot_start,
            "timeslot_end": timeslot_end,
        })
        response.raise_for_status()
        return response.json()
```

### JavaScript/TypeScript

```typescript
class LabletClient {
  constructor(private baseUrl: string, private token: string) {}

  async listInstances(status?: string): Promise<LabletInstance[]> {
    const url = new URL('/lablet-instances', this.baseUrl);
    if (status) url.searchParams.set('status', status);

    const response = await fetch(url.toString(), {
      headers: { 'Authorization': `Bearer ${this.token}` }
    });
    if (!response.ok) throw new Error(response.statusText);
    return response.json();
  }

  async createInstance(data: CreateInstanceRequest): Promise<LabletInstance> {
    const response = await fetch(`${this.baseUrl}/lablet-instances`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error(response.statusText);
    return response.json();
  }
}
```

## Best Practices

### 1. Use Idempotency Keys

For create operations, include an idempotency key to prevent duplicates:

```bash
curl -X POST "http://localhost:8000/api/lablet-instances" \
  -H "Idempotency-Key: req-12345-unique"
```

### 2. Handle Rate Limits

Implement exponential backoff when rate limited:

```python
import time

def make_request_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        response = requests.get(url)
        if response.status_code != 429:
            return response

        retry_after = int(response.headers.get('Retry-After', 60))
        time.sleep(retry_after * (2 ** attempt))

    raise Exception("Max retries exceeded")
```

### 3. Use Webhooks for Async Operations

Instead of polling for status changes, configure webhooks to receive CloudEvents.

### 4. Validate Before Creating

Before creating instances, verify:

- Definition exists and is active
- Worker capacity is available
- Timeslot doesn't conflict with existing instances

## Support

- **Issue Tracker**: GitHub Issues
- **API Status**: Check `/api/diagnostics/health`
- **Documentation**: This guide + OpenAPI spec
