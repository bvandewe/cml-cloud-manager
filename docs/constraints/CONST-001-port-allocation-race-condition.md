# CONST-001: Port Allocation Race Condition

| Attribute | Value |
|-----------|-------|
| **ID** | CONST-001 |
| **Component** | Port Allocation Service, etcd State Store |
| **Severity** | Medium |
| **Status** | Known |
| **Created** | 2026-01-16 |
| **Updated** | 2026-01-16 |

## Description

The current port allocation implementation uses a read-then-write pattern which can result in race conditions under high concurrent load. Multiple concurrent allocation requests may read the same "available ports" state and attempt to allocate the same port numbers.

## Impact

- Under high concurrency, some port allocation requests may fail with conflict errors
- Failed allocations return `PortAllocationResult.success = False` with error message indicating conflict
- Only affects scenarios where multiple lablet instances are being allocated simultaneously on the same worker
- Does **not** cause port collisions (conflict detection prevents actual duplicates)

## Root Cause

The `EtcdStateStore.allocate_instance_ports()` method follows this pattern:

```python
# 1. Read current allocations
current = await self.get_worker_ports(worker_id)

# 2. Check for conflicts
for port in ports.values():
    if port in used_ports:
        return False  # Conflict detected

# 3. Write new allocation
# ⚠️ Race window: between read and write, another request may have written
await self.set_worker_ports(worker_id, allocations)
```

Without atomic compare-and-swap (CAS) operations, concurrent requests can interleave between steps 1 and 3.

## Current Behavior

1. Concurrent allocation requests proceed independently
2. First request to complete write wins
3. Subsequent requests detect conflict when they read updated state
4. Conflict is reported as failure (not silent corruption)
5. Caller can retry allocation

**Test Evidence**: Integration test `test_concurrent_allocations` documents this behavior:

- Some concurrent allocations succeed
- Failed allocations report "conflict" error
- No duplicate port assignments occur

## Workaround / Mitigation

Current mitigations in place:

1. **Conflict Detection**: The system detects when ports are already allocated and returns failure
2. **Retry Logic**: Callers should implement retry with backoff for failed allocations
3. **Sequential Scheduling**: The scheduler can serialize allocation requests per worker

Recommended caller pattern:

```python
async def allocate_with_retry(service, worker_id, instance_id, template, max_retries=3):
    for attempt in range(max_retries):
        result = await service.allocate_ports(worker_id, instance_id, template)
        if result.success:
            return result
        if "conflict" not in result.error.lower():
            raise PortAllocationError(result.error)  # Non-retryable error
        await asyncio.sleep(0.1 * (attempt + 1))  # Backoff
    raise PortAllocationError("Max retries exceeded")
```

## Resolution Path

**Recommended Fix**: Implement etcd transactions for atomic compare-and-swap

```python
async def allocate_instance_ports_atomic(
    self,
    worker_id: str,
    instance_id: str,
    ports: dict[str, int],
) -> bool:
    """Atomically allocate ports using etcd transaction."""
    key = self.WORKER_PORTS_KEY.format(id=worker_id)

    # Use etcd transaction API
    # POST /v3/kv/txn with compare-and-swap semantics
    response = await self._etcd._request(
        "POST",
        "/v3/kv/txn",
        json={
            "compare": [{
                "key": base64.b64encode(key.encode()).decode(),
                "result": "EQUAL",
                "target": "MOD",
                "mod_revision": current_revision,  # Only succeed if unchanged
            }],
            "success": [{
                "request_put": {
                    "key": base64.b64encode(key.encode()).decode(),
                    "value": base64.b64encode(new_value.encode()).decode(),
                }
            }],
            "failure": []
        }
    )
    return response.get("succeeded", False)
```

**Effort Estimate**: 4-8 hours
**Priority**: Medium (implement when concurrent allocation becomes a bottleneck)

## Related

- **Code**: `integration/services/etcd_state_store.py` - `allocate_instance_ports()` method
- **Code**: `application/services/port_allocation_service.py` - `allocate_ports()` method
- **Tests**: `tests/integration/test_port_allocation_integration.py` - `test_concurrent_allocations`
- **ADR**: ADR-005 (etcd for State Coordination)
- **Task**: Phase 1, Task 1.7 (Port Allocation Service)
