# ADR-008: Worker Draining State for Scale-Down

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-01-16 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-002](./ADR-002-separate-resource-scheduler-service.md) |

## Context

When scaling down workers, we must ensure running LabletInstances complete gracefully. Simply stopping a worker with active sessions would disrupt users.

Options considered:

1. **Immediate stop** - Wait for instances to terminate, then stop worker
2. **Draining state** - Mark worker as draining, prevent new assignments, wait for completion
3. **Instance migration** - Move running instances to another worker (complex)

## Decision

**Introduce DRAINING state for Workers to enable graceful scale-down.**

A draining worker:

- Continues running existing instances
- Does NOT accept new instance assignments
- Transitions to STOPPED when all instances terminate

## Rationale

### Benefits

- **Graceful degradation**: Running sessions complete normally
- **Simple implementation**: No instance migration complexity
- **Predictable behavior**: Clear state machine for operations
- **Cost optimization**: Still enables scale-down without disruption

### Trade-offs

- Draining period can be long (up to max session duration)
- Capacity temporarily reduced during draining

## Worker State Machine

```
                                    ┌─────────────────┐
                                    │                 │
                                    ▼                 │
┌─────────┐    ┌─────────┐    ┌──────────┐    ┌──────────┐
│ PENDING │───▶│ RUNNING │◀──▶│ DRAINING │───▶│ STOPPING │
└─────────┘    └─────────┘    └──────────┘    └──────────┘
                    │       (admin cancel)▲      │                 │
                    │              │              │                 ▼
                    │              │              │          ┌──────────┐
                    └──────────────┴──────────────┴────────▶│ STOPPED  │
                                              └──────────┘
                                                    │
                                                    ▼
                                              ┌────────────┐
                                              │ TERMINATED │
                                              └────────────┘
```

**Note:** Admins can cancel draining and return worker to RUNNING state.

### State Definitions

| State | Can Accept Instances | Running Instances | Action | Transitions To |
|-------|---------------------|-------------------|--------|----------------|
| PENDING | No | No | Starting up | RUNNING |
| RUNNING | Yes | Yes/No | Normal operation | DRAINING, STOPPING |
| DRAINING | **No** | Yes | Graceful wind-down | STOPPING, **RUNNING** (admin cancel) |
| STOPPING | No | No | EC2 stop in progress | STOPPED |
| STOPPED | No | No | EC2 stopped (can restart) | RUNNING, TERMINATED |
| TERMINATED | No | No | EC2 terminated | (terminal) |

## Consequences

### Positive

- No session disruption during scale-down
- Clear operational model
- Scheduler simply excludes draining workers

### Negative

- Extended drain periods reduce elasticity
- Must handle long-running sessions (configurable max duration)

## Implementation

### Scheduler Filter Update

```python
def filter_eligible_workers(workers: list[CMLWorker]) -> list[CMLWorker]:
    """Filter workers that can accept new instances."""
    return [
        w for w in workers
        if w.state.status == CMLWorkerStatus.RUNNING
        # Exclude DRAINING workers
        and w.state.status != CMLWorkerStatus.DRAINING
    ]
```

### Resource Controller Drain Logic

```python
async def initiate_drain(worker_id: str) -> None:
    """Begin draining a worker."""
    worker = await worker_repository.get_by_id_async(worker_id)

    # Transition to draining
    worker.start_draining()
    await worker_repository.update_async(worker)

    # Emit event for audit
    await event_publisher.publish(WorkerDrainingEvent(
        worker_id=worker_id,
        running_instances=len(worker.state.instance_ids)
    ))


async def check_drain_completion(worker_id: str) -> None:
    """Check if draining worker can be stopped."""
    worker = await worker_repository.get_by_id_async(worker_id)

    if worker.state.status != CMLWorkerStatus.DRAINING:
        return

    # Get running instances on this worker
    instances = await instance_repository.get_by_worker_async(worker_id)
    running = [i for i in instances if i.state.state in ACTIVE_STATES]

    if not running:
        # All instances done, proceed to stop
        await stop_worker(worker_id)
```

### Drain Timeout

**Drain timeout is configurable per WorkerTemplate:**

