# Security Review - Lablet Cloud Manager

## Overview

This document provides a security review of the Lablet Cloud Manager control plane API,
covering authentication, authorization, input validation, and security best practices.

## Authentication Architecture

### Dual Authentication Strategy

The system implements two authentication mechanisms:

1. **Cookie-Based (BFF Pattern)** - Primary for UI
   - httpOnly cookies prevent XSS token theft
   - SameSite attribute protects against CSRF
   - Server-side session storage (Redis/in-memory)

2. **Bearer Token (JWT)** - API clients
   - Standard Authorization header
   - Token validation via Keycloak introspection
   - Short-lived access tokens with refresh capability

### Authentication Flow

```
┌─────────────┐      ┌───────────────┐      ┌──────────────┐
│   Browser   │──1──▶│  /api/auth/   │──2──▶│   Keycloak   │
│             │◀─4───│   login       │◀─3───│              │
└─────────────┘      └───────────────┘      └──────────────┘
       │
       │ Cookie: session_id (httpOnly)
       ▼
┌─────────────┐      ┌───────────────┐
│  Protected  │──────│ Validate      │
│  Endpoints  │      │ Session       │
└─────────────┘      └───────────────┘
```

### Session Management

| Setting | Value | Rationale |
|---------|-------|-----------|
| Session Timeout | 30 minutes | Balance usability/security |
| Cookie Secure | true (prod) | HTTPS only in production |
| Cookie HttpOnly | true | Prevent JS access |
| Cookie SameSite | Lax | Allow top-level navigation |

## Authorization (RBAC)

### Role Hierarchy

```
admin
  └── operator
        └── user
              └── viewer
```

### Role Permissions Matrix

| Permission | Viewer | User | Operator | Admin |
|------------|--------|------|----------|-------|
| List Workers | ✓ | ✓ | ✓ | ✓ |
| View Worker Details | ✓ | ✓ | ✓ | ✓ |
| Start/Stop Workers | ✗ | ✗ | ✓ | ✓ |
| Create/Delete Workers | ✗ | ✗ | ✓ | ✓ |
| List Definitions | ✓ | ✓ | ✓ | ✓ |
| Create Definitions | ✗ | ✗ | ✓ | ✓ |
| List Own Instances | ✓ | ✓ | ✓ | ✓ |
| List All Instances | ✗ | ✗ | ✓ | ✓ |
| Create Instances | ✗ | ✓ | ✓ | ✓ |
| Manage System Settings | ✗ | ✗ | ✗ | ✓ |

### Authorization Enforcement Points

**Controller Level** (Authentication):

```python
# api/controllers/workers_controller.py
@get("/")
async def list_workers(
    self,
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> list[WorkerDto]:
    user = await self._get_authenticated_user(credentials)
    # User is authenticated, proceed
```

**Handler Level** (Authorization):

```python
# application/commands/start_worker_command.py
async def handle_async(self, command: StartWorkerCommand) -> OperationResult:
    # Check role-based permission
    if not self._has_role(command.user_context, "operator"):
        return self.forbidden("Operator role required to start workers")

    # Check resource-level permission
    worker = await self._repository.get_by_id_async(command.worker_id)
    if not self._can_manage_worker(command.user_context, worker):
        return self.forbidden("Cannot manage workers in this region")
```

## Input Validation

### Validation Layers

1. **FastAPI/Pydantic** - Type validation, format checking
2. **Domain Validation** - Business rule enforcement
3. **Database Constraints** - Final safety net

### Pydantic Models (API Layer)

```python
# api/models/create_lablet_instance_request.py
class CreateLabletInstanceRequest(BaseModel):
    definition_id: str = Field(..., min_length=3, max_length=100)
    owner_id: str = Field(..., min_length=1, max_length=100)
    timeslot_start: datetime
    timeslot_end: datetime
    reservation_id: str | None = Field(None, max_length=100)

    @validator('timeslot_end')
    def timeslot_end_after_start(cls, v, values):
        if 'timeslot_start' in values and v <= values['timeslot_start']:
            raise ValueError('timeslot_end must be after timeslot_start')
        return v

    @validator('definition_id')
    def valid_definition_id_format(cls, v):
        if not v.replace('-', '').replace('_', '').isalnum():
            raise ValueError('Invalid definition_id format')
        return v
```

