# Runbook: etcd Operations

| Attribute | Value |
|-----------|-------|
| **Version** | 1.0.0 |
| **Last Updated** | 2026-01-19 |
| **Severity Levels** | P1 (Critical), P2 (High), P3 (Medium) |
| **On-Call Escalation** | Platform Engineering |

---

## Overview

etcd is used by the Lablet Cloud Manager for:

- Scheduler leader election
- Instance state coordination
- Port allocation locking
- Cross-service state synchronization

This runbook covers common etcd operations and troubleshooting procedures.

---

## etcd Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    etcd Key Structure                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  /lcm/                                                      │
│  ├── scheduler/                                             │
│  │   └── leader          # Current scheduler leader         │
│  ├── instances/                                             │
│  │   └── {id}/                                             │
│  │       ├── state       # Instance state                   │
│  │       └── assignment  # Worker assignment                │
│  ├── workers/                                               │
│  │   └── {id}/                                             │
│  │       ├── state       # Worker state                     │
│  │       └── capacity    # Available capacity               │
│  └── ports/                                                 │
│      └── {port}          # Port allocation lease           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Common Operations

### Check Cluster Health

```bash
# Check endpoint health
etcdctl endpoint health

# Check cluster status
etcdctl endpoint status --cluster --write-out=table

# Check member list
etcdctl member list --write-out=table
```

### View Keys

```bash
# List all LCM keys
etcdctl get --prefix /lcm/ --keys-only

# Get scheduler leader
etcdctl get /lcm/scheduler/leader

# Get all instance states
etcdctl get --prefix /lcm/instances/ --print-value-only

# Get specific instance state
etcdctl get /lcm/instances/{instance-id}/state

# Count keys by prefix
etcdctl get --prefix /lcm/instances/ --count-only
```

### Manage Keys

```bash
# Set a key (for recovery purposes only)
etcdctl put /lcm/instances/{instance-id}/state "pending"

# Delete a key
etcdctl del /lcm/instances/{instance-id}/state

# Delete prefix (CAUTION: destructive)
etcdctl del --prefix /lcm/instances/{instance-id}/
```

### Watch Changes

```bash
# Watch all instance changes
etcdctl watch --prefix /lcm/instances/

# Watch scheduler leader changes
etcdctl watch /lcm/scheduler/leader

# Watch with timestamp
etcdctl watch --prefix /lcm/ --write-out=json | jq '.kv[].key | @base64d'
```

---

## Troubleshooting

### etcd Unreachable

**Severity:** P1 (Critical)

**Symptoms:**

- Services cannot connect to etcd
- Scheduler leader election failing
- State updates not persisting

**Diagnosis:**

```bash
# Check etcd pod status
kubectl get pods -l app=etcd -n lcm

# Check etcd logs
kubectl logs -l app=etcd -n lcm --tail=100

# Check network connectivity
kubectl exec -it deploy/control-plane-api -- nc -zv etcd 2379

# Check etcd service
kubectl get svc etcd -n lcm
kubectl describe svc etcd -n lcm
```

**Resolution:**

1. Restart etcd if pod is unhealthy:

   ```bash
   kubectl rollout restart statefulset/etcd -n lcm
   ```

2. Check resource limits:

   ```bash
   kubectl describe pod -l app=etcd -n lcm | grep -A5 "Limits\|Requests"
   ```

3. Check storage:

   ```bash
   kubectl exec -it etcd-0 -n lcm -- df -h /var/run/etcd
   ```

### Leader Election Stuck

**Severity:** P2 (High)

**Symptoms:**

- Scheduler not making decisions
- Multiple schedulers think they are leader
- Stale leader key

**Diagnosis:**

```bash
# Check current leader
etcdctl get /lcm/scheduler/leader --print-value-only

# Check lease associated with leader
etcdctl lease list

# Get lease details
etcdctl lease timetolive {lease-id}
```

**Resolution:**

1. Force re-election by deleting leader key:

   ```bash
   etcdctl del /lcm/scheduler/leader
   ```

2. Restart scheduler pods:

   ```bash
   kubectl rollout restart deploy/resource-scheduler -n lcm
   ```

3. Verify new leader:

   ```bash
   sleep 30
   etcdctl get /lcm/scheduler/leader
   ```

### High Latency

**Severity:** P3 (Medium)

**Symptoms:**

- Slow scheduling decisions
- High `lcm_etcd_operation_latency_seconds` metrics
- Timeouts in service logs

**Diagnosis:**

```bash
# Check etcd latency metrics
etcdctl endpoint status --cluster --write-out=json | jq '.[].Status.raftTerm'

# Check disk latency
kubectl exec -it etcd-0 -n lcm -- iostat -x 1 5

# Check network latency
kubectl exec -it etcd-0 -n lcm -- ping -c 5 etcd-1.etcd
```

**Resolution:**

1. Compact and defragment:

   ```bash
   # Get current revision
   REVISION=$(etcdctl endpoint status --write-out=json | jq -r '.[0].Status.header.revision')

   # Compact to revision
   etcdctl compact $REVISION

   # Defragment
   etcdctl defrag --cluster
   ```

