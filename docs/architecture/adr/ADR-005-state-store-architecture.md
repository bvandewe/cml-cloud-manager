# ADR-005: Dual State Store Architecture (etcd + MongoDB)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-01-16 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-001](./ADR-001-api-centric-state-management.md), [ADR-002](./ADR-002-separate-resource-scheduler-service.md) |

## Context

The system requires:

1. **Reactive state propagation**: Scheduler and Controller need real-time notification of state changes
2. **Document storage**: Complex aggregate structures (LabletDefinition, Worker Templates)
3. **High availability**: No single point of failure for state storage

Options considered:

1. **MongoDB only** - Use MongoDB change streams for reactivity
2. **etcd only** - Store all state in etcd (key-value)
3. **Dual store** - etcd for state/coordination, MongoDB for documents
4. **PostgreSQL + LISTEN/NOTIFY** - Relational DB with notification

## Decision

**Use dual store architecture: etcd for state coordination + MongoDB for document storage.**

| Store | Purpose | Data |
|-------|---------|------|
| **etcd** | State coordination, watching | Instance state, Worker state, Port allocations |
| **MongoDB** | Document storage, specs | LabletDefinitions, Worker Templates, Audit logs |

## Rationale

### Why etcd?

- **Native watch**: Built-in watch mechanism with guaranteed delivery
- **Strong consistency**: Linearizable reads/writes
- **Leader election**: Built-in primitives for Scheduler HA
- **Kubernetes proven**: Battle-tested at scale

### Why MongoDB?

- **Document model**: Natural fit for complex aggregates (LabletDefinition schema)
- **Rich queries**: Filtering, aggregation for analytics
- **Existing integration**: Neuroglia MotorRepository already implemented
- **Schema flexibility**: Evolving document structures

### Why not MongoDB alone?

- Change streams have limitations (cursor timeout, resumption complexity)
- No built-in leader election primitives
- Watch granularity less precise than etcd

### Why not etcd alone?

- Key-value model awkward for complex documents
- No rich query capabilities
- Storage limits (default 2GB)

## Consequences

### Positive

- Best tool for each job
- Proven patterns from Kubernetes ecosystem
- Scheduler/Controller get reliable state watches
- LabletDefinitions stored in natural document format

### Negative

- Operational complexity of two data stores
- Data synchronization between stores (if needed)
- Learning curve for etcd operations

### Risks

- Consistency between etcd and MongoDB if same data in both
- etcd cluster management overhead

## Data Distribution

### etcd Keys

```
/lcm/instances/{id}/state          # LabletInstance current state
/lcm/instances/{id}/worker         # Assigned worker ID
/lcm/workers/{id}/state            # Worker state (running, draining, stopped)
/lcm/workers/{id}/capacity         # Current available capacity
/lcm/workers/{id}/ports            # Port allocation bitmap
/lcm/scheduler/leader              # Leader election key
/lcm/controller/leader             # Leader election key
```

### MongoDB Collections

```
lablet_definitions    # Full LabletDefinition documents
worker_templates      # WorkerTemplate documents
audit_events          # CloudEvents for audit trail
```

## Implementation Notes

### Watch Pattern for Scheduler

```python
async def watch_pending_instances():
    """Watch for new pending instances."""
    async for event in etcd.watch_prefix("/lcm/instances/"):
        if event.type == "PUT" and event.value["state"] == "PENDING":
            await schedule_instance(event.key.split("/")[3])
```

### State Update Flow

```
1. API receives mutation request
2. API validates and writes to etcd (state)
3. API writes to MongoDB (if document update)
4. etcd notifies watchers (Scheduler, Controller)
5. Scheduler/Controller process state change
6. Scheduler/Controller call API for mutations
```

## Alternatives Considered

### Redis + MongoDB

- Redis pub/sub less reliable than etcd watch
- No strong consistency guarantees
- Would work but etcd more robust

### Single MongoDB with Change Streams

- Simpler operationally
- Change stream resumption complexity
- No built-in leader election
- **Could reconsider if etcd overhead too high**

## Resolved Questions

1. ~~Should Redis session store migrate to etcd for UI sessions?~~
   → **No**, keep Redis for UI sessions (simpler TTL management, separation of concerns)

2. ~~What is the etcd cluster sizing for expected load?~~
   → TBD during implementation phase based on expected instance count

3. ~~Should we prototype with MongoDB-only first and add etcd if needed?~~
   → **No**, proceed with dual store architecture as designed