```python
# WorkerTemplate includes drain_timeout_hours
@dataclass
class WorkerTemplateState:
    # ... other fields ...
    drain_timeout_hours: int = 4  # Default: 4 hours, configurable per template


async def enforce_drain_timeout(worker_id: str) -> None:
    """Force stop after drain timeout (per-template configuration)."""
    worker = await worker_repository.get_by_id_async(worker_id)

    if worker.state.status != CMLWorkerStatus.DRAINING:
        return

    # Get timeout from worker's template
    template = await template_repository.get_by_name_async(worker.state.template_name)
    timeout_hours = template.state.drain_timeout_hours

    drain_started = worker.state.drain_started_at
    if datetime.now(timezone.utc) - drain_started > timedelta(hours=timeout_hours):
        log.warning(f"Drain timeout ({timeout_hours}h) for worker {worker_id}, forcing stop")
        # Force terminate remaining instances
        await terminate_worker_instances(worker_id)
        await stop_worker(worker_id)
```

### Admin Cancel Draining

```python
async def cancel_drain(worker_id: str, admin_id: str) -> None:
    """Admin cancels draining, returning worker to RUNNING state."""
    worker = await worker_repository.get_by_id_async(worker_id)

    if worker.state.status != CMLWorkerStatus.DRAINING:
        raise InvalidStateTransition(f"Cannot cancel drain from {worker.state.status}")

    # Transition back to RUNNING
    worker.cancel_draining(cancelled_by=admin_id)
    await worker_repository.update_async(worker)

    # Emit event for audit
    await event_publisher.publish(WorkerDrainCancelledEvent(
        worker_id=worker_id,
        cancelled_by=admin_id,
        reason="admin_action"
    ))

    log.info(f"Worker {worker_id} drain cancelled by {admin_id}, returned to RUNNING")
```

### Instance Failure During Drain

**Instances on draining workers that fail should be retried** (they are already scheduled to a running-though-draining worker):

```python
async def handle_instance_failure_on_draining_worker(
    instance_id: str,
    worker_id: str,
    failure_reason: str
) -> None:
    """Retry failed instance on draining worker (same worker)."""
    worker = await worker_repository.get_by_id_async(worker_id)
    instance = await instance_repository.get_by_id_async(instance_id)

    # Only retry if worker is still DRAINING (not yet STOPPING)
    if worker.state.status != CMLWorkerStatus.DRAINING:
        log.warning(f"Worker {worker_id} no longer draining, cannot retry {instance_id}")
        await terminate_instance(instance_id, reason="worker_stopped_during_retry")
        return

    # Retry on same worker (already scheduled there)
    retry_count = instance.state.retry_count or 0
    max_retries = 3

    if retry_count < max_retries:
        log.info(f"Retrying instance {instance_id} on draining worker {worker_id} (attempt {retry_count + 1})")
        instance.increment_retry()
        instance.transition_to(LabletInstanceState.INSTANTIATING)
        await instance_repository.update_async(instance)
        # Re-trigger instantiation
        await instantiate_instance(instance_id)
    else:
        log.error(f"Instance {instance_id} exceeded max retries on draining worker {worker_id}")
        await terminate_instance(instance_id, reason="max_retries_exceeded")
```

## Scale-Down Decision Flow

```
1. Resource Controller identifies idle worker candidate
2. Check: Any running instances?
   - No → Stop worker immediately
   - Yes → Continue
3. Check: Any scheduled instances approaching timeslot?
   - Yes → Skip (worker still needed)
   - No → Continue
4. Initiate DRAINING state
5. Scheduler stops assigning to this worker
6. Monitor instance completion
7. On last instance termination → Stop worker
8. On drain timeout → Force stop (with notification)
```

## Resolved Questions

1. ~~Should drain timeout be configurable per worker template?~~
   → **Yes**, `drain_timeout_hours` is a WorkerTemplate attribute (default: 4 hours)

2. ~~Should admins be able to cancel draining and return to RUNNING?~~
   → **Yes**, via `POST /api/v1/workers/{id}/cancel-drain` endpoint

3. ~~How to handle instance failures during drain (retry vs abandon)?~~
   → **Retry** on same worker (up to 3 attempts) since instances are already scheduled there
