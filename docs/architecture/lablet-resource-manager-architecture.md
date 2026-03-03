# Lablet Resource Manager - Architecture Design

| Attribute | Value |
|-----------|-------|
| **Document Version** | 0.5.0 |
| **Status** | Draft |
| **Created** | 2026-01-15 |
| **Last Updated** | 2026-02-18 |
| **Author** | Architecture Team |
| **Related** | [Requirements Specification](../specs/lablet-resource-manager-requirements.md), [ADRs](./adr/README.md) |

---

## 1. Architecture Overview

### 1.1 Design Principles

| Principle | Application |
|-----------|-------------|
| **Declarative over Imperative** | Users declare desired state; system reconciles |
| **Separation of Concerns** | API, Scheduling, Control each have distinct responsibilities |
| **Event-Driven Integration** | CloudEvents for async external communication |
| **API-Centric State Management** | Single source of truth via Control Plane API |
| **Provider Abstraction** | SPI pattern for cloud provider independence |

### 1.2 High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL CLIENTS                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  ┌───────────────────┐   │
│  │ REST API │  │ UI (SPA) │  │ Assessment Svc   │  │ Audit/Compliance  │   │
│  │ Clients  │  │          │  │ (CloudEvents)    │  │ (CloudEvents)     │   │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  └─────────┬─────────┘   │
└───────┼─────────────┼─────────────────┼──────────────────────┼─────────────┘
        │             │                 │                      │
        ▼             ▼                 ▼                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         CML CLOUD MANAGER SYSTEM                           │
│                                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      CONTROL PLANE API                              │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────────┐  │   │
│  │  │ Definition  │ │ Session     │ │ Worker      │ │ Reservation   │  │   │
│  │  │ Endpoints   │ │ Endpoints   │ │ Endpoints   │ │ Endpoints     │  │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └───────────────┘  │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────────┐  │   │
│  │  │ SSE Stream  │ │ Admission   │ │ Rate        │ │ Auth/RBAC     │  │   │
│  │  │             │ │ Control     │ │ Limiting    │ │               │  │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └───────────────┘  │   │
│  └───────────────────────────┬─────────────────────────────────────────┘   │
│                              │                                             │
│                              ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      DUAL STORAGE ARCHITECTURE                      │   │
│  │                                                                     │   │
│  │  ┌───────────────────────────┐   ┌────────────────────────────────┐ │   │
│  │  │      STATE STORE (etcd)   │   │     SPEC STORE (MongoDB)       │ │   │
│  │  │                           │   │                                │ │   │
│  │  │  • Instance states        │   │  • LabletDefinitions (full)    │ │   │
│  │  │  • Worker states          │   │  • WorkerTemplates (full)      │ │   │
│  │  │  • Port allocations       │   │  • Audit events (CloudEvents)  │ │   │
│  │  │  • Leader election keys   │   │  • Complex aggregates          │ │   │
│  │  │  • Watch subscriptions    │   │  • Historical data             │ │   │
│  │  │                           │   │                                │ │   │
│  │  │  [Native Watch Mechanism] │   │  [Rich Query Capabilities]     │ │   │
│  │  └─────────────┬─────────────┘   └────────────────────────────────┘ │   │
│  │                │                                                    │   │
│  │                │ Watch Events                                       │   │
│  │                ▼                                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                             │
│         ┌────────────────────┼────────────────────┐                        │
│         ▼                    ▼                    ▼                        │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐                 │
│  │  RESOURCE   │      │   LABLET    │      │   WORKER    │                 │
│  │  SCHEDULER  │      │ CONTROLLER  │      │ CONTROLLER  │                 │
│  │             │      │             │      │             │                 │
│  │ • Watch for │      │ • Watch for │      │ • Watch for │                 │
│  │   PENDING   │      │   SCHEDULED │      │   Workers   │                 │
│  │ • Placement │      │ • Reconcile │      │ • Reconcile │                 │
│  │ • Queue Mgmt│      │   Instances │      │   Workers   │                 │
│  │ • Timeslots │      │   vs Labs   │      │   vs EC2    │                 │
│  │             │      │ • DRAINING  │      │ • License   │                 │
│  │ [Leader     │      │ [Leader     │      │ [Leader     │                 │
│  │  Election]  │      │  Election]  │      │  Election]  │                 │
│  └─────────────┘      └─────────────┘      └─────────────┘                 │
│         │                    │                    │                        │
│         │                    │                    │                        │
│         │             ┌──────┴──────┐      ┌──────┴──────┐                 │
│         │             │ CML LABS    │      │ CLOUD       │                 │
│         │             │ SPI         │      │ PROVIDER    │                 │
│         │             │             │      │ SPI         │                 │
│         │             │ • Labs API  │      │             │                 │
│         │             │ • Nodes API │      │ • AWS EC2   │                 │
│         │             │ • Links API │      │ • CloudWatch│                 │
│         │             │ • Interfaces│      │ • CML System│                 │
│         │             └─────────────┘      └─────────────┘                 │
│         │                    │                    │                        │
│         └────────────────────┼────────────────────┘                        │
│                              ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    CLOUDEVENTS BUS                                  │   │
│  │                   (External Event Sink)                             │   │
│  │                                                                     │   │
│  │  [Persists events for audit/analytics - NOT primary write model]    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                             │
│                              ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    CML WORKERS (Data Plane)                         │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │   │
│  │  │ Worker 1    │  │ Worker 2    │  │ Worker N    │                  │   │
│  │  │ (Personal)  │  │ (Enterprise)│  │ (DRAINING)  │                  │   │
│  │  │             │  │             │  │             │                  │   │
│  │  │ ┌─────────┐ │  │ ┌─────────┐ │  │ ┌─────────┐ │                  │   │
│  │  │ │Session 1│ │  │ │Session 3│ │  │ │Session 5│ │ ◀─ completing    │   │
│  │  │ └─────────┘ │  │ ├─────────┤ │  │ └─────────┘ │                  │   │
│  │  │ ┌─────────┐ │  │ │Session 4│ │  │             │ ◀─ no new        │   │
│  │  │ │Session 2│ │  │ └─────────┘ │  │             │    assignments   │   │
│  │  │ └─────────┘ │  │             │  │             │                  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL SERVICES                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │ Artifact Storage │  │ Keycloak         │  │ OTEL Collector           │  │
│  │ (S3/MinIO)       │  │ (Auth)           │  │ (Traces/Metrics/Logs)    │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Storage Architecture Decision

> **See [ADR-005: Dual State Store Architecture](./adr/ADR-005-state-store-architecture.md) for full rationale.**

| Store | Purpose | Data Types | Key Feature |
|-------|---------|------------|-------------|
| **etcd** | State coordination | Instance states, worker states, port allocations, leader keys | Native watch mechanism |
| **MongoDB** | Spec/document storage | LabletDefinitions, WorkerTemplates, Audit events | Rich queries, schema flexibility |
| **Redis** | UI Session storage | User sessions (httpOnly cookies) | Fast, ephemeral |

**Why not just MongoDB?**

- MongoDB Change Streams have limitations (cursor timeout, resumption complexity)
- No built-in leader election primitives
- etcd's watch mechanism is more reliable for reactive state propagation

**Redis clarification:**

