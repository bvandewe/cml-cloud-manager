# Runbook: Instance Recovery

| Attribute | Value |
|-----------|-------|
| **Version** | 1.0.0 |
| **Last Updated** | 2026-01-19 |
| **Severity Levels** | P1 (Critical), P2 (High), P3 (Medium) |
| **On-Call Escalation** | Platform Engineering |

---

## Overview

This runbook covers procedures for recovering LabletInstances that are in unexpected or error states, including:

- Stuck state transitions
- Failed instantiation
- Orphaned instances
- Assessment recovery

---

## Instance Lifecycle

```
┌──────────────────────────────────────────────────────────────────────┐
│                     LabletInstance Lifecycle                         │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────┐   ┌───────────┐   ┌──────────────┐   ┌─────────┐       │
│  │ PENDING │──▶│ SCHEDULED │──▶│INSTANTIATING │──▶│ RUNNING │       │
│  └─────────┘   └───────────┘   └──────────────┘   └─────────┘       │
│       │                              │                  │            │
│       │                              │                  ▼            │
│       │                              │           ┌────────────┐      │
│       │                              │           │ COLLECTING │      │
│       │                              │           └────────────┘      │
│       │                              │                  │            │
│       │                              │                  ▼            │
│       │                              │           ┌──────────┐        │
│       │                              │           │ GRADING  │        │
│       │                              │           └──────────┘        │
│       │                              │                  │            │
│       ▼                              ▼                  ▼            │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │                      TERMINATED                          │       │
│  └──────────────────────────────────────────────────────────┘       │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Recovery Scenarios

### 1. Stuck in PENDING

**Severity:** P2 (High)

**Symptoms:**

- Instance in `PENDING` state for > 5 minutes
- Not being picked up by scheduler
- Timeslot may be approaching or passed

**Diagnosis:**

```bash
# Get instance details
curl http://control-plane-api:8080/api/instances/{instance-id} | jq

# Check scheduler logs for this instance
kubectl logs -l app=resource-scheduler | grep {instance-id}

# Check if timeslot is valid
curl http://control-plane-api:8080/api/instances/{instance-id} | jq '.timeslot_start, .timeslot_end'

