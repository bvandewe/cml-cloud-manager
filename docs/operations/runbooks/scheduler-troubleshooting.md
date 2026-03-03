# Runbook: Scheduler Troubleshooting

| Attribute | Value |
|-----------|-------|
| **Version** | 1.0.0 |
| **Last Updated** | 2026-01-19 |
| **Severity Levels** | P1 (Critical), P2 (High), P3 (Medium) |
| **On-Call Escalation** | Platform Engineering |

---

## Overview

This runbook covers troubleshooting procedures for the Resource Scheduler component, which is responsible for:

- Placing LabletInstances on available workers
- Triggering scale-up when capacity is insufficient
- Managing scheduling decisions and worker assignment

---

## Symptoms

### 1. Instances Stuck in PENDING State

**Severity:** P2 (High)

**Symptoms:**

- Instances remain in `PENDING` state for > 5 minutes
- Metrics show increasing `lcm_lablet_instances_active{state="pending"}` gauge
- No scheduling decisions being made (`lcm_scheduling_decisions_total` not increasing)

**Potential Causes:**

- Scheduler not running or not leader
- No available workers with sufficient capacity
- etcd connectivity issues
- Worker health checks failing

### 2. Scheduler Not Making Placement Decisions

**Severity:** P2 (High)

**Symptoms:**

- `lcm_scheduling_decisions_total` counter not increasing
- Scheduler logs show no activity
- Instances accumulating in pending queue

**Potential Causes:**

- Scheduler leader election failed
- Background job not running
- Exception in scheduling loop

### 3. Workers Not Receiving Assignments

**Severity:** P2 (High)

**Symptoms:**

- Scheduling decisions being made but workers not receiving labs
- `lcm_instance_state_transitions_total{to_state="instantiating"}` not matching scheduling decisions
- Workers showing available capacity but not being used

**Potential Causes:**

- CloudEvent publishing failing
- Worker controller not processing events
- Network partition between services

---

## Diagnosis Steps

### Step 1: Check Scheduler Status

```bash
# Check if scheduler is running
kubectl get pods -l app=resource-scheduler -n lcm

# Check scheduler logs for errors
kubectl logs -l app=resource-scheduler -n lcm --tail=100 | grep -i error

# Check scheduler health endpoint
curl http://resource-scheduler:8080/health
```

### Step 2: Verify Leader Election

```bash
# Check etcd for leader key
etcdctl get /lcm/scheduler/leader

# Verify leader is current pod
etcdctl get /lcm/scheduler/leader --print-value-only

# Check lease status
etcdctl lease list
etcdctl lease timetolive <lease-id>
```

### Step 3: Check Worker Availability

```bash
# Query available workers
curl http://control-plane-api:8080/api/workers?state=running

# Check worker capacity
curl http://control-plane-api:8080/api/workers/{worker-id}/resources

# Verify workers are healthy
for worker in $(curl -s http://control-plane-api:8080/api/workers | jq -r '.[].id'); do
  echo "Worker: $worker"
  curl -s "http://control-plane-api:8080/api/workers/$worker" | jq '.state, .resources'
done
```

### Step 4: Check etcd Connectivity

```bash
# Test etcd connection
etcdctl endpoint health

# Check etcd cluster status
etcdctl endpoint status --cluster

# Verify scheduler can reach etcd
kubectl exec -it deploy/resource-scheduler -- curl http://etcd:2379/health
```

### Step 5: Check Pending Instances

```bash
# Count pending instances
curl http://control-plane-api:8080/api/instances?state=pending | jq 'length'

# Get oldest pending instances
curl "http://control-plane-api:8080/api/instances?state=pending&sort=created_at" | jq '.[0:5]'

# Check instance details
curl http://control-plane-api:8080/api/instances/{instance-id}
```

### Step 6: Check Metrics

```bash
# Query Prometheus metrics
curl http://prometheus:9090/api/v1/query?query=lcm_lablet_instances_active

# Check scheduling decisions
curl http://prometheus:9090/api/v1/query?query=rate(lcm_scheduling_decisions_total[5m])

# Check scheduler loop duration
curl http://prometheus:9090/api/v1/query?query=lcm_scheduler_loop_duration_seconds
```

