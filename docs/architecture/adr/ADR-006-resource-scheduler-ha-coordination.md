# ADR-006: Resource Scheduler High Availability Coordination

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-01-16 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-002](./ADR-002-separate-resource-scheduler-service.md), [ADR-005](./ADR-005-state-store-architecture.md) |

## Context

With multiple Resource Scheduler replicas for HA, we need to prevent:

1. **Duplicate scheduling**: Two schedulers assigning the same instance
2. **Lost assignments**: Instance falls through cracks between schedulers
3. **Conflicting decisions**: Schedulers making incompatible placements

Options considered:

1. **Leader election** - Single active resource scheduler at a time
2. **Optimistic locking** - First writer wins via version checks
3. **Work partitioning** - Each scheduler handles subset of instances
4. **Distributed lock per instance** - Fine-grained locking

## Decision

**Use leader election for Scheduler (single active leader).**

Only the leader resource scheduler makes placement decisions. Other replicas are hot standbys that take over if leader fails.

## Rationale

### Why Leader Election?

- **Simplicity**: No distributed coordination per instance
- **Deterministic**: Clear ownership of scheduling responsibility
- **Proven pattern**: Used by Kubernetes scheduler
- **etcd native**: Built-in leader election support

### Why Not Optimistic Locking?

- Race conditions under high load
- Wasted work when multiple schedulers compute same placement
- Complexity in retry logic

### Why Not Work Partitioning?

- Partition rebalancing on scheduler failure
- Complexity in partition assignment
- Overkill for expected scale (<1000 instances)

## Consequences

### Positive

- Simple mental model (one scheduler active)
- No per-instance locking overhead
- Fast failover via etcd lease expiration

### Negative

- Single scheduler bottleneck (mitigated by fast placement algorithm)
- Failover latency (etcd lease TTL, typically 10-15 seconds)

## Implementation

### Leader Election with etcd

```python
class SchedulerLeaderElection:
    def __init__(self, etcd_client, instance_id: str):
        self.etcd = etcd_client
        self.instance_id = instance_id
        self.lease_ttl = 15  # seconds
        self.leader_key = "/lcm/scheduler/leader"

    async def campaign(self):
        """Attempt to become leader."""
        lease = await self.etcd.lease(self.lease_ttl)

        try:
            # Try to create leader key (fails if exists)
            await self.etcd.put(
                self.leader_key,
                self.instance_id,
                lease=lease
            )
            return True  # We are leader
        except etcd.KeyExistsError:
            return False  # Someone else is leader

    async def maintain_leadership(self):
        """Keep lease alive while leader."""
        while True:
            await self.lease.refresh()
            await asyncio.sleep(self.lease_ttl / 3)

    async def watch_leader(self):
        """Watch for leader changes."""
        async for event in self.etcd.watch(self.leader_key):
            if event.type == "DELETE":
                # Leader lost, try to become leader
                await self.campaign()
```

### Scheduler Lifecycle

```
1. Scheduler starts
2. Attempts leader election (campaign)
3. If leader:
   a. Start scheduling loop
   b. Maintain leadership (lease refresh)
4. If not leader:
   a. Watch leader key
   b. On leader loss, attempt election
5. On shutdown:
   a. Release lease
   b. Another replica becomes leader
```

### Failover Timeline

```
T+0:    Leader crashes
T+0-15: Lease TTL expires (configurable)
T+15:   etcd deletes leader key
T+15:   Standby detects deletion via watch
T+15-16: Standby campaigns and wins
T+16:   New leader starts scheduling

Total failover: ~15-20 seconds
```

## Resource Controller HA

Same pattern applies to Resource Controller:

- Leader election at `/lcm/controller/leader`
- Only leader runs reconciliation loop
- Hot standby replicas

## Trade-offs vs Scale

| Scale | Recommendation |
|-------|----------------|
| <100 instances | Leader election sufficient |
| 100-1000 instances | Leader election, optimize algorithm |
| >1000 instances | Consider work partitioning |

Given expected scale (<1000 concurrent instances), leader election is appropriate.

## Open Questions

1. What lease TTL balances failover speed vs network flakiness?
2. Should standby schedulers pre-warm caches (read state)?
3. Should we expose leader status in health checks?