- Redis stores **UI session data** (user authentication state via httpOnly cookies)
- NOT used for Resource Scheduler/Controller coordination (that's etcd)
- Could migrate to etcd, but Redis is simpler for session TTL management

---

## 2. Component Design

### 2.1 Control Plane API

**Responsibility:** Central gateway for all state operations, authentication, and real-time updates.

**Key Design Decision:** The Control Plane API is the **ONLY** component that writes to MongoDB and etcd. All other services (Resource Scheduler, Lablet Controller, Worker Controller) read state and request mutations via the API.

```
┌─────────────────────────────────────────────────────────────────┐
│                     CONTROL PLANE API                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌────────────────┐    ┌────────────────┐    ┌────────────────┐ │
│  │   REST API     │    │   Event API    │    │   SSE Stream   │ │
│  │   Endpoints    │    │   (Webhooks)   │    │   (Real-time)  │ │
│  └───────┬────────┘    └───────┬────────┘    └───────┬────────┘ │
│          │                     │                     │          │
│          ▼                     ▼                     ▼          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    ADMISSION CONTROL                      │  │
│  │  • Authentication (Keycloak JWT)                          │  │
│  │  • Authorization (RBAC)                                   │  │
│  │  • Rate Limiting                                          │  │
│  │  • Request Validation                                     │  │
│  └───────────────────────────────────────────────────────────┘  │
│          │                     │                     │          │
│          ▼                     ▼                     ▼          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    COMMAND/QUERY BUS                      │  │
│  │                    (Neuroglia Mediator)                   │  │
│  └───────────────────────────────────────────────────────────┘  │
│          │                                                      │
│          ▼                                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    DOMAIN LAYER                           │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐   │  │
│  │  │ Lablet     │  │ Lablet     │  │ CMLWorker          │   │  │
│  │  │ Definition │  │ Session    │  │ (Extended)         │   │  │
│  │  │ Aggregate  │  │ Aggregate  │  │ Aggregate          │   │  │
│  │  │            │  │ + UserSess │  │                    │   │  │
│  │  │            │  │ + GradeSes │  │                    │   │  │
│  │  │            │  │ + ScoreRep │  │                    │   │  │
│  │  └────────────┘  └────────────┘  └────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────┘  │
│          │                                                      │
│          ▼                                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    EVENT PUBLISHER                        │  │
│  │                    (CloudEvents)                          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.1.1 API Endpoints

**LabletDefinition Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/definitions` | Create/register new definition |
| GET | `/api/v1/definitions` | List all definitions |
| GET | `/api/v1/definitions/{id}` | Get definition by ID |
| GET | `/api/v1/definitions/{id}/versions` | List all versions |
| GET | `/api/v1/definitions/{id}/versions/{version}` | Get specific version |
| POST | `/api/v1/definitions/{id}/sync` | Trigger artifact sync |
| DELETE | `/api/v1/definitions/{id}` | Soft-delete definition |

**LabletSession Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/sessions` | Create session (reservation) |
| GET | `/api/v1/sessions` | List sessions (with filters) |
| GET | `/api/v1/sessions/{id}` | Get session details |
| POST | `/api/v1/sessions/{id}/start` | Start stopped session |
| POST | `/api/v1/sessions/{id}/stop` | Stop running session |
| POST | `/api/v1/sessions/{id}/collect` | Trigger collection |
| DELETE | `/api/v1/sessions/{id}` | Terminate session |

**UserSession Endpoints (LDS Integration):**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/sessions/{id}/user-session` | Get UserSession details |
| GET | `/api/v1/sessions/{id}/user-session/login-url` | Get LDS IFRAME login URL |

**GradingSession Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/sessions/{id}/grading-session` | Get GradingSession details |
| POST | `/api/v1/sessions/{id}/grade` | Trigger grading |

**ScoreReport Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/sessions/{id}/score-report` | Get score report |
| GET | `/api/v1/score-reports` | List/query score reports (reporting) |

**Worker Endpoints (Extended):**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/workers/{id}/capacity` | Get capacity details |
| GET | `/api/v1/workers/{id}/instances` | List instances on worker |
| GET | `/api/v1/workers/{id}/ports` | Get port allocations |

**Internal Endpoints (for Controllers):**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/internal/sessions/{id}/schedule` | Assign worker to session |
| POST | `/api/internal/sessions/{id}/allocate-ports` | Allocate ports |
| POST | `/api/internal/sessions/{id}/transition` | Transition state |
| POST | `/api/internal/sessions/{id}/user-session` | Create UserSession (LDS provisioned) |
| PUT | `/api/internal/sessions/{id}/user-session/status` | Update UserSession status |
| POST | `/api/internal/sessions/{id}/grading-session` | Create GradingSession |
| PUT | `/api/internal/sessions/{id}/grading-session/status` | Update GradingSession status |
| POST | `/api/internal/sessions/{id}/score-report` | Store ScoreReport |
| POST | `/api/internal/workers/scale-up` | Request new worker |
| POST | `/api/internal/workers/{id}/scale-down` | Stop/terminate worker |

---

### 2.2 Resource Resource Scheduler

**Responsibility:** Make placement decisions and manage the scheduling queue.

**Key Design Decision:** Stateless service that reads state via etcd watches and writes decisions via Control Plane API. Uses leader election for HA (see [ADR-006](./adr/ADR-006-resource-scheduler-ha-coordination.md)).

```
┌─────────────────────────────────────────────────────────────────┐
│                  RESOURCE SCHEDULER SERVICE                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  LEADER ELECTION (etcd)                   │  │
│  │     Only leader runs scheduling loop; standbys watch      │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            │                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    SCHEDULING LOOP                        │  │
│  │   Triggered by: etcd watch + Periodic reconciliation (30s)│  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            │                                    │
│            ┌───────────────┼───────────────┐                    │
│            ▼               ▼               ▼                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ PENDING      │  │ SCHEDULED    │  │ APPROACHING  │           │
│  │ QUEUE        │  │ QUEUE        │  │ TIMESLOTS    │           │
│  │ PROCESSOR    │  │ MONITOR      │  │ MONITOR      │           │
│  │              │  │              │  │              │           │
│  │ [etcd watch: │  │ [Verify      │  │ [35min lead  │           │
│  │  state=PEND] │  │  assignments]│  │  time check] │           │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘           │
│         │                 │                 │                   │
│         ▼                 ▼                 ▼                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    PLACEMENT ENGINE                       │  │
│  │                                                           │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │ 1. Filter: License Affinity                         │  │  │
│  │  │ 2. Filter: Resource Requirements                    │  │  │
│  │  │ 3. Filter: AMI Requirements                         │  │  │
│  │  │ 4. Filter: Available Capacity                       │  │  │
│  │  │ 5. Filter: Available Ports                          │  │  │
│  │  │ 6. Filter: NOT DRAINING (exclude draining workers)  │  │  │
│  │  │ 7. Score: Bin-Packing (prefer fuller workers)       │  │  │
│  │  │ 8. Select: Highest scoring worker                   │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │                                                           │  │
│  │  Outcome:                                                 │  │
│  │  • Worker Found → Call API to schedule instance           │  │
│  │  • No Worker → Signal Lablet Controller for scale-up      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.2.0 Resource Scheduler High Availability

> **See [ADR-006: Resource Scheduler HA Coordination](./adr/ADR-006-resource-scheduler-ha-coordination.md) for full details.**

**How multiple resource schedulers coordinate:**

```python
class ResourceSchedulerService:
    """Resource Scheduler with leader election."""

    def __init__(self, etcd_client, api_client, instance_id: str):
        self.etcd = etcd_client
        self.api = api_client
        self.instance_id = instance_id
        self.leader_key = "/lcm/resource-scheduler/leader"
        self.is_leader = False

    async def start_async(self):
        """Start the resource scheduler service."""
        # Attempt to become leader
        self.is_leader = await self._campaign_for_leadership()

        if self.is_leader:
            # Start leadership maintenance and scheduling loop
            asyncio.create_task(self._maintain_leadership())
            asyncio.create_task(self._run_scheduling_loop())
        else:
            # Watch for leader changes
            asyncio.create_task(self._watch_leader())

    async def _campaign_for_leadership(self) -> bool:
        """Try to become leader via etcd lease."""
        lease = await self.etcd.lease(ttl=15)  # 15 second lease
        try:
            await self.etcd.put(
                self.leader_key,
                self.instance_id,
                lease=lease,
                prev_kv=False,
                create_only=True  # Only succeeds if key doesn't exist
            )
            self._lease = lease
            return True
        except KeyExistsError:
            return False

    async def _watch_leader(self):
        """Watch leader key, campaign when leader fails."""
        async for event in self.etcd.watch(self.leader_key):
            if event.type == EventType.DELETE:
                # Leader lost, try to take over
                self.is_leader = await self._campaign_for_leadership()
                if self.is_leader:
                    asyncio.create_task(self._maintain_leadership())
                    asyncio.create_task(self._run_scheduling_loop())
```

**Failover timeline:**

- Leader crashes → Lease expires in ~15 seconds → Standby detects via watch → Standby campaigns and wins → New leader starts scheduling

**Total failover time: ~15-20 seconds**

#### 2.2.1 Scheduling Algorithm

```python
def schedule_session(session: LabletSession) -> SchedulingDecision:
    """
    Placement algorithm for LabletSession.
    Returns assigned worker or scale-up request.
    """
    definition = get_definition(session.definition_id)

    # Phase 1: Filter eligible workers
    candidates = []
    for worker in get_active_workers():
        if not matches_license_affinity(worker, definition):
            continue
        if not meets_resource_requirements(worker, definition):
            continue
        if not matches_ami_requirements(worker, definition):
            continue
        if not has_available_capacity(worker, definition):
            continue
        if not has_available_ports(worker, definition.port_count):
            continue
        candidates.append(worker)

    # Phase 2: No candidates - request scale-up
    if not candidates:
        return SchedulingDecision(
            action=ScaleUpRequired,
            worker_template=select_template(definition),
            reason="No worker with sufficient capacity"
        )

    # Phase 3: Score candidates (bin-packing)
    scored = []
    for worker in candidates:
        score = calculate_utilization_score(worker)  # Higher = fuller
        scored.append((worker, score))

    # Phase 4: Select best worker
    scored.sort(key=lambda x: x[1], reverse=True)
    selected_worker = scored[0][0]

    return SchedulingDecision(
        action=AssignWorker,
        worker_id=selected_worker.id,
        reason=f"Best fit with {scored[0][1]:.2f} utilization"
    )
```

#### 2.2.2 Timeslot Management

```
Timeline:
    NOW                      TIMESLOT_START            TIMESLOT_END
     │                            │                         │
     ▼                            ▼                         ▼
─────┼────────────────────────────┼─────────────────────────┼─────▶
     │                            │                         │
     │◄──── LEAD_TIME ────────────┤                         │
     │      (15 min buffer)       │                         │
     │                            │                         │
     │  ┌─────────────────────┐   │  ┌──────────────────┐  │
     │  │ INSTANTIATION       │   │  │ RUNNING          │  │
     │  │ (Import + Start)    │   │  │ (User Session)   │  │
     │  └─────────────────────┘   │  └──────────────────┘  │
```

The resource scheduler monitors approaching timeslots and triggers instantiation with `LEAD_TIME` buffer (default: 15 minutes to account for worker startup).

---

### 2.3 Lablet Controller (`src/lablet-controller/`)

**Responsibility:** LabletSession reconciliation loop - reconciles desired session state (spec) against actual CML lab, LDS, and GradingEngine state.

**Domain:** Application-layer workload management. Talks exclusively to **CML Labs SPI** (labs/nodes/interfaces/links API), **LDS SPI** (sessions/devices), and **GradingEngine SPI** (sessions/parts/pods).

**Key Design Decision:** Stateless service operating on a periodic reconciliation cycle. Detects drift between desired LabletSession state and actual external system states. All mutations go through Control Plane API (ADR-001). **Only service that communicates with LDS, GradingEngine, and CML Labs API.** Receives CloudEvents from LDS and GradingEngine via Neuroglia CloudEventIngestor and proxies state updates to CPA.

```
┌─────────────────────────────────────────────────────────────────┐
│                     LABLET CONTROLLER                           │
│               (Application Layer - Workloads)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                  LEADER ELECTION (etcd)                   │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            │                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                 RECONCILIATION LOOP                       │  │
│  │                 (Every 30 seconds)                        │  │
│  │                                                           │  │
│  │     For each LabletSession:                               │  │
│  │       SPEC (desired) ←→ OBSERVE (actual) → ACT            │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            │                                    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                 CML LABS SPI (Service Provider Interface) │  │
│  │                                                           │  │
│  │  ┌──────────────────────────────────────────────────────┐ │  │
│  │  │  /api/v0/labs                                        │ │  │
│  │  │  • Create lab (import topology)                      │ │  │
│  │  │  • Start/stop/wipe lab                               │ │  │
│  │  │  • Get lab state                                     │ │  │
│  │  │  • Delete lab                                        │ │  │
│  │  └──────────────────────────────────────────────────────┘ │  │
│  │  ┌──────────────────────────────────────────────────────┐ │  │
│  │  │  /api/v0/labs/{id}/nodes                             │ │  │
│  │  │  • List nodes in lab                                 │ │  │
│  │  │  • Get node state                                    │ │  │
│  │  │  • Extract node configs                              │ │  │
│  │  └──────────────────────────────────────────────────────┘ │  │
│  │  ┌──────────────────────────────────────────────────────┐ │  │
│  │  │  /api/v0/labs/{id}/interfaces                        │ │  │
│  │  │  • Get console ports                                 │ │  │
│  │  │  • Map external ports                                │ │  │
│  │  └──────────────────────────────────────────────────────┘ │  │
│  │  ┌──────────────────────────────────────────────────────┐ │  │
│  │  │  /api/v0/labs/{id}/links                             │ │  │
│  │  │  • Topology connectivity                             │ │  │
│  │  └──────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            │                                    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                   CONTROL PLANE API                       │  │
│  │         (All mutations via API - ADR-001)                 │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.3.0 Lablet Controller Reconciliation Pattern

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                LABLET CONTROLLER - RECONCILIATION PATTERN                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐    │
│   │       SPEC       │     │     OBSERVE      │     │       ACT        │    │
│   │   (Desired)      │     │    (Actual)      │     │   (Reconcile)    │    │
│   └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘    │
│            │                        │                        │              │
│            ▼                        ▼                        ▼              │
│   ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐    │
│   │ LabletSession    │     │ CML Lab State    │     │ • Import lab     │    │
│   │ • state=RUNNING  │     │ • state=DEFINED  │     │ • Start nodes    │    │
│   │ • worker_id=W1   │ ←→  │ • nodes stopped  │  →  │ • Allocate ports │    │
│   │ • ports={...}    │     │ • no ports       │     │ • Update state   │    │
│   └──────────────────┘     └──────────────────┘     └──────────────────┘    │
│                                                                             │
│   Source: MongoDB         Source: CML Labs API       Target: Both           │
│   (via Control Plane)     (direct observation)       (via Control Plane)    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Reconciliation Examples:**

| Desired (Spec) | Actual (Observed) | Action |
|----------------|-------------------|--------|
| Session state=RUNNING | Lab not imported | Import topology, start lab |
| Session state=RUNNING | Lab state=DEFINED | Start lab nodes |
| Session state=RUNNING | Lab state=STARTED | No action (converged) |
| Session state=STOPPED | Lab state=STARTED | Stop lab nodes |
| Session state=TERMINATED | Lab exists | Wipe and delete lab |

#### 2.3.1 Scale-Up Logic

> **See [ADR-008: Worker Draining State](./adr/ADR-008-worker-draining-state.md) for draining behavior.**

**Critical Timing Considerations:**

- **Worker bootup time**: 15-20 minutes (EC2 m5zn.metal + CML initialization)
- **Lablet instantiation time**: Up to 15 minutes (lab import + node startup)
- **Total lead time**: Up to 35 minutes before scheduled timeslot

```python
# Configurable timing parameters
WORKER_BOOTUP_DELAY_MINUTES = 20      # m5zn.metal EC2 + CML startup
LABLET_INSTANTIATION_DELAY_MINUTES = 15  # Lab import + node startup
TOTAL_LEAD_TIME_MINUTES = WORKER_BOOTUP_DELAY_MINUTES + LABLET_INSTANTIATION_DELAY_MINUTES


def check_scale_up_needed() -> list[ScaleUpAction]:
    """
    Determine if new workers are needed.
    Called by Lablet Controller reconciliation loop.

    Must account for:
    1. Worker bootup delay (15-20 min for m5zn.metal)
    2. Lablet instantiation delay (up to 15 min)
    """
    actions = []

    # Get scheduled sessions approaching timeslot
    # Use TOTAL_LEAD_TIME to account for both delays
    approaching = get_sessions_approaching_timeslot(
        lead_time_minutes=TOTAL_LEAD_TIME_MINUTES  # ~35 minutes
    )

    for session in approaching:
        if session.worker_id is None:
            # Session not yet assigned - resource scheduler couldn't place it
            definition = get_definition(session.definition_id)
            template = select_worker_template(definition)

            # Check if scale-up already in progress for this template
            pending_workers = get_workers_in_state(
                template=template,
                states=[WorkerStatus.PENDING, WorkerStatus.PROVISIONING]
            )

            if not pending_workers:
                actions.append(ScaleUpAction(
                    template=template,
                    reason=f"Session {session.id} approaching timeslot with no capacity",
                    estimated_ready_time=datetime.now() + timedelta(minutes=WORKER_BOOTUP_DELAY_MINUTES)
                ))

    return actions
```

#### 2.3.2 Scale-Down Logic

> **IMPORTANT:** Workers should enter DRAINING state before scale-down to allow running instances to complete gracefully.

```python
SCALE_DOWN_GRACE_PERIOD_MINUTES = 30  # Don't scale down if work approaching


def check_scale_down_candidates() -> list[ScaleDownAction]:
    """
    Identify workers eligible for scale-down.

    Process:
    1. Find idle workers (no running instances)
    2. Check for upcoming scheduled work
    3. Transition to DRAINING (not immediate stop)
    4. DRAINING workers complete existing work, accept no new assignments
    5. When DRAINING worker is empty -> STOPPING -> STOPPED
    """
    actions = []

    for worker in get_workers_in_state(states=[WorkerStatus.RUNNING]):
        # Check if worker has any active sessions
        active_sessions = get_sessions_on_worker(
            worker_id=worker.id,
            states=[
                SessionState.RUNNING,
                SessionState.COLLECTING,
                SessionState.GRADING
            ]
        )

        if active_sessions:
            continue  # Worker is active, cannot scale down

        # Check if worker has upcoming scheduled sessions
        scheduled_sessions = get_sessions_on_worker(
            worker_id=worker.id,
            states=[
                SessionState.SCHEDULED,
                SessionState.INSTANTIATING
            ]
        )

        if scheduled_sessions:
            continue  # Worker has pending work

        # Check approaching timeslots (any session scheduled to this worker)
        approaching = get_approaching_sessions_for_worker(
            worker_id=worker.id,
            lookahead_minutes=SCALE_DOWN_GRACE_PERIOD_MINUTES
        )

        if approaching:
            continue  # Work coming soon

        # Worker is idle - candidate for scale-down
        # Prefer DRAINING transition over immediate stop
        actions.append(ScaleDownAction(
            worker_id=worker.id,
            action=ScaleDownActionType.DRAIN,  # Start draining, not immediate stop
            reason="No running or scheduled sessions"
        ))

    # Also check DRAINING workers that can be stopped
    for worker in get_workers_in_state(states=[WorkerStatus.DRAINING]):
        sessions_on_worker = get_sessions_on_worker(
            worker_id=worker.id,
            states=ACTIVE_SESSION_STATES
        )

        if not sessions_on_worker:
            # DRAINING worker with no sessions -> stop it
            actions.append(ScaleDownAction(
                worker_id=worker.id,
                action=ScaleDownActionType.STOP,
                reason="Draining complete, no remaining sessions"
            ))

    return actions
```

#### 2.3.3 Worker State Machine with DRAINING

```
                                    ┌─────────────────┐
                                    │                 │
                                    ▼                 │
┌─────────┐    ┌─────────────┐    ┌──────────┐    ┌──────────┐
│ PENDING │───▶│ PROVISIONING│───▶│ RUNNING  │───▶│ DRAINING │
└─────────┘    └─────────────┘    └──────────┘    └──────────┘
                                        │              │
                                        │              │ All instances
                                        │              │ completed
                                        ▼              ▼
                                  ┌──────────┐    ┌──────────┐
                                  │ STOPPING │◀───│ (empty)  │
                                  └──────────┘    └──────────┘
                                        │
                                        ▼
                                  ┌──────────┐
                                  │ STOPPED  │
                                  └──────────┘
                                        │
                                        ▼
                                  ┌────────────┐
                                  │ TERMINATED │
                                  └────────────┘
```

**DRAINING State Behavior:**

- Continues running existing LabletSessions
- Does NOT accept new session assignments (Resource Scheduler skips)
- Transitions to STOPPING when last session terminates
- Has configurable timeout (default 4 hours) after which force-stop

---

### 2.4 Worker Controller (`src/worker-controller/`)

**Responsibility:** CML Worker reconciliation loop - reconciles desired worker state (spec) against actual cloud infrastructure state.

**Domain:** Infrastructure-layer resource management. Talks exclusively to **Cloud Provider SPI** (AWS EC2, CloudWatch, CML system API).

**Key Design Decision:** Separate service from Lablet Controller to enable clear domain separation. Worker Controller reconciles CML Workers (infrastructure layer); Lablet Controller reconciles LabletSessions (application layer). All mutations go through Control Plane API (ADR-001).

```
┌────────────────────────────────────────────────────────────────┐
│                     WORKER CONTROLLER                          │
│               (Infrastructure Layer - Compute)                 │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                  LEADER ELECTION (etcd)                  │  │
│  └─────────────────────────┬────────────────────────────────┘  │
│                            │                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                 RECONCILIATION LOOP                      │  │
│  │                 (Every 30 seconds)                       │  │
│  │                                                          │  │
│  │     For each CMLWorker:                                  │  │
│  │       SPEC (desired) ←→ OBSERVE (actual) → ACT           │  │
│  └─────────────────────────┬────────────────────────────────┘  │
│                            │                                   │
│                            ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │       CLOUD PROVIDER SPI (Service Provider Interface).   │  │
│  │                                                          │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │  AWS EC2 API                                        │ │  │
│  │  │  • Describe instances (status, tags)                │ │  │
│  │  │  • Start/stop/terminate instances                   │ │  │
│  │  │  • Create instances (scale-up)                      │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │  AWS CloudWatch API                                 │ │  │
│  │  │  • Instance CPU/memory/network metrics              │ │  │
│  │  │  • Disk I/O and utilization                         │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  │  ┌─────────────────────────────────────────────────────┐ │  │
│  │  │  CML System API (worker-level)                      │ │  │
│  │  │  • /api/v0/system_information (no auth required)    │ │  │
│  │  │  • /api/v0/system_stats (requires auth)             │ │  │
│  │  │  • License registration/deregistration              │ │  │
│  │  └─────────────────────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────┘  │
│                            │                                   │
│                            ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │                   CONTROL PLANE API                       │ │
│  │         (All mutations via API - ADR-001)                 │ │
│  └───────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

#### 2.4.0 Worker Controller Reconciliation Pattern

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                WORKER CONTROLLER - RECONCILIATION PATTERN                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐    │
│   │       SPEC       │     │     OBSERVE      │     │       ACT        │    │
│   │   (Desired)      │     │    (Actual)      │     │   (Reconcile)    │    │
│   └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘    │
│            │                        │                        │              │
│            ▼                        ▼                        ▼              │
│   ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐    │
│   │ CMLWorker        │     │ EC2 + CML State  │     │ • Launch EC2     │    │
│   │ • status=RUNNING │     │ • EC2 running    │     │ • Register lic.  │    │
│   │ • license=ENT    │ ←→  │ • CML ready      │  →  │ • Update status  │    │
│   │ • region=us-e-1  │     │ • No license     │     │ • Collect metrics│    │
│   └──────────────────┘     └──────────────────┘     └──────────────────┘    │
│                                                                             │
│   Source: MongoDB         Source: AWS + CML API      Target: Both           │
│   (via Control Plane)     (direct observation)       (via Control Plane)    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Reconciliation Examples:**

| Desired (Spec) | Actual (Observed) | Action |
|----------------|-------------------|--------|
| Worker status=RUNNING | EC2 stopped | Start EC2 instance |
| Worker status=RUNNING | EC2 running, CML unlicensed | Register CML license |
| Worker status=RUNNING | EC2 running, CML licensed | Update metrics, no action |
| Worker status=STOPPED | EC2 running | Stop EC2 instance |
| Worker status=TERMINATED | EC2 exists | Terminate EC2 instance |
| Worker imported=false | EC2 tagged for import | Create worker record |

#### 2.4.1 Metrics Collection Job

The Worker Controller polls each active CML Worker for infrastructure metrics:

- **CML System API**: System stats via `/api/v0/system_stats` (worker-level, requires auth)
- **EC2 CloudWatch**: Instance-level CPU, memory, network, disk
- **EC2 Describe Instances**: Instance status, tags, metadata

```python
class WorkerMetricsCollectionJob:
    """Collects infrastructure metrics from CML Workers and updates via API."""

    async def execute_async(self, worker_id: str) -> None:
        # 1. Get worker spec from API
        worker = await self.api_client.get_worker(worker_id)

        # 2. Observe actual EC2 state
        ec2_state = await self.ec2_client.describe_instance(worker.ec2_instance_id)

        # 3. Observe CML system metrics
        cml_stats = await self.cml_client.get_system_stats(
            host=worker.ip_address,
            username=settings.CML_WORKER_API_USERNAME,
            password=settings.CML_WORKER_API_PASSWORD
        )

        # 4. Collect CloudWatch metrics
        cloudwatch_metrics = await self.cloudwatch_client.get_instance_metrics(
            instance_id=worker.ec2_instance_id
        )

        # 5. Update via Control Plane API (ADR-001)
        await self.api_client.update_worker_metrics(
            worker_id=worker_id,
            metrics=WorkerMetrics(
                ec2_status=ec2_state.status,
                cpu_utilization=cml_stats.cpu_percent,
                memory_utilization=cml_stats.memory_percent,
                disk_utilization=cml_stats.disk_percent,
                network_in=cloudwatch_metrics.network_in,
                network_out=cloudwatch_metrics.network_out,
                collected_at=datetime.utcnow()
            )
        )
```

#### 2.4.2 License Management

Reconciles CML license state with desired configuration:

```python
class LicenseReconciler:
    """Ensures CML workers have correct license state."""

    async def reconcile(self, worker: CMLWorker) -> None:
        # Observe actual license state
        license_info = await self.cml_client.get_license_info(worker.ip_address)

        # Compare with desired spec
        if worker.license_required and not license_info.is_registered:
            # Action: Register license
            await self.cml_client.register_license(
                host=worker.ip_address,
                license_token=settings.CML_LICENSE_TOKEN
            )
            await self.api_client.update_worker_license_status(
                worker_id=worker.id,
                license_registered=True
            )

        elif not worker.license_required and license_info.is_registered:
            # Action: Deregister license (release for other workers)
            await self.cml_client.deregister_license(worker.ip_address)
            await self.api_client.update_worker_license_status(
                worker_id=worker.id,
                license_registered=False
            )
```

#### 2.4.3 Auto-Import Workers

Discovers and imports EC2 instances tagged for CML management:

```python
class AutoImportWorkersJob:
    """Discovers EC2 instances and creates worker records."""

    async def execute_async(self) -> None:
        # Observe: Find EC2 instances tagged for CML
        ec2_instances = await self.ec2_client.describe_instances(
            filters=[
                {"Name": "tag:cml-managed", "Values": ["true"]},
                {"Name": "instance-state-name", "Values": ["running"]}
            ]
        )

        # Get existing workers from spec
        existing_workers = await self.api_client.list_workers()
        existing_instance_ids = {w.ec2_instance_id for w in existing_workers}

        # Reconcile: Create workers for new instances
        for instance in ec2_instances:
            if instance.id not in existing_instance_ids:
                # Action: Import worker
                await self.api_client.import_worker(
                    ec2_instance_id=instance.id,
                    name=instance.tags.get("Name", f"imported-{instance.id}"),
                    ip_address=instance.private_ip
                )
```

---

### 2.5 Cloud Provider SPI

**Responsibility:** Abstract cloud-specific operations behind a common interface.

```
┌─────────────────────────────────────────────────────────────────┐
│                   CLOUD PROVIDER SPI                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                 ICloudProviderAdapter                     │  │
│  │                 (Abstract Interface)                      │  │
│  │                                                           │  │
│  │  + create_instance(template) -> InstanceId                │  │
│  │  + start_instance(instance_id) -> None                    │  │
│  │  + stop_instance(instance_id) -> None                     │  │
│  │  + terminate_instance(instance_id) -> None                │  │
│  │  + get_instance_status(instance_id) -> Status             │  │
│  │  + get_instance_metrics(instance_id) -> Metrics           │  │
│  │  + list_instances(filters) -> list[Instance]              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            △                                    │
│                            │                                    │
│            ┌───────────────┼───────────────┐                    │
│            │               │               │                    │
│  ┌─────────┴────┐  ┌───────┴─────┐  ┌──────┴──────┐             │
│  │ AWS EC2      │  │ GCP Compute │  │ Azure VMs   │             │
│  │ Adapter      │  │ Adapter     │  │ Adapter     │             │
│  │ (Implemented)│  │ (Future)    │  │ (Future)    │             │
│  └──────────────┘  └─────────────┘  └─────────────┘             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Domain Model

### 3.1 Aggregate Relationships

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DOMAIN MODEL                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌────────────────────┐         ┌────────────────────────────────────────┐  │
│  │  LabletDefinition  │ 1     * │  LabletSession (AggregateRoot)         │  │
│  │  (Aggregate Root)  │────────▶│                                        │  │
│  │                    │         │  • id                                  │  │
│  │  • id              │         │  • definition_id, definition_ver       │  │
│  │  • name            │         │  • worker_id                           │─┐│
│  │  • version         │         │  • lab_record_id (1:1)                 │ ││
│  │  • lab_artifact_uri│         │  • user_session_id → UserSession       │ ││
│  │  • resource_reqs   │         │  • grading_session_id → GradingSess    │ ││
│  │  • license_affinity│         │  • score_report_id → ScoreReport       │ ││
│  │  • port_template   │         │  • state (LabletSessionStatus)         │ ││
│  │  • grading_rules   │         │  • allocated_ports                     │ ││
│  │  • warm_pool_depth │         │  • timeslot_start, timeslot_end        │ ││
│  └────────────────────┘         │  • started_at, ended_at                │ ││
│                                 │  • duration_seconds                    │ ││
│                                 │  • owner_id, reservation_id            │ ││
│                                 └────────────────────────────────────────┘ ││
│                                                                            ││
│  ┌──────────────────────────────────────────────────────────────────────┐  ││
│  │  CHILD ENTITIES (separate collections, linked by lablet_session_id)  │  ││
│  │                                                                      │  ││
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐    │  ││
│  │  │ UserSession      │  │ GradingSession   │  │ ScoreReport      │    │  ││
│  │  │ (Entity[str])    │  │ (Entity[str])    │  │ (Entity[str])    │    │  ││
│  │  │                  │  │                  │  │                  │    │  ││
│  │  │ • lds_session_id │  │ • grading_id     │  │ • grading_sess_id│    │  ││
│  │  │ • lds_part_id    │  │ • grading_part_id│  │ • score          │    │  ││
│  │  │ • form_qual_name │  │ • pod_id         │  │ • max_score      │    │  ││
│  │  │ • login_url      │  │ • form_qual_name │  │ • cut_score      │    │  ││
│  │  │ • devices[]      │  │ • devices[]      │  │ • passed         │    │  ││
│  │  │ • status         │  │ • status         │  │ • sections[]     │    │  ││
│  │  └──────────────────┘  └──────────────────┘  │ • submitted_at   │    │  ││
│  │                                              │ • report_url     │    │  ││
│  │  Collection:            Collection:           └──────────────────┘   │  ││
│  │  user_sessions          grading_sessions      Collection:            │  ││
│  │                                              score_reports           │  ││
│  └──────────────────────────────────────────────────────────────────────┘  ││
│                                                                            ││
│                                          ┌─────────────────────────────────┘│
│                                          │                                  │
│                                          ▼ *                                │
│  ┌────────────────────┐         ┌────────────────────┐                      │
│  │  WorkerTemplate    │ 1     * │  CMLWorker         │                      │
│  │  (Value Object)    │────────▶│  (Aggregate Root)  │                      │
│  │                    │         │  [EXTENDED]        │                      │
│  │  • name            │         │                    │                      │
│  │  • instance_type   │         │  • id              │                      │
│  │  • capacity        │         │  • template_name   │                      │
│  │  • license_type    │         │  • status          │                      │
│  │  • ami_pattern     │         │  • capacity        │                      │
│  │  • region          │         │  • allocated_cap   │                      │
│  │  • port_range      │         │  • port_allocations│                      │
│  └────────────────────┘         │  • session_ids[]   │                      │
│                                 └────────────────────┘                      │
│                                                                             │
│  ELIMINATED (AD-39): LabletRecordRun, LabletLabBinding                      │
│  LabletSession absorbs: allocated_ports, started_at/ended_at/duration       │
│  LabletSession absorbs: lab_record_id as direct 1:1 reference (AD-43)       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 LabletDefinition Aggregate

```python
@dataclass
class LabletDefinitionState(AggregateState[str]):
    """State for LabletDefinition aggregate."""

    id: str
    name: str
    version: str  # Semantic version

    # Artifact reference
    lab_artifact_uri: str  # S3/MinIO path
    lab_yaml_hash: str     # SHA-256 for change detection
    lab_yaml_cached: str | None  # Cached YAML content

    # Resource requirements
    resource_requirements: ResourceRequirements
    license_affinity: list[LicenseType]
    node_count: int

    # Port configuration
    port_template: PortTemplate  # Template with placeholders

    # Assessment integration
    grading_rules_uri: str | None
    max_duration_minutes: int

    # Warm pool
    warm_pool_depth: int

    # Ownership
    owner_notification: NotificationConfig | None
    created_by: str
    created_at: datetime


@dataclass
class ResourceRequirements:
    cpu_cores: int
    memory_gb: int
    storage_gb: int
    nested_virt: bool
    ami_requirements: list[AmiRequirement] | None


@dataclass
class PortTemplate:
    """Template for port allocation with placeholders."""
    ports: list[PortDefinition]

    # Example: [{"name": "serial_1", "protocol": "tcp"}, {"name": "vnc_1", "protocol": "tcp"}]


class LabletDefinition(AggregateRoot[LabletDefinitionState, str]):
    """LabletDefinition aggregate - immutable per version."""

    @staticmethod
    def create(
        name: str,
        version: str,
        lab_artifact_uri: str,
        resource_requirements: ResourceRequirements,
        license_affinity: list[LicenseType],
        port_template: PortTemplate,
        created_by: str,
        **kwargs
    ) -> "LabletDefinition":
        """Create a new LabletDefinition."""
        definition = LabletDefinition()
        definition.record_event(LabletDefinitionCreatedDomainEvent(
            aggregate_id=str(uuid4()),
            name=name,
            version=version,
            lab_artifact_uri=lab_artifact_uri,
            resource_requirements=resource_requirements,
            license_affinity=license_affinity,
            port_template=port_template,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
            **kwargs
        ))
        return definition
```

### 3.3 LabletSession Aggregate (renamed from LabletInstance — AD-38)

```python
class LabletSessionStatus(Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    INSTANTIATING = "instantiating"
    READY = "ready"              # NEW: LDS provisioned, awaiting user login
    RUNNING = "running"
    COLLECTING = "collecting"
    GRADING = "grading"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ARCHIVED = "archived"
    TERMINATED = "terminated"


@dataclass
class LabletSessionState(AggregateState[str]):
    """State for LabletSession aggregate."""

    id: str
    definition_id: str
    definition_version: str  # Pinned at creation

    # Assignment
    worker_id: str | None
    allocated_ports: dict[str, int] | None  # {"serial_1": 5041, "vnc_1": 5044}
    cml_lab_id: str | None  # Lab ID in CML after import

    # Lifecycle
    status: LabletSessionStatus
    state_history: list[StateTransition]

    # Timeslot
    timeslot_start: datetime
    timeslot_end: datetime

    # Ownership
    owner_id: str
    reservation_id: str | None  # External reservation reference

    # Lab Record binding (1:1, absorbed from LabletLabBinding — AD-39, AD-43)
    lab_record_id: str | None

    # Child entity references (separate collections — AD-45, AD-46, AD-47-R1)
    user_session_id: str | None       # → UserSession (user_sessions collection)
    grading_session_id: str | None    # → GradingSession (grading_sessions collection)
    score_report_id: str | None       # → ScoreReport (score_reports collection)

    # Timing (absorbed from LabletRecordRun — AD-39)
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None

    # Timestamps
    created_at: datetime
    scheduled_at: datetime | None
    terminated_at: datetime | None


class LabletSession(AggregateRoot[LabletSessionState, str]):
    """LabletSession aggregate - runtime lifecycle (renamed from LabletInstance)."""

    def schedule(self, worker_id: str, allocated_ports: dict[str, int]) -> None:
        """Assign session to worker with port allocation."""
        if self.state.status != LabletSessionStatus.PENDING:
            raise InvalidStateTransition(f"Cannot schedule from {self.state.status}")

        self.record_event(LabletSessionScheduledDomainEvent(
            aggregate_id=self.id(),
            worker_id=worker_id,
            allocated_ports=allocated_ports,
            scheduled_at=datetime.now(timezone.utc)
        ))

    def start_instantiation(self) -> None:
        """Begin lab import and startup."""
        if self.state.status != LabletSessionStatus.SCHEDULED:
            raise InvalidStateTransition(f"Cannot instantiate from {self.state.status}")

        self.record_event(LabletSessionInstantiatingDomainEvent(
            aggregate_id=self.id()
        ))

    def mark_ready(self, cml_lab_id: str, user_session_id: str) -> None:
        """Mark session as ready after LDS provisioning complete."""
        self.record_event(LabletSessionReadyDomainEvent(
            aggregate_id=self.id(),
            cml_lab_id=cml_lab_id,
            user_session_id=user_session_id,
        ))

    def mark_running(self) -> None:
        """Mark session as running when user logs in (via LDS CloudEvent)."""
        self.record_event(LabletSessionRunningDomainEvent(
            aggregate_id=self.id(),
            started_at=datetime.now(timezone.utc)
        ))

    def start_collection(self) -> None:
        """Transition to collecting state."""
        if self.state.status != LabletSessionStatus.RUNNING:
            raise InvalidStateTransition(f"Cannot collect from {self.state.status}")

        self.record_event(LabletSessionCollectingDomainEvent(
            aggregate_id=self.id()
        ))

    def record_grading_result(self, score_report_id: str) -> None:
        """Record grading result and transition to stopping."""
        self.record_event(LabletSessionGradedDomainEvent(
            aggregate_id=self.id(),
            score_report_id=score_report_id
        ))
```

### 3.3.1 UserSession Entity (AD-45)

```python
class UserSessionStatus(Enum):
    PROVISIONING = "provisioning"
    PROVISIONED = "provisioned"    # LDS session created, awaiting user login
    ACTIVE = "active"              # User logged in
    PAUSED = "paused"              # User paused session
    ENDED = "ended"                # Normal completion
    EXPIRED = "expired"            # Timeslot expired
    FAULTED = "faulted"            # LDS error


@dataclass
class UserSessionState(AggregateState[str]):
    """State for UserSession entity. Stored in 'user_sessions' collection."""

    id: str
    lablet_session_id: str  # FK to LabletSession

    # LDS references
    lds_session_id: str
    lds_part_id: str
    form_qualified_name: str

    # Access
    login_url: str | None
    devices: list[DeviceAccessInfo]

    # Lifecycle
    status: UserSessionStatus
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
```

### 3.3.2 GradingSession Entity (AD-46)

```python
class GradingStatus(Enum):
    PENDING = "pending"
    COLLECTING = "collecting"
    GRADING = "grading"
    REVIEWING = "reviewing"
    SUBMITTED = "submitted"
    FAULTED = "faulted"


@dataclass
class GradingSessionState(AggregateState[str]):
    """State for GradingSession entity. Stored in 'grading_sessions' collection."""

    id: str
    lablet_session_id: str  # FK to LabletSession

    # Grading Engine references
    grading_session_id: str
    grading_part_id: str
    pod_id: str

    # Content
    form_qualified_name: str
    devices: list[DeviceAccessInfo]

    # Lifecycle
    status: GradingStatus
    created_at: datetime
    completed_at: datetime | None
```

### 3.3.3 ScoreReport Entity (AD-47-R1)

```python
@dataclass
class ScoreSection:
    """Individual grading section within a score report."""
    criterion: str
    points: float
    max_points: float


@dataclass
class ScoreReportState(AggregateState[str]):
    """State for ScoreReport entity. Stored in 'score_reports' collection."""

    id: str
    lablet_session_id: str    # FK to LabletSession
    grading_session_id: str   # FK to GradingSession

    # Scores
    score: float
    max_score: float
    cut_score: float | None
    passed: bool
    sections: list[ScoreSection]

    # Metadata
    submitted_at: datetime
    report_url: str | None
```

### 3.4 CMLWorker Extensions

The existing `CMLWorker` aggregate needs extensions for capacity tracking:

```python
@dataclass
class WorkerCapacity:
    """Capacity specification for a worker."""
    cpu_cores: int
    memory_gb: int
    storage_gb: int
    max_nodes: int  # License-based limit


@dataclass
class PortAllocation:
    """Port allocation on a worker."""
    session_id: str
    ports: dict[str, int]  # {"serial_1": 5041, "vnc_1": 5044}
    allocated_at: datetime


# Extensions to CMLWorkerState
class CMLWorkerState(AggregateState[str]):
    # ... existing fields ...

    # NEW: Capacity management
    template_name: str | None  # Reference to WorkerTemplate
    declared_capacity: WorkerCapacity
    allocated_capacity: WorkerCapacity  # Sum of running sessions

    # NEW: Port management
    port_range_start: int  # 2000
    port_range_end: int    # 9999
    port_allocations: list[PortAllocation]

    # NEW: Session tracking
    session_ids: list[str]  # Currently assigned sessions

    @property
    def available_capacity(self) -> WorkerCapacity:
        """Calculate remaining available capacity."""
        return WorkerCapacity(
            cpu_cores=self.declared_capacity.cpu_cores - self.allocated_capacity.cpu_cores,
            memory_gb=self.declared_capacity.memory_gb - self.allocated_capacity.memory_gb,
            storage_gb=self.declared_capacity.storage_gb - self.allocated_capacity.storage_gb,
            max_nodes=self.declared_capacity.max_nodes - self.allocated_capacity.max_nodes
        )

    @property
    def available_ports(self) -> int:
        """Calculate remaining available ports."""
        used_ports = sum(len(a.ports) for a in self.port_allocations)
        total_ports = self.port_range_end - self.port_range_start + 1
        return total_ports - used_ports
```

---

## 4. Data Flows

### 4.1 Reservation Request Flow

```
┌─────────┐          ┌───────────────┐          ┌─────────────────┐
│ Client  │          │ Control Plane │          │    Resource     │
│         │          │     API       │          │    Scheduler    │
└────┬────┘          └───────┬───────┘          └────────┬────────┘
     │                       │                           │
     │ POST /api/v1/sessions │                           │
     │ {definition_id,       │                           │
     │  timeslot_start, ...} │                           │
     │──────────────────────▶│                           │
     │                       │                           │
     │                       │ Create Session          │
     │                       │ (PENDING state)         │
     │                       │────────┐               │
     │                       │        │               │
     │                       │◀───────┘               │
     │                       │                        │
     │                       │ Emit: SessionCreated    │
     │                       │───────────────────────▶│
     │                       │                        │
     │ 201 Created           │                        │
     │ {session_id, state:   │                        │
     │  "pending"}           │                        │
     │◀──────────────────────│                        │
     │                       │                        │
     │                       │                        │ Scheduling
     │                       │                        │ Loop Runs
     │                       │                        │─────┐
     │                       │                        │     │ Find
     │                       │                        │     │ Worker
     │                       │                        │◀────┘
     │                       │                        │
     │                       │ POST /internal/schedule│
     │                       │ {session_id, worker_id │
     │                       │  allocated_ports}      │
     │                       │◀───────────────────────│
     │                       │                        │
     │                       │ Update Session         │
     │                       │ (SCHEDULED state)      │
     │                       │────────┐               │
     │                       │        │               │
     │                       │◀───────┘               │
     │                       │                        │
     │ SSE: SessionScheduled │                        │
     │◀──────────────────────│                        │
     │                       │                        │
```

### 4.2 Session Instantiation Flow

```
┌─────────┐      ┌───────────┐      ┌──────────┐      ┌──────────┐
│Lablet   │      │ Control   │      │ CML      │      │Artifact  │
│Controller      │ Plane API │      │ Worker   │      │Storage   │
└────┬────┘      └─────┬─────┘      └────┬─────┘      └────┬─────┘
     │                 │                 │                 │
     │ Reconcile Loop  │                 │                 │
     │ (Approaching    │                 │                 │
     │  Timeslot)      │                 │                 │
     │────────────────▶│                 │                 │
     │                 │                 │                 │
     │ Get Session     │                 │                 │
     │◀────────────────│                 │                 │
     │                 │                 │                 │
     │ Get Definition  │                 │                 │
     │◀────────────────│                 │                 │
     │                 │                 │                 │
     │                 │                 │      Download   │
     │                 │                 │      Lab YAML   │
     │────────────────────────────────────────────────────▶│
     │                 │                 │                 │
     │◀─────────────────────────────────────Lab YAML──────│
     │                 │                 │                 │
     │ Rewrite YAML    │                 │                 │
     │ (Port mapping)  │                 │                 │
     │────────┐        │                 │                 │
     │        │        │                 │                 │
     │◀───────┘        │                 │                 │
     │                 │                 │                 │
     │ POST /internal/ │                 │                 │
     │ transition      │                 │                 │
     │ (INSTANTIATING) │                 │                 │
     │────────────────▶│                 │                 │
     │                 │                 │                 │
     │                 │ Import Lab YAML │                 │
     │                 │────────────────▶│                 │
     │                 │                 │                 │
     │                 │ Lab ID          │                 │
     │                 │◀────────────────│                 │
     │                 │                 │                 │
     │                 │ Start Lab       │                 │
     │                 │────────────────▶│                 │
     │                 │                 │                 │
     │                 │ Lab Started     │                 │
     │                 │◀────────────────│                 │
     │                 │                 │                 │
     │ POST /internal/ │                 │                 │
     │ transition      │                 │                 │
     │ (RUNNING)       │                 │                 │
     │────────────────▶│                 │                 │
     │                 │                 │                 │
     │                 │ Emit CloudEvent:│                 │
     │                 │ session.running │                 │
     │                 │─────────────────│▶ (to Assessment)│
     │                 │                 │                 │
```

### 4.3 Port Rewriting Process

```python
def rewrite_lab_yaml(
    lab_yaml: str,
    port_template: PortTemplate,
    allocated_ports: dict[str, int]
) -> str:
    """
    Rewrite lab YAML with allocated ports.

    Template placeholders in smart_annotations:
      tag: serial:${PORT_SERIAL_1}

    Becomes:
      tag: serial:5041
    """
    import yaml

    lab_data = yaml.safe_load(lab_yaml)

    # Build placeholder -> port mapping
    port_map = {}
    for port_def in port_template.ports:
        placeholder = f"${{{port_def.name.upper()}}}"
        port_map[placeholder] = allocated_ports[port_def.name]

    # Rewrite smart_annotations
    for annotation in lab_data.get("smart_annotations", []):
        tag = annotation.get("tag", "")
        for placeholder, port in port_map.items():
            if placeholder in tag:
                annotation["tag"] = tag.replace(placeholder, str(port))
                annotation["label"] = annotation["label"].replace(placeholder, str(port))

    # Also rewrite node tags
    for node in lab_data.get("nodes", []):
        new_tags = []
        for tag in node.get("tags", []):
            for placeholder, port in port_map.items():
                tag = tag.replace(placeholder, str(port))
            new_tags.append(tag)
        node["tags"] = new_tags

    return yaml.dump(lab_data)
```

---

## 5. CloudEvents Schema

> **See [ADR-003: CloudEvents for External Integration](./adr/ADR-003-cloudevents-for-integration.md) for rationale.**

**Important:** CloudEvents are emitted for **external integration and audit** - they are NOT the primary persistence mechanism. State is persisted in etcd/MongoDB; events are a side-effect for subscribers.

### 5.1 Complete Event Catalog

#### 5.1.1 LabletDefinition Events

| Event Type | Trigger | Purpose |
|------------|---------|---------|
| `ccm.lablet.definition.created` | New definition registered | Notify consumers of new lab type |
| `ccm.lablet.definition.version.created` | New version detected | Version management, cache invalidation |
| `ccm.lablet.definition.deprecated` | Definition marked deprecated | Prevent new sessions |

#### 5.1.2 LabletSession Lifecycle Events (All States)

| Event Type | Trigger | Purpose |
|------------|---------|---------|
| `ccm.lablet.session.pending` | Session created | Audit: request received |
| `ccm.lablet.session.scheduled` | Worker assigned | Audit: placement decision made |
| `ccm.lablet.session.instantiating` | Lab import begins | Audit: instantiation starting |
| `ccm.lablet.session.ready` | LDS provisioned, awaiting user | **NEW**: Session ready for user login |
| `ccm.lablet.session.running` | User logged in (LDS CloudEvent) | **Assessment integration**: session active |
| `ccm.lablet.session.collecting` | Collection triggered | **Assessment integration**: begin collection |
| `ccm.lablet.session.grading` | Grading in progress | **Assessment integration**: grading active |
| `ccm.lablet.session.graded` | Grading finished | **Assessment integration**: score available |
| `ccm.lablet.session.stopping` | Stop initiated | Audit: teardown starting |
| `ccm.lablet.session.stopped` | Lab stopped | Audit: lab inactive |
| `ccm.lablet.session.archived` | Resources cleaned | Audit: ready for deletion |
| `ccm.lablet.session.terminated` | Session deleted | Audit: final state |

#### 5.1.2.1 Child Entity Events

| Event Type | Trigger | Purpose |
|------------|---------|---------|
| `ccm.lablet.session.user-session.created` | LDS session provisioned | UserSession tracking |
| `ccm.lablet.session.user-session.active` | User logged in | Session started |
| `ccm.lablet.session.user-session.ended` | User ended session | Session completed |
| `ccm.lablet.session.grading-session.created` | Grading initiated | GradingSession tracking |
| `ccm.lablet.session.grading-session.completed` | Grading finished | Results available |
| `ccm.lablet.session.score-report.created` | Score recorded | ScoreReport created |

#### 5.1.3 Worker Lifecycle Events

| Event Type | Trigger | Purpose |
|------------|---------|---------|
| `ccm.worker.pending` | Scale-up initiated | Audit: worker requested |
| `ccm.worker.provisioning.started` | EC2 instance launching | Audit: cloud API called |
| `ccm.worker.running` | Worker ready for workload | Capacity management |
| `ccm.worker.draining` | Scale-down initiated | Capacity: no new assignments |
| `ccm.worker.stopping` | Worker shutdown started | Audit: EC2 stop in progress |
| `ccm.worker.stopped` | Worker stopped | Cost: compute paused |
| `ccm.worker.terminated` | Worker deleted | Audit: resources released |

#### 5.1.4 Scaling Events

| Event Type | Trigger | Purpose |
|------------|---------|---------|
| `ccm.scaling.up.requested` | Capacity shortage detected | Operations alerting |
| `ccm.scaling.up.completed` | New worker ready | Capacity confirmation |
| `ccm.scaling.down.requested` | Idle worker detected | Cost optimization tracking |
| `ccm.scaling.down.completed` | Worker stopped/terminated | Cost confirmation |

### 5.2 Event Payload Examples

```yaml
# ccm.lablet.session.pending
{
  "specversion": "1.0",
  "type": "ccm.lablet.session.pending",
  "source": "ccm/api",
  "id": "evt-12345",
  "time": "2026-01-15T10:30:00Z",
  "datacontenttype": "application/json",
  "data": {
    "session_id": "sess-abc123",
    "definition_id": "def-xyz789",
    "definition_version": "1.2.0",
    "owner_id": "user-456",
    "reservation_id": "res-789",
    "timeslot_start": "2026-01-15T11:00:00Z",
    "timeslot_end": "2026-01-15T12:00:00Z",
    "created_at": "2026-01-15T10:30:00Z"
  }
}

# ccm.lablet.session.instantiating
{
  "specversion": "1.0",
  "type": "ccm.lablet.session.instantiating",
  "source": "ccm/controller",
  "id": "evt-12346",
  "time": "2026-01-15T10:35:00Z",
  "data": {
    "session_id": "sess-abc123",
    "worker_id": "worker-def456",
    "allocated_ports": {
      "serial_1": 5041,
      "vnc_1": 5044
    },
    "lab_yaml_hash": "sha256:abc123..."
  }
}

# ccm.lablet.session.running
{
  "specversion": "1.0",
  "type": "ccm.lablet.session.running",
  "source": "ccm/controller",
  "id": "evt-12347",
  "time": "2026-01-15T10:45:00Z",
  "data": {
    "session_id": "sess-abc123",
    "worker_id": "worker-def456",
    "worker_hostname": "worker-def456.internal",
    "cml_lab_id": "lab-ghi789",
    "allocated_ports": {
      "serial_1": 5041,
      "serial_2": 5042,
      "vnc_1": 5044
    },
    "started_at": "2026-01-15T10:45:00Z"
  }
}

# ccm.lablet.session.collecting
{
  "specversion": "1.0",
  "type": "ccm.lablet.session.collecting",
  "source": "ccm/api",
  "id": "evt-12348",
  "time": "2026-01-15T11:50:00Z",
  "data": {
    "session_id": "sess-abc123",
    "triggered_by": "user-456",  // or "system" for auto-collection
    "collection_reason": "manual"  // or "timeslot_end", "assessment_request"
  }
}

# ccm.lablet.session.grading
{
  "specversion": "1.0",
  "type": "ccm.lablet.session.grading",
  "source": "ccm/controller",
  "id": "evt-12349",
  "time": "2026-01-15T11:52:00Z",
  "data": {
    "session_id": "sess-abc123",
    "grading_session_id": "grade-session-xyz"
  }
}

# ccm.lablet.session.graded
{
  "specversion": "1.0",
  "type": "ccm.lablet.session.graded",
  "source": "ccm/controller",
  "id": "evt-12350",
  "time": "2026-01-15T12:00:00Z",
  "data": {
    "session_id": "sess-abc123",
    "score_report_id": "sr-abc123",
    "score": {
      "total": 85,
      "max": 100,
      "passed": true,
      "breakdown": [
        {"criterion": "Task 1", "points": 25, "max": 30},
        {"criterion": "Task 2", "points": 30, "max": 30},
        {"criterion": "Task 3", "points": 30, "max": 40}
      ]
    },
    "grading_duration_seconds": 120
  }
}

# ccm.lablet.session.terminated
{
  "specversion": "1.0",
  "type": "ccm.lablet.session.terminated",
  "source": "ccm/controller",
  "id": "evt-12355",
  "time": "2026-01-15T12:05:00Z",
  "data": {
    "session_id": "sess-abc123",
    "final_state": "archived",
    "score_report_id": "sr-abc123",
    "duration_minutes": 55
  }
}

# ccm.worker.draining (for scale-down visibility)
{
  "specversion": "1.0",
  "type": "ccm.worker.draining",
  "source": "ccm/controller",
  "id": "evt-worker-drain-1",
  "time": "2026-01-15T13:00:00Z",
  "data": {
    "worker_id": "worker-def456",
    "reason": "scale_down_idle",
    "running_sessions_count": 2,
    "estimated_drain_completion": "2026-01-15T14:00:00Z"
  }
}
```

### 5.3 Events Consumed by CCM

```yaml
# lds.session.started (from LDS via CloudEventIngestor — AD-41)
{
  "specversion": "1.0",
  "type": "lds.session.started",
  "source": "lds",
  "id": "evt-lds-start-1",
  "time": "2026-01-15T10:46:00Z",
  "data": {
    "lds_session_id": "lds-sess-123",
    "session_id": "sess-abc123"
  }
}

# lds.session.ended (from LDS via CloudEventIngestor)
{
  "specversion": "1.0",
  "type": "lds.session.ended",
  "source": "lds",
  "id": "evt-lds-end-1",
  "time": "2026-01-15T11:50:00Z",
  "data": {
    "lds_session_id": "lds-sess-123",
    "session_id": "sess-abc123"
  }
}

# grading.session.completed (from Grading Engine via CloudEventIngestor)
{
  "specversion": "1.0",
  "type": "grading.session.completed",
  "source": "grading-engine",
  "id": "evt-grade-789",
  "time": "2026-01-15T12:02:00Z",
  "data": {
    "grading_session_id": "grade-session-xyz",
    "session_id": "sess-abc123",
    "score": {
      "total": 85,
      "max": 100,
      "breakdown": [
        {"criterion": "Task 1", "points": 25, "max": 30},
        {"criterion": "Task 2", "points": 30, "max": 30},
        {"criterion": "Task 3", "points": 30, "max": 40}
      ]
    },
    "passed": true
  }
}
```

---

## 6. Deployment Architecture

### 6.1 Component Deployment

```
┌─────────────────────────────────────────────────────────────────┐
│                    KUBERNETES CLUSTER                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    Ingress Controller                       │ │
│  └───────────────────────────┬────────────────────────────────┘ │
│                              │                                   │
│         ┌────────────────────┼────────────────────┐             │
│         ▼                    ▼                    ▼             │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐     │
│  │ Control     │      │ Scheduler   │      │ Resource    │     │
│  │ Plane API   │      │ Service     │      │ Controller  │     │
│  │ (3 replicas)│      │ (2 replicas)│      │ (2 replicas)│     │
│  └──────┬──────┘      └─────────────┘      └─────────────┘     │
│         │             (Leader election)   (Leader election)    │
│         ▼                                                        │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                      etcd (State Store)                      ││
│  │                      (3-node cluster)                        ││
│  │  • Instance/Worker state  • Leader election  • Watches      ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    MongoDB (Spec Store)                      ││
│  │                    (3-node replica set)                      ││
│  │  • LabletDefinitions  • WorkerTemplates  • Audit events     ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Redis (UI Session Store)                  ││
│  │  • User authentication sessions (httpOnly cookies)          ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    CloudEvents Bus (External Sink)           ││
│  │  • Event persistence for audit/analytics                    ││
│  │  • External integration (Assessment Platform)               ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ Keycloak │  │ S3/MinIO │  │ OTEL     │  │ Assessment    │   │
│  │          │  │          │  │ Collector│  │ Platform      │   │
│  └──────────┘  └──────────┘  └──────────┘  └───────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Scaling Configuration

| Component | Min Replicas | Max Replicas | Scaling Metric |
|-----------|--------------|--------------|----------------|
| Control Plane API | 2 | 10 | CPU 70% |
| Resource Scheduler | 2 | 5 | Custom (queue depth) |
| Lablet Controller | 2 | 3 | N/A (leader election) |
| Worker Controller | 2 | 3 | N/A (leader election) |

---

## 7. Implementation Phases

### Phase 1: Foundation (Weeks 1-4)

- [ ] Define LabletDefinition aggregate and repository
- [ ] Define LabletSession aggregate and repository (renamed from LabletInstance)
- [ ] Define UserSession, GradingSession, ScoreReport entities and repositories
- [ ] Extend CMLWorker with capacity tracking
- [ ] Implement basic CRUD APIs
- [ ] Implement port allocation service

### Phase 2: Scheduling (Weeks 5-8)

- [ ] Implement Resource Scheduler (basic placement)
- [ ] Implement timeslot management
- [ ] Implement lab YAML rewriting
- [ ] Implement instantiation flow
- [ ] Add SSE updates for instance state

### Phase 3: Auto-Scaling (Weeks 9-12)

- [ ] Implement Lablet Controller (`src/lablet-controller/`)
- [ ] Implement Worker Controller (`src/worker-controller/`)
- [ ] Implement scale-up logic
- [ ] Implement scale-down logic
- [ ] Implement Cloud Provider SPI (AWS)
- [ ] Add worker template configuration

### Phase 4: Assessment Integration (Weeks 13-16)

- [ ] Implement CloudEvent publishing
- [ ] Implement CloudEvent consumption
- [ ] Integrate collection/grading states
- [ ] Add grading result handling

### Phase 5: Production Hardening (Weeks 17-20)

- [ ] Add comprehensive observability
- [ ] Implement warm pool (if needed)
- [ ] Performance testing
- [ ] Documentation
- [ ] UI integration

---

## 8. Architectural Decisions Record

All architectural decisions are documented in the [ADR folder](./adr/README.md).

### Current ADRs

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](./adr/ADR-001-api-centric-state-management.md) | API-Centric State Management | Accepted |
| [ADR-002](./adr/ADR-002-separate-resource-scheduler-service.md) | Separate Resource Scheduler | Accepted |
| [ADR-003](./adr/ADR-003-cloudevents-for-integration.md) | CloudEvents for External Integration | Accepted |
| [ADR-004](./adr/ADR-004-port-allocation-per-worker.md) | Port Allocation per Worker | Accepted |
| [ADR-005](./adr/ADR-005-state-store-architecture.md) | Dual State Store Architecture (etcd + MongoDB) | Proposed |
| [ADR-006](./adr/ADR-006-resource-scheduler-ha-coordination.md) | Scheduler High Availability Coordination | Proposed |
| [ADR-007](./adr/ADR-007-worker-template-seeding.md) | Worker Template Seeding and Management | Accepted |
| [ADR-008](./adr/ADR-008-worker-draining-state.md) | Worker Draining State for Scale-Down | Proposed |

---

## 9. Assessment Integration: Pod Generation

> Based on the Grading Engine API schema (`docs/grading-engine_openapi.json`).

### 9.0 Integration Configuration

**Authentication:** JWT tokens from shared Keycloak instance (same IDP as CCM).

**Deployment:** Grading Engine can be deployed in the same docker-compose stack for development/testing.

```yaml
# docker-compose.yml (example addition)
services:
  grading-engine:
    image: grading-engine:latest
    environment:
      - KEYCLOAK_URL=http://keycloak:8080
      - KEYCLOAK_REALM=lablet-cloud-manager
      - KEYCLOAK_CLIENT_ID=grading-engine
    depends_on:
      - keycloak
```

### 9.1 Pod Schema Mapping

The Grading Engine expects a **Pod** definition when assigning lab resources to an assessment session:

```json
// Grading Engine Pod Schema (confirmed)
{
  "id": "string",
  "devices": [
    {
      "label": "string",
      "hostname": "string",
      "collector": "string",
      "interfaces": [
        {
          "name": "string",
          "protocol": "string",  // ssh, telnet, console, vnc
          "host": "string",      // Worker IP/hostname
          "port": 5041,          // Allocated port
          "authentication": {},   // Credentials object
          "configuration": {}     // Protocol-specific config
        }
      ]
    }
  ]
}
```

### 9.2 CML Lab → Pod Mapping

When a LabletSession reaches READY state, the Lablet Controller generates a Pod definition from:

1. **CML Lab YAML** (nodes with smart_annotations)
2. **Allocated Ports** (from Scheduler)
3. **Worker Details** (hostname/IP)

```python
def generate_pod_from_session(
    session: LabletSession,
    worker: CMLWorker,
    definition: LabletDefinition
) -> Pod:
    """
    Generate Grading Engine Pod from LabletSession in READY state.
    Called by Lablet Controller during reconciliation.

    Mapping:
    - CML node → Pod device
    - smart_annotation serial:PORT → interface (protocol=console)
    - smart_annotation vnc:PORT → interface (protocol=vnc)
    """
    lab_yaml = yaml.safe_load(definition.lab_yaml_cached)

    devices = []
    for node in lab_yaml.get("nodes", []):
        device = Device(
            label=node["label"],
            hostname=node["label"],  # Or extract from node config
            collector="ccm",  # Collection agent identifier
            interfaces=[]
        )

        # Extract interfaces from node tags
        for tag in node.get("tags", []):
            if tag.startswith("serial:"):
                port = int(tag.split(":")[1])
                device.interfaces.append(DeviceInterface(
                    name=f"console-{node['label']}",
                    protocol="console",
                    host=worker.state.hostname,
                    port=port,
                    authentication={"type": "none"},  # CML console auth
                ))
            elif tag.startswith("vnc:"):
                port = int(tag.split(":")[1])
                device.interfaces.append(DeviceInterface(
                    name=f"vnc-{node['label']}",
                    protocol="vnc",
                    host=worker.state.hostname,
                    port=port,
                    authentication={"type": "vnc_password"},
                ))

        if device.interfaces:  # Only include nodes with external interfaces
            devices.append(device)

    return Pod(
        id=session.id,
        devices=devices
    )
```

### 9.3 Pod Assignment Flow

```
Lablet Controller                Grading Engine
 │                                    │
 │ Session reaches READY state        │
 │────────────────────────────────────│
 │                                    │
 │ Generate Pod from Lab YAML         │
 │────────┐                           │
 │        │                           │
 │◀───────┘                           │
 │                                    │
 │ POST /api/v1/sessions/{id}/parts/{partId}/pod
 │ { pod: {...} }                     │
 │───────────────────────────────────▶│
 │                                    │
 │         202 Accepted               │
 │◀───────────────────────────────────│
 │                                    │
 │ CloudEvent: ccm.lablet.session.ready
 │ { pod_assigned: true }             │
 │───────────────────────────────────▶│
```

---

## 10. Open Questions for Implementation

### Resolved

1. ~~**Warm Pool Priority:** Should warm pool implementation be deferred?~~
   → **Deferred** to later optimization phase

2. ~~**Worker Template Management:** Should templates be stored in MongoDB or configuration files?~~
   → **Both**: MongoDB aggregate seeded from config files (see [ADR-007](./adr/ADR-007-worker-template-seeding.md))

3. ~~**Multi-Region Strategy:** How to handle region-specific worker templates?~~
   → **Regional isolation**: One CCM deployment per region, no cross-region coordination

4. ~~**etcd vs MongoDB-only**: Should we prototype with MongoDB Change Streams first?~~
   → **No**, proceed with dual store (etcd + MongoDB) - see [ADR-005](./adr/ADR-005-state-store-architecture.md)

5. ~~**Drain timeout configuration**: Should drain timeout be per-worker-template or global?~~
   → **Per-template**: `drain_timeout_hours` attribute on WorkerTemplate (see [ADR-008](./adr/ADR-008-worker-draining-state.md))

6. ~~**Grading Engine integration**: Confirm Pod assignment API endpoint and authentication?~~
   → **Confirmed**: Device/Interface schema validated, JWT auth on shared Keycloak instance

7. ~~**Audit Log Retention:** How long should CloudEvents be retained?~~
   → **Minimum 3 months, maximum 1 year** (NFR-3.5.5)

8. ~~**Cost estimation**: Should terminated events include cost estimates?~~
   → **No**, cost estimation NOT included in event payload

### Open

None - all questions resolved.

---

## 11. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2026-01-15 | Architecture Team | Initial draft |
| 0.2.0 | 2026-01-15 | Architecture Team | Incorporated feedback: dual store architecture (etcd+MongoDB), worker DRAINING state, scale timing delays, separated ADRs to `/docs/architecture/adr/`, added intermediate CloudEvents, HA coordination with leader election, Pod generation for Grading Engine integration |
| 0.5.0 | 2026-02-18 | Architecture Team | **Major entity model redesign (AD-38 through AD-47-R1):** Renamed LabletInstance → LabletSession, eliminated LabletRecordRun and LabletLabBinding, added UserSession/GradingSession/ScoreReport as separate Entity[str] with own collections. Added READY state between INSTANTIATING and RUNNING. Updated CloudEvents schema (ccm.lablet.instance._→ ccm.lablet.session._). Added LDS/GradingEngine CloudEvent consumption via Neuroglia CloudEventIngestor. Updated Lablet Controller responsibility to include LDS+GradingEngine+CloudEvent proxy. |
| 0.3.0 | 2026-01-16 | Architecture Team | Resolved all open questions: confirmed dual DB approach, drain timeout per-template with admin cancel + instance retry, Grading Engine JWT auth confirmed, audit retention 3mo-1yr, no cost in events |