---

## Resolution Steps

### Resolution 1: Restart Scheduler

**When:** Scheduler appears hung or unresponsive

```bash
# Graceful restart
kubectl rollout restart deployment/resource-scheduler -n lcm

# Verify new pod is running
kubectl get pods -l app=resource-scheduler -n lcm -w

# Check logs for successful startup
kubectl logs -l app=resource-scheduler -n lcm --tail=50 | grep -i "started\|leader"
```

### Resolution 2: Force Leader Re-election

**When:** Leader election is stuck or leader pod is unhealthy

```bash
# Delete the leader key to force re-election
etcdctl del /lcm/scheduler/leader

# Wait for new leader to be elected (typically < 30 seconds)
sleep 30

# Verify new leader
etcdctl get /lcm/scheduler/leader
```

### Resolution 3: Clear Stuck Instances

**When:** Instances are stuck due to data inconsistency

```bash
# Find stuck instances
curl "http://control-plane-api:8080/api/instances?state=pending" | jq -r '.[] | select(.created_at < (now - 3600)) | .id'

# For each stuck instance, manually transition or terminate
curl -X POST "http://control-plane-api:8080/api/instances/{instance-id}/terminate"
```

### Resolution 4: Scale Up Workers Manually

**When:** Auto-scaling is not triggering

```bash
# Check current worker count
kubectl get pods -l app=cml-worker -n lcm | wc -l

# Trigger manual scale-up via API
curl -X POST "http://control-plane-api:8080/api/workers/scale-up" \
  -H "Content-Type: application/json" \
  -d '{"template_id": "default", "count": 2}'

# Or scale via kubectl
kubectl scale deployment/worker-controller --replicas=3 -n lcm
```

### Resolution 5: Recover etcd Connection

**When:** etcd is unreachable

```bash
# Check etcd pod status
kubectl get pods -l app=etcd -n lcm

# Restart etcd if needed
kubectl rollout restart statefulset/etcd -n lcm

# Verify cluster health after restart
etcdctl endpoint health --cluster

# Restart scheduler to reconnect
kubectl rollout restart deployment/resource-scheduler -n lcm
```

---

## Prevention

### Monitoring Alerts

Configure the following alerts in Prometheus:

```yaml
groups:
  - name: scheduler
    rules:
      - alert: SchedulerNotRunning
        expr: up{job="resource-scheduler"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Resource Scheduler is down"

      - alert: PendingInstancesHigh
        expr: lcm_lablet_instances_active{state="pending"} > 50
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High number of pending instances"

      - alert: SchedulerNoDecisions
        expr: rate(lcm_scheduling_decisions_total[10m]) == 0 and lcm_lablet_instances_active{state="pending"} > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Scheduler not making decisions despite pending instances"

      - alert: SchedulerLoopSlow
        expr: histogram_quantile(0.95, rate(lcm_scheduler_loop_duration_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Scheduler loop taking too long"
```

### Health Checks

Ensure proper health checks are configured:

```yaml
# Kubernetes liveness probe
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10

# Kubernetes readiness probe
readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5
```

---

## Escalation

### When to Escalate

- Issue persists after all resolution steps
- Multiple services affected
- Data loss or corruption suspected
- etcd cluster issues

### Escalation Path

1. **First Responder:** On-call Platform Engineer
2. **30 min:** Senior Platform Engineer
3. **1 hour:** Engineering Manager
4. **2 hours:** Director of Engineering

### Contact Information

| Role | Contact |
|------|---------|
| Platform Engineering | #platform-oncall |
| Database Team | #data-oncall |
| Security Team | #security-oncall |

---

## Related Runbooks

- [etcd Operations](./etcd-operations.md)
- [Instance Recovery](./instance-recovery.md)
- [Scaling Operations](./scaling-operations.md)
- [Worker Troubleshooting](./worker-troubleshooting.md)
