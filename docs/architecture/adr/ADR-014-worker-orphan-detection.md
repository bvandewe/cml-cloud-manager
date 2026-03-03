# ADR-014: Worker Orphan Detection and Garbage Collection

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-02-06 |
| **Deciders** | Architecture Team |
| **Related ADRs** | [ADR-001](./ADR-001-api-centric-state-management.md), [ADR-012](./ADR-012-dynamic-region-configuration.md) |

## Context

The worker-controller's discovery service scans AWS EC2 for instances matching the configured AMI pattern and imports them into the Control Plane API. However, the current implementation is **import-only** and does not detect workers that have been terminated externally (via AWS Console, CLI, or TTL policies).

### Problem Statement

| Scenario | Current Behavior | Expected Behavior |
|----------|------------------|-------------------|
| Worker terminated in AWS Console | DB shows RUNNING | DB should show TERMINATED |
| Worker terminated by AWS auto-scaling | DB shows RUNNING | DB should show TERMINATED |
| Worker instance deleted externally | DB shows RUNNING | DB should show TERMINATED |

**Evidence from logs:**

```
Discovery found: 3 EC2 instances
Database has: 13 workers
Reconciliation: "Found 0 workers needing reconciliation (of 13 total)"
```

10 workers in the database no longer exist in EC2 but still show as RUNNING.

### Scheduler Trust Model Issue

The Resource Scheduler trusts the database status when making placement decisions:

```python
# PlacementEngine (placement_engine.py)
EXCLUDED_STATUSES = {"stopping", "stopped", "shutting-down", "terminated", "failed"}

# Only considers RUNNING workers
if status != "running":
    continue
```

**Risk:** If a worker's EC2 instance was terminated externally but the DB still shows "RUNNING", the scheduler may assign lablet instances to non-existent workers, causing immediate scheduling failures.

### Current Architecture Gap

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Current Discovery Flow                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   EC2 (3 instances)           Control Plane API (13 workers)                │
│                                                                             │
│   ┌──────────────┐           ┌──────────────────────────────┐               │
│   │ Instance A   │──Import──▶│ Worker A (RUNNING) ✓         │               │
│   │ Instance B   │──Import──▶│ Worker B (RUNNING) ✓         │               │
│   │ Instance C   │──Import──▶│ Worker C (RUNNING) ✓         │               │
│   └──────────────┘           │ Worker D (RUNNING) ✗ ORPHAN  │               │
│                              │ Worker E (RUNNING) ✗ ORPHAN  │               │
│                              │ ... 8 more orphans ...       │               │
│                              └──────────────────────────────┘               │
│                                                                             │
│   Legend: ✓ = Exists in EC2    ✗ = Orphan (EC2 terminated)                  │
│                                                                             │
│   PROBLEM: No mechanism to detect/cleanup orphaned workers                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Decision

**Implement orphan detection as a garbage collection step within the discovery loop.**

> **Note:** Discovery was originally in a standalone `WorkerDiscoveryService`.
> Per AD-020, it has been consolidated into `WorkerReconciler._run_discovery_loop()`.

### Design: Discovery-Based Garbage Collection

After each discovery run, the service will:

1. Get all workers from DB for the region with status NOT in (TERMINATED, PENDING)
2. Compare against the set of discovered EC2 instance IDs
3. For workers not in the discovered set, verify via direct EC2 API call
4. If EC2 confirms instance doesn't exist or is terminated, mark worker as TERMINATED

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        New Discovery + GC Flow                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   WorkerReconciler._run_discovery_loop()                                    │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ Step 1: DISCOVERY                                                   │   │
│   │   - Scan EC2 for instances matching AMI pattern                     │   │
│   │   - Submit new instances to Control Plane API for import            │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                         │
│                                   ▼                                         │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ Step 2: GARBAGE COLLECTION (NEW)                                    │   │
│   │   - Fetch DB workers for region (non-terminated)                    │   │
│   │   - Identify orphans (in DB but not in discovered set)              │   │
│   │   - Verify each orphan via EC2 describe-instances                   │   │
│   │   - Mark verified orphans as TERMINATED                             │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Soft Delete (TERMINATED status)

Workers will be marked as `TERMINATED` rather than deleted from the database.

**Rationale:**

- Maintains audit trail for historical analysis
- Consistent with existing lifecycle state machine
- PlacementEngine already excludes TERMINATED workers
- Allows potential "resurrection" if instance comes back (edge case)

### No Grace Period

Orphan detection will immediately mark workers as TERMINATED without a grace period.

**Rationale:**

- Discovery runs every 5 minutes - that's already enough delay
- EC2 `describe-instances` is authoritative - if empty, instance is gone
- **Speed is critical** to prevent bad scheduling decisions
- AWS terminates instances synchronously; no "pending termination" state that could cause false positives

### Implementation Components

#### 1. WorkerReconciler Discovery Loop Enhancement

