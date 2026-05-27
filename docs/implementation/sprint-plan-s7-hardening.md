# Sprint 7: Operational Hardening

> **Effort:** 2 sessions
> **Dependencies:** Sprint 5 (grading complete), Sprint 6 (reconciler stable)
> **Services:** All services
> **Status:** ⬜ Not Started

## Objective

Post-MVP hardening focused on reliability, observability, and reducing manual operator intervention. These improvements make the system production-grade.

## Tasks

### S7.1 — Port Allocation Detection from CML API

**Problem:** The system doesn't detect ports already assigned to CML labs on workers. This can cause port conflicts when multiple labs share a worker.

**Scope:**

- [ ] Extend `PortAllocationService` to query CML native API for existing port mappings
- [ ] Query endpoint: `GET /api/v0/labs/{lab_id}/external_connectors` per lab
- [ ] Build port inventory per worker (both lablet-managed and locally-managed labs)
- [ ] Reject port allocations that conflict with existing CML assignments
- [ ] Store detected ports in worker's resource observation data

**Files likely touched:**

- `src/control-plane-api/application/services/port_allocation_service.py`
- `src/worker-controller/integration/services/cml_api_client.py` (add external_connectors query)
- `src/control-plane-api/domain/entities/cml_worker.py` (port inventory)

**Acceptance Criteria:**

- Port allocation checks CML API before assigning
- Conflicts detected and reported with clear error messages
- Tests: 4+ (no conflict, conflict detected, CML API error, worker with mixed labs)

---

### S7.2 — OTel Metrics for Timeslot Management

**Problem:** No observability into timeslot management — operators can't see scheduling latency, approaching sessions, or expiry rates.

**Scope:**

- [ ] Add Prometheus metrics to `TimeslotManagerHostedService`:
  - `lcm_timeslots_approaching_total` (gauge)
  - `lcm_timeslots_expired_total` (counter)
  - `lcm_scheduling_latency_seconds` (histogram, from timeslot_start to actual placement)
  - `lcm_timeslots_active` (gauge, by region)
- [ ] Export via OpenTelemetry SDK (already in stack via OTEL Collector)
- [ ] Add Grafana dashboard panel for timeslot metrics

**Files:**

- `src/resource-scheduler/application/hosted_services/timeslot_manager.py` (add metrics)
- `src/resource-scheduler/main.py` (meter provider setup)
- `deployment/grafana/dashboards/` (timeslot dashboard JSON)

**Acceptance Criteria:**

- Metrics visible in Grafana after `make dev`
- Dashboard shows approaching/expired/active timeslots

---

### S7.3 — Placement Decision Audit Log

**Problem:** No audit trail for why a session was placed on a specific worker. Debugging bad placements requires reading logs.

**Scope:**

- [ ] Create `PlacementDecisionRecord` value object:
  - `session_id`, `worker_id`, `timestamp`
  - `score_breakdown` (dict of factor → score)
  - `candidates_evaluated` (list of worker_id + scores)
  - `decision_reason` (human-readable)
- [ ] Persist to MongoDB collection `placement_decisions`
- [ ] Add query endpoint: `GET /api/admin/placements?session_id=xxx`
- [ ] Retention: keep last 1000 decisions or 30 days

**Files:**

- `src/resource-scheduler/domain/models/placement_decision.py` (create)
- `src/resource-scheduler/integration/repositories/placement_repository.py` (create)
- `src/resource-scheduler/application/services/placement.py` (emit decisions)
- `src/resource-scheduler/api/controllers/admin_controller.py` (query endpoint)

**Acceptance Criteria:**

- Every placement stores decision record
- Admin endpoint returns decision with full score breakdown
- Tests: 3+ (record creation, query, retention)

---

### S7.4 — Fix/Expand Resource-Scheduler UI Dashboard

**Problem:** Scheduler dashboard is minimal — doesn't show scheduling metrics, pending/scheduled queues, or timeslot landscape.

**Scope:**

- [ ] Add dashboard panels:
  - Pending queue: sessions waiting for placement (count, oldest age)
  - Scheduled queue: recently placed sessions (last 10)
  - Timeslot landscape: next-24h histogram of session timeslots
  - Worker utilization: capacity used/available per worker
- [ ] Use SSE for real-time updates (subscribe to scheduler events)
- [ ] Add refresh button for manual reload

**Files:**

- `src/resource-scheduler/static/` (dashboard assets)
- `src/resource-scheduler/ui/` (page templates)
- `src/resource-scheduler/api/controllers/` (data endpoints)

---

### S7.5 — WebSocket for CML Activity Detection

**Problem:** Worker-controller uses HTTP polling to detect CML activity. WebSocket would provide lower latency and reduce API load.

**Scope:**

- [ ] Investigate CML WebSocket API (how CML frontend uses it)
- [ ] Implement WebSocket client in worker-controller
- [ ] Subscribe to lab state change events
- [ ] Fall back to polling if WebSocket not available (older CML versions)
- [ ] Update idle detection to use WebSocket events

**Files:**

- `src/worker-controller/integration/services/cml_api_client.py` (add WebSocket)
- `src/worker-controller/application/hosted_services/` (activity detection)

**Acceptance Criteria:**

- WebSocket connection established and maintained per active worker
- Lab state changes detected within seconds (vs polling interval)
- Graceful fallback to polling on WebSocket failure
- Tests: 3+ (connect, reconnect, fallback)

---

### S7.6 — Auto-Detect Resource Requirements from cml.yml

**Problem:** Users manually specify CPU, memory, storage requirements when creating sessions. These values often don't match the actual topology requirements, leading to undersized placements.

**Scope:**

- [ ] Parse `cml.yml` topology to extract:
  - Node count × node_definition resource profiles
  - Total CPU, memory, storage requirements
  - Nested virtualization requirement (from node types)
- [ ] Create `TopologyAnalyzer` service that calculates resource requirements
- [ ] Pre-populate "Create Session" form with calculated requirements
- [ ] Allow manual override with warning if below calculated minimum

**Files:**

- `src/control-plane-api/application/services/topology_analyzer.py` (create)
- `src/control-plane-api/api/controllers/` (analysis endpoint)
- Frontend: Create Session modal (auto-populate)

**Acceptance Criteria:**

- cml.yml parsed correctly for standard node definitions
- Calculated requirements shown as defaults in creation form
- Warning shown if user overrides below minimum
- Tests: 5+ (various topology sizes, unknown node defs, edge cases)

---

## Completion Checklist

- [ ] All 6 tasks implemented
- [ ] `make test` passes (all services)
- [ ] `make lint` passes
- [ ] Grafana dashboard updated
- [ ] New tests: 20+
- [ ] Commits: one per task
