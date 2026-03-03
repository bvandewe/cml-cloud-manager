# Runbook: Scaling Operations

| Attribute | Value |
|-----------|-------|
| **Version** | 1.0.0 |
| **Last Updated** | 2026-01-19 |
| **Severity Levels** | P1 (Critical), P2 (High), P3 (Medium) |
| **On-Call Escalation** | Platform Engineering |

---

## Overview

This runbook covers scaling operations for CML workers, including:

- Manual scale-up and scale-down procedures
- Auto-scaling troubleshooting
- Capacity planning and monitoring
- Cost optimization through worker lifecycle management

---

## Scaling Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Scaling Components                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │  Scheduler  │───▶│   Worker    │───▶│    AWS      │     │
│  │  Service    │    │ Controller  │    │    EC2      │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│         │                  │                  │             │
│         │                  │                  │             │
│         ▼                  ▼                  ▼             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   etcd      │    │  MongoDB    │    │ CloudWatch  │     │
│  │  (state)    │    │  (data)     │    │  (metrics)  │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Manual Scale-Up

### When to Scale Up

- Pending instances queue is growing
- Scheduled capacity insufficient for upcoming timeslots
- Peak usage period approaching

### Scale-Up Procedure

#### Step 1: Assess Current Capacity

```bash
# Check current worker count and status
curl http://control-plane-api:8080/api/workers | jq 'group_by(.state) | map({state: .[0].state, count: length})'

# Check available templates
curl http://control-plane-api:8080/api/worker-templates | jq '.[] | {id, instance_type, max_labs_per_worker}'

# Check pending instances
curl http://control-plane-api:8080/api/instances?state=pending | jq 'length'
```

#### Step 2: Request Scale-Up

```bash
# Scale up with default template
curl -X POST "http://control-plane-api:8080/api/workers" \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": "default",
    "name": "manual-scaleup-001",
    "tags": {
      "ScaledBy": "manual",
      "Reason": "capacity-increase"
    }
  }'

# Scale up multiple workers
for i in {1..3}; do
  curl -X POST "http://control-plane-api:8080/api/workers" \
    -H "Content-Type: application/json" \
    -d "{
      \"template_id\": \"default\",
      \"name\": \"manual-scaleup-$(date +%Y%m%d)-$i\"
    }"
  sleep 5  # Avoid rate limiting
done
```

#### Step 3: Monitor Provisioning

```bash
# Watch worker status
watch -n 5 'curl -s http://control-plane-api:8080/api/workers | jq ".[] | select(.state == \"provisioning\") | {id, name, state}"'

# Check provisioning progress
curl http://control-plane-api:8080/api/workers?state=provisioning | jq '.[] | {id, name, created_at}'

# View EC2 console (if needed)
aws ec2 describe-instances --filters "Name=tag:ManagedBy,Values=lcm" --query 'Reservations[].Instances[].[InstanceId,State.Name,LaunchTime]' --output table
```

#### Step 4: Verify Worker Health

```bash
# Check worker is running
curl http://control-plane-api:8080/api/workers/{worker-id} | jq '{state, health: .health_status}'

# Verify CML API connectivity
curl http://control-plane-api:8080/api/workers/{worker-id}/health

# Confirm worker capacity is available
curl http://control-plane-api:8080/api/workers/{worker-id}/resources
```

---

## Manual Scale-Down

### When to Scale Down

- Low utilization (< 30% for extended period)
- Cost optimization required
- Workers in ERROR state that need replacement

### Scale-Down Procedure

#### Step 1: Identify Scale-Down Candidates

```bash
# Find idle workers (no active labs)
curl http://control-plane-api:8080/api/workers | jq '.[] | select(.active_labs == 0 and .state == "running") | {id, name, created_at}'

# Check worker utilization
curl http://control-plane-api:8080/api/workers | jq '.[] | {id, name, active_labs: .resources.active_labs, max_labs: .resources.max_labs}'

# Find workers with low utilization
curl http://control-plane-api:8080/api/workers | jq '.[] | select((.resources.active_labs / .resources.max_labs) < 0.3)'
```

#### Step 2: Drain Worker

Before terminating, ensure no active labs:

```bash
# Initiate drain (prevents new assignments)
curl -X POST "http://control-plane-api:8080/api/workers/{worker-id}/drain"

# Check drain status
curl http://control-plane-api:8080/api/workers/{worker-id} | jq '.state, .drain_status'

# Wait for active labs to complete or migrate
watch -n 10 'curl -s http://control-plane-api:8080/api/workers/{worker-id} | jq ".active_labs"'
```

#### Step 3: Stop or Terminate Worker

```bash
# Stop worker (preserves instance for later use)
curl -X POST "http://control-plane-api:8080/api/workers/{worker-id}/stop"

# OR terminate worker (destroys EC2 instance)
curl -X DELETE "http://control-plane-api:8080/api/workers/{worker-id}"

# Verify termination
curl http://control-plane-api:8080/api/workers/{worker-id} | jq '.state'
```

---

## Auto-Scaling Troubleshooting

### Auto-Scaling Not Triggering

**Symptoms:**

- Pending instances but no scale-up
- `lcm_scaling_actions_total` not increasing

**Diagnosis:**