```python
async def _run_discovery(self, discovery_settings: CachedDiscoverySettings) -> None:
    """Execute discovery + garbage collection for all regions."""

    for region in discovery_settings.regions:
        # Existing: Discovery and import
        discovered, imported = await self._discover_in_region(region, ami_pattern)

        # NEW: Garbage collection
        await self._garbage_collect_orphans(region, discovered_instance_ids)
```

#### 2. Garbage Collection Logic

```python
async def _garbage_collect_orphans(
    self,
    region: str,
    discovered_instance_ids: set[str]
) -> int:
    """Detect and mark orphaned workers as TERMINATED.

    Args:
        region: AWS region that was scanned
        discovered_instance_ids: Set of EC2 instance IDs found during discovery

    Returns:
        Number of orphans marked as terminated
    """
    # Get all non-terminated workers for this region from Control Plane API
    db_workers = await self._api.get_workers(
        aws_region=region,
        exclude_statuses=["TERMINATED", "PENDING"]
    )

    orphan_count = 0
    for worker in db_workers:
        instance_id = worker.get("ec2_instance_id")
        if not instance_id:
            continue

        # Check if instance was in discovery results
        if instance_id in discovered_instance_ids:
            continue  # Not an orphan

        # Verify via direct EC2 API call (handles edge cases)
        state = await self._ec2.get_instance_state(instance_id)

        if state is None or state.state == "terminated":
            # Confirmed orphan - mark as TERMINATED
            await self._api.mark_worker_terminated(
                worker_id=worker["id"],
                reason="EC2 instance not found during discovery"
            )
            orphan_count += 1
            logger.info(f"🗑️ Marked orphan worker {worker['id']} as TERMINATED")

    return orphan_count
```

#### 3. Control Plane API Endpoint

Add or use existing endpoint for marking workers terminated:

```python
# Option A: New dedicated endpoint
POST /api/internal/workers/{id}/mark-terminated
{
    "reason": "EC2 instance not found during discovery"
}

# Option B: Use existing status update (preferred for simplicity)
POST /api/internal/workers/{id}/status
{
    "status": "TERMINATED",
    "terminated_by": "discovery-gc",
    "terminated_reason": "EC2 instance not found during discovery"
}
```

## Alternatives Considered

### Alternative A: Reconciler-Based Orphan Scan

Add periodic orphan detection to the WorkerReconciler instead of discovery.

**Rejected because:**

- Reconciler's responsibility is lifecycle management, not discovery
- Would duplicate EC2 querying logic
- Reconciler's `list_resources()` only fetches workers needing action, not all workers
- Blurs separation of concerns

### Alternative B: Implement Both Discovery + Reconciler Detection

Run orphan detection in both services for redundancy.

**Rejected because:**

- Unnecessary complexity
- Discovery runs frequently enough (5 minutes)
- If discovery is disabled, operator likely wants manual control

### Alternative C: Hard Delete Orphaned Workers

Delete worker records from MongoDB instead of soft delete.

**Rejected because:**

- Loses audit trail
- Cannot analyze historical worker usage
- Complicates potential resurrection scenarios

## Consequences

### Positive

- **Scheduler reliability**: Prevents scheduling to non-existent workers
- **Data accuracy**: DB reflects actual EC2 state
- **Operator confidence**: UI shows accurate worker inventory
- **Cost visibility**: Accurate count of running workers for billing

### Negative

- **5-minute detection latency**: Orphans detected only on discovery runs
- **Requires discovery enabled**: If discovery disabled, orphan detection stops
- **Additional API calls**: Each discovery run queries Control Plane API for workers

### Mitigations

1. **Latency**: Acceptable for current use case; can reduce interval if needed
2. **Discovery dependency**: Document that discovery should stay enabled for orphan detection
3. **API load**: Queries are lightweight; add caching if needed

## Implementation Checklist

!!! note "Status: Likely Complete (Pending Verification)"
    Implementation was completed but checklist was not updated. Verify against codebase.

- [x] Enhance discovery loop to call GC after import (now in `WorkerReconciler._run_discovery_loop()`)
- [x] Implement garbage collection in discovery loop
- [x] Add `get_workers(aws_region, exclude_statuses)` filter to Control Plane API
- [x] Update discovery stats to include `orphans_terminated` count
- [x] Add logging for orphan detection
- [ ] Write unit tests for GC logic (verify coverage)
- [ ] Write integration test for full discovery + GC flow (verify coverage)
- [x] Update worker-controller README with orphan detection docs

## References

- [ADR-001: API-Centric State Management](./ADR-001-api-centric-state-management.md)
- [ADR-012: Dynamic Region Configuration](./ADR-012-dynamic-region-configuration.md)
- [WorkerReconciler._run_discovery_loop()](../../../src/worker-controller/application/hosted_services/worker_reconciler.py)
- [PlacementEngine](../../../src/resource-scheduler/application/services/placement_engine.py)