### Domain Validation (Business Rules)

```python
# domain/entities/lablet_instance.py
def schedule(self, worker_id: str, timeslot: Timeslot, ports: list[AllocatedPort]):
    # Validate current state
    if self.state.status != LabletInstanceStatus.PENDING:
        raise InvalidStateTransitionError(
            current_status=self.state.status,
            target_status=LabletInstanceStatus.SCHEDULED
        )

    # Validate timeslot
    if timeslot.start >= timeslot.end:
        raise ValueError("Invalid timeslot: start must be before end")

    if timeslot.start < datetime.now(tz=timezone.utc):
        raise ValueError("Cannot schedule in the past")
```

### Common Injection Prevention

| Attack Vector | Prevention |
|---------------|------------|
| SQL Injection | Not applicable (MongoDB) |
| NoSQL Injection | Pydantic validation, Motor parameterization |
| Command Injection | No shell execution, validated parameters |
| Path Traversal | Validated file paths, no user-controlled paths |
| XSS | HTTPOnly cookies, Content-Type validation |

## Secrets Management

### Environment Variables

Sensitive configuration via environment variables:

```bash
# Never in code or version control
KEYCLOAK_CLIENT_SECRET
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
MONGODB_URI  # if contains credentials
REDIS_URL    # if contains credentials
```

### Secret Scanning

Pre-commit hooks include `detect-secrets`:

```yaml
# .pre-commit-config.yaml
- repo: https://github.com/Yelp/detect-secrets
  rev: v1.4.0
  hooks:
    - id: detect-secrets
```

### AWS Credential Rotation

AWS credentials should be rotated using IAM roles when possible:

- **EC2 Instance Role**: For workers running on EC2
- **IAM Access Keys**: For development, rotated every 90 days
- **Session Tokens**: For temporary access

## API Security Headers

### Response Headers

```python
# Middleware configuration
app.add_middleware(
    ContentSecurityPolicy,
    policy="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
)

# Security headers added to responses
{
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'"
}
```

## Rate Limiting

### Configuration

```python
# Per-user rate limiting
RATE_LIMIT_REQUESTS_PER_MINUTE = 1000
RATE_LIMIT_BURST = 100

# Per-endpoint limits (more restrictive)
RATE_LIMIT_AUTH_REQUESTS = 10  # per minute
RATE_LIMIT_CREATE_REQUESTS = 60  # per minute
```

### Implementation

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/auth/login")
@limiter.limit("10/minute")
async def login():
    ...
```

## Audit Logging

### Events Logged

| Event Type | Data Captured |
|------------|---------------|
| Authentication | user_id, timestamp, IP, success/failure |
| Authorization Failure | user_id, resource, action, reason |
| Resource Creation | user_id, resource_type, resource_id |
| Resource Deletion | user_id, resource_type, resource_id |
| Configuration Change | user_id, setting, old_value, new_value |
| Security Event | type, details, severity |

### Log Format

```json
{
  "timestamp": "2025-01-19T14:30:00Z",
  "level": "INFO",
  "event_type": "security.authentication",
  "user_id": "user-12345",
  "action": "login",
  "result": "success",
  "ip_address": "10.0.1.100",
  "trace_id": "abc123def456"
}
```

## Vulnerability Checklist

### OWASP Top 10 Coverage

| # | Vulnerability | Status | Mitigation |
|---|---------------|--------|------------|
| A01 | Broken Access Control | ✓ | RBAC in handlers, resource-level checks |
| A02 | Cryptographic Failures | ✓ | HTTPS, secure cookies, no sensitive data in logs |
| A03 | Injection | ✓ | Pydantic validation, parameterized queries |
| A04 | Insecure Design | ✓ | Defense in depth, principle of least privilege |
| A05 | Security Misconfiguration | ✓ | Security headers, minimal permissions |
| A06 | Vulnerable Components | ⚠️ | Dependency scanning needed |
| A07 | Auth Failures | ✓ | Keycloak, session management, rate limiting |
| A08 | Software/Data Integrity | ✓ | Signed deployments, immutable infrastructure |
| A09 | Logging/Monitoring | ✓ | Structured logging, audit trails, OTEL |
| A10 | SSRF | ✓ | No user-controlled URLs, whitelist validation |

### Dependency Scanning

```bash
# Check for known vulnerabilities
poetry export -f requirements.txt | safety check --stdin