```bash
# Check auto-scaling configuration
curl http://control-plane-api:8080/api/settings | jq '.auto_scaling'

# Verify scheduler is running
curl http://resource-scheduler:8080/health

# Check scaling decision logs
kubectl logs -l app=resource-scheduler | grep -i "scale\|capacity"
```

**Resolution:**

1. Verify auto-scaling is enabled:

   ```bash
   curl -X PATCH "http://control-plane-api:8080/api/settings" \
     -H "Content-Type: application/json" \
     -d '{"auto_scaling_enabled": true}'
   ```

2. Check scaling thresholds:

   ```bash
   # Current thresholds
   curl http://control-plane-api:8080/api/settings | jq '.scaling_threshold_percent, .min_workers, .max_workers'

   # Adjust if needed
   curl -X PATCH "http://control-plane-api:8080/api/settings" \
     -H "Content-Type: application/json" \
     -d '{"scaling_threshold_percent": 70, "max_workers": 10}'
   ```

3. Check AWS limits:

   ```bash
   # EC2 instance limits
   aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A

   # Current instance count
   aws ec2 describe-instances --filters "Name=tag:ManagedBy,Values=lcm" "Name=instance-state-name,Values=running" --query 'length(Reservations[].Instances[])'
   ```

### Workers Scaling Too Aggressively

**Symptoms:**

- High AWS costs
- Workers created but underutilized
- Frequent scale-up/scale-down cycles

**Resolution:**

```bash
# Increase scale-down cooldown
curl -X PATCH "http://control-plane-api:8080/api/settings" \
  -H "Content-Type: application/json" \
  -d '{"scale_down_cooldown_minutes": 30}'

# Adjust utilization thresholds
curl -X PATCH "http://control-plane-api:8080/api/settings" \
  -H "Content-Type: application/json" \
  -d '{
    "scale_up_threshold_percent": 80,
    "scale_down_threshold_percent": 20
  }'

# Set minimum worker count
curl -X PATCH "http://control-plane-api:8080/api/settings" \
  -H "Content-Type: application/json" \
  -d '{"min_workers": 2}'
```

---

## Capacity Planning

### Viewing Current Capacity

```bash
# Total capacity
curl http://control-plane-api:8080/api/workers | jq '{
  total_workers: length,
  running_workers: [.[] | select(.state == "running")] | length,
  total_lab_capacity: [.[].resources.max_labs] | add,
  used_lab_capacity: [.[].resources.active_labs] | add,
  available_capacity: ([.[].resources.max_labs] | add) - ([.[].resources.active_labs] | add)
}'

# Per-worker capacity
curl http://control-plane-api:8080/api/workers | jq '.[] | {
  id,
  name,
  state,
  max_labs: .resources.max_labs,
  active_labs: .resources.active_labs,
  utilization_pct: ((.resources.active_labs / .resources.max_labs) * 100)
}' | jq -s 'sort_by(.utilization_pct) | reverse'
```

### Forecasting Needs

```bash
# Upcoming scheduled instances
curl "http://control-plane-api:8080/api/instances?state=scheduled" | jq 'group_by(.timeslot_start[:10]) | .[] | {date: .[0].timeslot_start[:10], count: length}'

# Peak usage times
curl http://prometheus:9090/api/v1/query_range \
  --data-urlencode 'query=max_over_time(lcm_lablet_instances_active[24h])' \
  --data-urlencode 'start=now-7d' \
  --data-urlencode 'end=now' \
  --data-urlencode 'step=1h' | jq '.data.result'
```

---

## Cost Optimization

### Scheduled Scaling

Configure scheduled scale-up/down for predictable patterns:

```bash
# Add scheduled scale-up for business hours
curl -X POST "http://control-plane-api:8080/api/scheduled-scaling" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "business-hours-scale-up",
    "cron": "0 8 * * 1-5",
    "action": "scale_up",
    "target_count": 5
  }'

# Add scheduled scale-down for nights
curl -X POST "http://control-plane-api:8080/api/scheduled-scaling" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "night-scale-down",
    "cron": "0 20 * * 1-5",
    "action": "scale_down",
    "target_count": 1
  }'
```

### Reserved Instances / Savings Plans

For predictable base capacity, use AWS Reserved Instances or Savings Plans for the minimum worker count.

---

## Monitoring Alerts

```yaml
groups:
  - name: scaling
    rules:
      - alert: HighWorkerUtilization
        expr: (sum(lcm_lablet_instances_active{state="running"}) / sum(lcm_workers_active{state="running"} * 5)) > 0.9
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Worker utilization above 90%"

      - alert: NoAvailableCapacity
        expr: sum(lcm_workers_active{state="running"}) == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "No running workers available"

      - alert: ScaleUpFailing
        expr: increase(lcm_scaling_actions_total{action="scale_up_failed"}[1h]) > 3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Scale-up operations failing repeatedly"

      - alert: WorkerProvisioningStuck
        expr: lcm_workers_active{state="provisioning"} > 0 and time() - lcm_worker_state_transitions_total{to_state="provisioning"} > 600
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Workers stuck in provisioning state"
```

---

## Related Runbooks

- [Scheduler Troubleshooting](./scheduler-troubleshooting.md)
- [Worker Troubleshooting](./worker-troubleshooting.md)
- [Instance Recovery](./instance-recovery.md)
- [AWS Operations](./aws-operations.md)