2. Check and increase resources if needed:

   ```bash
   kubectl set resources statefulset/etcd -n lcm \
     --limits=cpu=2,memory=4Gi \
     --requests=cpu=500m,memory=1Gi
   ```

### Data Corruption

**Severity:** P1 (Critical)

**Symptoms:**

- etcd failing to start
- Checksum errors in logs
- Inconsistent reads

**Diagnosis:**

```bash
# Check for corruption in logs
kubectl logs -l app=etcd -n lcm | grep -i "corrupt\|checksum\|error"

# Check data directory
kubectl exec -it etcd-0 -n lcm -- ls -la /var/run/etcd/
```

**Resolution:**

1. Attempt to recover from snapshot:

   ```bash
   # List snapshots
   etcdctl snapshot ls

   # Restore from snapshot
   etcdctl snapshot restore /backup/etcd-snapshot.db \
     --data-dir /var/run/etcd/restored \
     --name etcd-0 \
     --initial-cluster etcd-0=https://etcd-0:2380
   ```

2. If no snapshot available, reinitialize (DATA LOSS):

   ```bash
   # WARNING: This will lose all etcd data
   kubectl delete pvc -l app=etcd -n lcm
   kubectl rollout restart statefulset/etcd -n lcm
   ```

3. After reinitialize, scheduler will need to resync state from MongoDB.

---

## Backup and Restore

### Create Snapshot

```bash
# Create snapshot
etcdctl snapshot save /tmp/etcd-snapshot-$(date +%Y%m%d).db

# Copy to safe location
kubectl cp etcd-0:/tmp/etcd-snapshot-$(date +%Y%m%d).db ./backups/

# Verify snapshot
etcdctl snapshot status ./backups/etcd-snapshot-*.db --write-out=table
```

### Scheduled Backups

Configure CronJob for automated backups:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-backup
  namespace: lcm
spec:
  schedule: "0 */4 * * *"  # Every 4 hours
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: bitnami/etcd:3.5
            command:
            - /bin/sh
            - -c
            - |
              etcdctl snapshot save /backup/snapshot-$(date +%Y%m%d-%H%M%S).db
            volumeMounts:
            - name: backup
              mountPath: /backup
          volumes:
          - name: backup
            persistentVolumeClaim:
              claimName: etcd-backups
          restartPolicy: OnFailure
```

### Restore from Snapshot

```bash
# Stop services using etcd
kubectl scale deploy/resource-scheduler --replicas=0 -n lcm
kubectl scale deploy/control-plane-api --replicas=0 -n lcm

# Restore snapshot
etcdctl snapshot restore /backup/etcd-snapshot.db \
  --data-dir /var/run/etcd/restored \
  --name etcd-0 \
  --initial-cluster etcd-0=https://etcd-0.etcd:2380

# Restart etcd with restored data
kubectl rollout restart statefulset/etcd -n lcm

# Wait for etcd to be ready
kubectl wait --for=condition=ready pod/etcd-0 -n lcm --timeout=120s

# Restart services
kubectl scale deploy/resource-scheduler --replicas=1 -n lcm
kubectl scale deploy/control-plane-api --replicas=1 -n lcm
```

---

## Maintenance Operations

### Compaction

Regular compaction prevents unbounded storage growth:

```bash
# Get current revision
REVISION=$(etcdctl endpoint status --write-out=json | jq -r '.[0].Status.header.revision')

# Compact to revision
etcdctl compact $REVISION

# Verify
etcdctl endpoint status --write-out=table
```

### Defragmentation

Run during maintenance windows:

```bash
# Defragment single member
etcdctl defrag

# Defragment entire cluster (one at a time internally)
etcdctl defrag --cluster
```

### Key Cleanup

Clean up orphaned keys:

```bash
# Find orphaned instance keys (instances not in MongoDB)
for key in $(etcdctl get --prefix /lcm/instances/ --keys-only); do
  instance_id=$(echo $key | cut -d'/' -f4)
  if ! curl -s "http://control-plane-api:8080/api/instances/$instance_id" | jq -e '.id' > /dev/null 2>&1; then
    echo "Orphaned key: $key"
    # Uncomment to delete:
    # etcdctl del "$key"
  fi
done
```

---

## Monitoring Alerts

```yaml
groups:
  - name: etcd
    rules:
      - alert: EtcdClusterUnavailable
        expr: up{job="etcd"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "etcd cluster is unavailable"

      - alert: EtcdHighLatency
        expr: histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "etcd write latency is high"

      - alert: EtcdDiskSpaceLow
        expr: etcd_server_quota_backend_bytes - etcd_mvcc_db_total_size_in_bytes < 100000000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "etcd disk space running low"

      - alert: EtcdNoLeader
        expr: etcd_server_has_leader == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "etcd cluster has no leader"

      - alert: EtcdHighNumberOfLeaderChanges
        expr: increase(etcd_server_leader_changes_seen_total[1h]) > 3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "etcd leader changing frequently"
```

---

## Related Runbooks

- [Scheduler Troubleshooting](./scheduler-troubleshooting.md)
- [Instance Recovery](./instance-recovery.md)
- [Disaster Recovery](./disaster-recovery.md)