# Update dependencies
poetry update

# Audit npm dependencies (UI)
cd ui && npm audit
```

## Security Testing

### Automated Security Tests

```python
# tests/security/test_authentication.py
class TestAuthenticationSecurity:
    async def test_unauthenticated_access_rejected(self, client):
        response = await client.get("/api/workers")
        assert response.status_code == 401

    async def test_invalid_token_rejected(self, client):
        response = await client.get(
            "/api/workers",
            headers={"Authorization": "Bearer invalid_token"}
        )
        assert response.status_code == 401

    async def test_expired_token_rejected(self, client, expired_token):
        response = await client.get(
            "/api/workers",
            headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert response.status_code == 401

# tests/security/test_authorization.py
class TestAuthorizationSecurity:
    async def test_user_cannot_start_worker(self, client, user_token):
        response = await client.post(
            "/api/workers/worker-123/start",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert response.status_code == 403

    async def test_operator_can_start_worker(self, client, operator_token):
        response = await client.post(
            "/api/workers/worker-123/start",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code in [200, 202]
```

### Penetration Testing Recommendations

1. **Authentication Testing**
   - Brute force protection
   - Session fixation
   - Token leakage

2. **Authorization Testing**
   - Privilege escalation
   - IDOR (Insecure Direct Object References)
   - Missing function level access control

3. **API Security Testing**
   - Rate limiting bypass
   - Parameter tampering
   - Mass assignment

## Remediation Priorities

### Critical (Immediate)

- [ ] Enable dependency vulnerability scanning in CI/CD
- [ ] Implement secret rotation for AWS credentials

### High (Within 1 Week)

- [ ] Add security headers middleware
- [ ] Implement comprehensive audit logging
- [ ] Add rate limiting to auth endpoints

### Medium (Within 1 Month)

- [ ] Conduct penetration testing
- [ ] Implement API versioning for security patches
- [ ] Add security-focused integration tests

### Low (Ongoing)

- [ ] Regular dependency updates
- [ ] Security training for developers
- [ ] Periodic security review

## Compliance Considerations

### Data Handling

- User data (owner_id) is pseudonymized
- No PII stored directly in lablet instances
- Audit logs retained for 90 days

### Access Controls

- Principle of least privilege enforced
- Role separation (viewer < user < operator < admin)
- All access logged and auditable

## Appendix: Security Configuration

### Keycloak Client Configuration

```json
{
  "clientId": "lablet-cloud-manager",
  "protocol": "openid-connect",
  "publicClient": true,
  "standardFlowEnabled": true,
  "directAccessGrantsEnabled": false,
  "implicitFlowEnabled": false,
  "authorizationServicesEnabled": true,
  "redirectUris": ["https://lablet.example.com/*"],
  "webOrigins": ["https://lablet.example.com"]
}
```

### Recommended Production Settings

```yaml
# Environment variables for production
SECURE_COOKIES: "true"
SESSION_TIMEOUT_MINUTES: 30
RATE_LIMIT_ENABLED: "true"
CORS_ALLOWED_ORIGINS: "https://lablet.example.com"
LOG_LEVEL: "INFO"
AUDIT_LOG_ENABLED: "true"
```