# Check etcd state
etcdctl get /lcm/instances/{instance-id}/state
```

**Resolution:**

1. Force re-scheduling:

   ```bash
   # Trigger scheduler to re-evaluate
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/reschedule"
   ```

2. Manual assignment (if workers available):

   ```bash
   # Find available worker
   WORKER_ID=$(curl -s http://control-plane-api:8080/api/workers?state=running | jq -r '.[0].id')

   # Manually assign
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/assign" \
     -H "Content-Type: application/json" \
     -d "{\"worker_id\": \"$WORKER_ID\"}"
   ```

3. Terminate and recreate (if timeslot passed):

   ```bash
   curl -X DELETE "http://control-plane-api:8080/api/instances/{instance-id}"

   # Create new instance with updated timeslot
   curl -X POST "http://control-plane-api:8080/api/instances" \
     -H "Content-Type: application/json" \
     -d '{...}'
   ```

### 2. Stuck in INSTANTIATING

**Severity:** P2 (High)

**Symptoms:**

- Instance in `INSTANTIATING` state for > 10 minutes
- Lab import may have failed
- Worker not responding

**Diagnosis:**

```bash
# Get instance and worker details
curl http://control-plane-api:8080/api/instances/{instance-id} | jq '{state, worker_id, lab_id}'

# Check worker health
WORKER_ID=$(curl -s http://control-plane-api:8080/api/instances/{instance-id} | jq -r '.worker_id')
curl http://control-plane-api:8080/api/workers/$WORKER_ID/health

# Check CML API for lab status
curl http://control-plane-api:8080/api/workers/$WORKER_ID/labs | jq '.[] | select(.id == "{lab-id}")'

# Check worker-controller logs
kubectl logs -l app=worker-controller | grep {instance-id}
```

**Resolution:**

1. Check if lab was actually created:

   ```bash
   # Query CML directly through worker
   LAB_ID=$(curl -s http://control-plane-api:8080/api/instances/{instance-id} | jq -r '.lab_id')
   curl http://control-plane-api:8080/api/workers/$WORKER_ID/labs/$LAB_ID
   ```

2. If lab exists, force state transition:

   ```bash
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/transition" \
     -H "Content-Type: application/json" \
     -d '{"target_state": "running"}'
   ```

3. If lab failed, retry instantiation:

   ```bash
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/retry-instantiate"
   ```

4. If worker is unhealthy, reassign to different worker:

   ```bash
   # Terminate on current worker
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/detach"

   # Reschedule to different worker
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/reschedule"
   ```

### 3. Stuck in COLLECTING or GRADING

**Severity:** P2 (High)

**Symptoms:**

- Assessment phase not completing
- Timeout during collection or grading
- Artifacts not being collected

**Diagnosis:**

```bash
# Get instance assessment state
curl http://control-plane-api:8080/api/instances/{instance-id} | jq '.state, .assessment_status'

# Check assessment handler logs
kubectl logs -l app=control-plane-api | grep "assessment\|{instance-id}"

# Check if artifacts exist
curl http://control-plane-api:8080/api/instances/{instance-id}/artifacts
```

**Resolution:**

1. Retry collection:

   ```bash
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/retry-collection"
   ```

2. Force transition to grading (if collection data available):

   ```bash
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/transition" \
     -H "Content-Type: application/json" \
     -d '{"target_state": "grading", "force": true}'
   ```

3. Skip assessment and terminate:

   ```bash
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/skip-assessment"
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/terminate"
   ```

### 4. Orphaned Instance (No Worker)

**Severity:** P3 (Medium)

**Symptoms:**

- Instance has worker_id but worker doesn't exist
- Instance reports as running but lab not found

**Diagnosis:**

```bash
# Check if worker exists
WORKER_ID=$(curl -s http://control-plane-api:8080/api/instances/{instance-id} | jq -r '.worker_id')
curl http://control-plane-api:8080/api/workers/$WORKER_ID | jq '.id, .state'

# Check MongoDB for worker record
mongo lablet_cloud_manager --eval "db.cml_workers.findOne({id: '$WORKER_ID'})"
```

**Resolution:**

1. Clear worker assignment:

   ```bash
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/detach"
   ```

2. Reschedule to new worker:

   ```bash
   curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/reschedule"
   ```

3. Or terminate if no longer needed:

   ```bash
   curl -X DELETE "http://control-plane-api:8080/api/instances/{instance-id}"
   ```

### 5. Bulk Recovery (Multiple Instances)

**Severity:** P1 (Critical) - if many instances affected

**Symptoms:**

- Multiple instances in same error state
- Systemic failure (worker, network, etc.)

**Resolution:**

```bash
# Find all stuck instances
STUCK_INSTANCES=$(curl -s http://control-plane-api:8080/api/instances?state=instantiating \
  | jq -r '.[] | select(.updated_at < (now - 600 | todate)) | .id')

# Bulk retry
for id in $STUCK_INSTANCES; do
  echo "Retrying instance: $id"
  curl -X POST "http://control-plane-api:8080/api/instances/$id/retry-instantiate"
  sleep 1
done

# Or bulk terminate
for id in $STUCK_INSTANCES; do
  echo "Terminating instance: $id"
  curl -X DELETE "http://control-plane-api:8080/api/instances/$id"
  sleep 1
done
```

---

## State Synchronization

When instance state is inconsistent between MongoDB, etcd, and CML:

### Sync from CML (Source of Truth for Lab State)

```bash
# Force sync instance state from CML
curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/sync"

# Sync all instances for a worker
curl -X POST "http://control-plane-api:8080/api/workers/{worker-id}/sync-instances"
```

### Sync from MongoDB (Source of Truth for Instance Records)

```bash
# Rebuild etcd state from MongoDB
curl -X POST "http://control-plane-api:8080/api/admin/rebuild-etcd-state"
```

---

## Prevention

### Monitoring Alerts

```yaml
groups:
  - name: instances
    rules:
      - alert: InstanceStuckPending
        expr: time() - lcm_instance_created_timestamp{state="pending"} > 300
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Instance stuck in PENDING state"

      - alert: InstanceStuckInstantiating
        expr: time() - lcm_instance_state_transition_timestamp{to_state="instantiating"} > 600
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Instance stuck in INSTANTIATING state"

      - alert: HighInstanceFailureRate
        expr: rate(lcm_instance_state_transitions_total{to_state="terminated", reason="error"}[1h]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High instance failure rate detected"
```

### Automated Recovery

Consider implementing automated recovery for common issues:

```python
# Example: Automated stuck instance recovery job
@backgroundjob(task_type="recurrent", interval=300)
class StuckInstanceRecoveryJob(BackgroundJobBase):
    async def execute_async(self, context):
        stuck_instances = await self.find_stuck_instances()
        for instance in stuck_instances:
            if instance.stuck_duration > timedelta(minutes=10):
                await self.retry_or_terminate(instance)
```

---

## Audit Trail

All recovery actions should be logged:

```bash
# View recovery audit log
kubectl logs -l app=control-plane-api | grep "RECOVERY\|force_transition\|manual"

# Check Prometheus for recovery actions
curl http://prometheus:9090/api/v1/query?query=lcm_instance_recovery_actions_total
```

---

## Related Runbooks

- [Scheduler Troubleshooting](./scheduler-troubleshooting.md)
- [Worker Troubleshooting](./worker-troubleshooting.md)
- [Assessment Troubleshooting](./assessment-troubleshooting.md)
