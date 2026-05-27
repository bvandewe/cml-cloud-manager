# Sprint 8: Security, Access Control & Deployment

> **Effort:** 2–3 sessions
> **Dependencies:** Sprint 7 (stable features to secure)
> **Services:** control-plane-api, deployment
> **Status:** ⬜ Not Started

## Objective

Final-mile security hardening, RBAC enforcement, and production deployment packaging. These tasks depend on stable features — changing permissions on evolving APIs wastes effort.

## Tasks

### S8.1 — CRUD Restrictions to Admin Users

**Problem:** All authenticated users can perform destructive operations (delete workers, terminate sessions, wipe labs). Only admins should have these permissions.

**Scope:**

- [ ] Define admin-only endpoints:
  - `DELETE /api/workers/{id}` (drain, terminate)
  - `DELETE /api/definitions/{id}`
  - `DELETE /api/lab-records/{id}`
  - `POST /api/lab-records/dispose-orphaned`
  - Worker scale-up/scale-down
- [ ] Create `require_admin` dependency (FastAPI Depends):
  - Check Keycloak `realm_access.roles` for `lcm-admin` role
  - Return 403 Forbidden if missing
- [ ] Add to relevant controller endpoints
- [ ] Update Keycloak realm config with `lcm-admin` role

**Files:**

- `src/control-plane-api/api/dependencies.py` (add `require_admin`)
- `src/control-plane-api/api/controllers/*.py` (add dependency to admin endpoints)
- `deployment/keycloak/` (realm import JSON update)

**Acceptance Criteria:**

- Non-admin users get 403 on destructive operations
- Admin users can perform all operations
- Keycloak realm has `lcm-admin` role configured
- Tests: 4+ (admin allowed, non-admin blocked, missing role, token without roles)

---

### S8.2 — RBAC Scope Enforcement (Per-Track, Per-Role)

**Problem:** Beyond admin/non-admin, fine-grained permissions are needed — e.g., instructors can manage their own sessions but not others', track-scoped visibility.

**Scope:**

- [ ] Define RBAC scopes:
  - `lcm:sessions:own` — manage own sessions
  - `lcm:sessions:all` — manage all sessions (admin/instructor)
  - `lcm:workers:read` — view workers
  - `lcm:workers:manage` — manage workers (admin only)
  - `lcm:definitions:manage` — manage definitions (admin/instructor)
- [ ] Implement scope-checking middleware or dependency
- [ ] Configure scopes in Keycloak client (resource server authorization)
- [ ] Filter query results by scope (users see only their sessions)

**Files:**

- `src/control-plane-api/api/dependencies.py` (scope checking)
- `src/control-plane-api/api/services/auth.py` (scope extraction)
- `src/control-plane-api/application/queries/` (filter by owner)
- `deployment/keycloak/` (client authorization config)

**Acceptance Criteria:**

- Users with `lcm:sessions:own` see only their sessions
- Users with `lcm:sessions:all` see all sessions
- Scope violations return 403 with clear message
- Tests: 6+ (various scope combinations)

---

### S8.3 — API Rate Limiting

**Problem:** No rate limiting — a misbehaving client or bot can overwhelm the API.

**Scope:**

- [ ] Add rate limiting middleware to API SubApp
- [ ] Configuration:
  - Default: 100 requests/minute per IP
  - Auth endpoints: 10 requests/minute per IP (brute force protection)
  - Admin endpoints: 30 requests/minute per user
- [ ] Return `429 Too Many Requests` with `Retry-After` header
- [ ] Use Redis for distributed rate limiting (already in stack)
- [ ] Bypass for health check endpoints

**Files:**

- `src/control-plane-api/api/middleware/rate_limiter.py` (create)
- `src/control-plane-api/main.py` (register middleware)
- `src/control-plane-api/application/settings.py` (rate limit config)

**Acceptance Criteria:**

- Rate limits enforced per configuration
- 429 response includes `Retry-After` header
- Redis-backed for consistency across restarts
- Health checks exempt
- Tests: 3+ (under limit, at limit, over limit)

---

### S8.4 — SSE Per-User Session Limits

**Problem:** Unlimited SSE connections per user could exhaust server resources.

**Scope:**

- [ ] Track SSE connection count per user in `SSEEventRelay`
- [ ] Limit: max 3 concurrent SSE connections per user
- [ ] On exceeding limit, close oldest connection with reconnect hint
- [ ] Log warning on limit enforcement

**Files:**

- `src/control-plane-api/application/services/sse_event_relay.py`
- `src/control-plane-api/api/controllers/events_controller.py`

**Acceptance Criteria:**

- 4th SSE connection from same user closes oldest
- Client receives close event with reconnect guidance
- Tests: 2+ (within limit, exceeding limit)

---

### S8.5 — User Profile Modal

**Problem:** No self-service user profile — users can't see their role, session history, or preferences.

**Scope:**

- [ ] Add user profile modal accessible from navbar
- [ ] Display: username, email, roles, active sessions count, session history
- [ ] Pull data from Keycloak token claims + CPA queries
- [ ] No edit capability in v1 (read-only profile)

**Files:**

- Frontend: `src/control-plane-api/static/src/components/UserProfileModal.ts` (create)
- Frontend: navbar component (add profile button)
- `src/control-plane-api/api/controllers/` (user info endpoint if needed)

---

### S8.6 — User-Based Lab Filtering by Tag Pattern

**Problem:** Multi-tenant environments need users to see only labs relevant to them (matching `USER_TAG_PATTERN` setting).

**Scope:**

- [ ] Add `USER_TAG_PATTERN` setting (regex pattern, e.g., `user:{username}`)
- [ ] Filter lab/session lists by matching tags when non-admin user
- [ ] Admin users see all resources regardless of tags
- [ ] UI filter toggle: "Show only my resources" (default on for non-admins)

**Files:**

- `src/control-plane-api/application/settings.py` (add setting)
- `src/control-plane-api/application/queries/` (tag-based filtering)
- Frontend: filter toggle in nav views

---

### S8.7 — Helm Chart Deployment

**Problem:** No Kubernetes deployment packaging. Currently Docker Compose only.

**Scope:**

- [ ] Create Helm chart under `deployment/helm/lcm/`:
  - `Chart.yaml`, `values.yaml`
  - Templates: Deployment, Service, Ingress, ConfigMap, Secret
  - One deployment per service (CPA, resource-scheduler, worker-controller, lablet-controller)
  - Dependencies: MongoDB, Redis, Keycloak (optional external)
- [ ] Support configuration via `values.yaml`:
  - Image tags, replicas, resource limits
  - Environment variables passthrough
  - Ingress configuration (nginx/traefik)
- [ ] Add `make helm-template` and `make helm-install` commands

**Files:**

- `deployment/helm/lcm/` (create entire chart)
- `Makefile` (add helm commands)

**Acceptance Criteria:**

- `helm template` renders valid Kubernetes manifests
- `helm install` deploys full stack to local k8s (kind/minikube)
- All services start and pass health checks
- Documented in `deployment/helm/README.md`

---

## Completion Checklist

- [ ] All 7 tasks implemented
- [ ] `make test` passes (all services)
- [ ] `make lint` passes
- [ ] Keycloak realm updated with roles and scopes
- [ ] Helm chart validates and deploys
- [ ] New tests: 20+
- [ ] Commits: one per task
- [ ] Update `IMPLEMENTATION_STATUS.md` → all phases complete
- [ ] Update `CHANGELOG.md` with security and deployment entries
