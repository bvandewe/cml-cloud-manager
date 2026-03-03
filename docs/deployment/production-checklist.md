# Production Deployment Checklist

## Overview

This checklist covers all steps required to deploy the Lablet Cloud Manager to production.
Complete each section in order and verify all items before proceeding.

---

## Pre-Deployment Verification

### Code Quality

- [ ] All unit tests passing (`make test` in each microservice)
- [ ] All integration tests passing (`pytest tests/integration/`)
- [ ] Linting passes (`make lint`)
- [ ] No security vulnerabilities in dependencies (`safety check`)
- [ ] UI assets built (`make build-ui` in control-plane-api)
- [ ] Version number updated in `pyproject.toml`
- [ ] CHANGELOG.md updated with release notes

### Docker Images

- [ ] Docker images build successfully (`docker build -t lablet-control-plane:v1.0.0 .`)
- [ ] Images tagged with version and `latest`
- [ ] Images pushed to container registry
- [ ] Image sizes reasonable (< 500MB)
- [ ] No hardcoded secrets in images

---

## Infrastructure Setup

### Kubernetes Cluster (if applicable)

- [ ] Cluster provisioned with sufficient resources
- [ ] Node pools configured (min 3 nodes for HA)
- [ ] Ingress controller installed (nginx-ingress or similar)
- [ ] Cert-manager configured for TLS
- [ ] PersistentVolume provisioner available

### MongoDB

- [ ] MongoDB cluster deployed (replica set or sharded)
- [ ] Authentication enabled
- [ ] TLS/SSL enabled for connections
- [ ] `otel_monitor` user created for observability
- [ ] Backups configured (daily snapshots)
- [ ] Connection string stored in secrets

```bash
# Create MongoDB user for app
mongosh <<EOF
use lablet_cloud_manager
db.createUser({
  user: "lablet_app",
  pwd: "<secure-password>",
  roles: [{role: "readWrite", db: "lablet_cloud_manager"}]
})
EOF
```

### Redis

- [ ] Redis cluster deployed (or managed Redis)
- [ ] Authentication enabled
- [ ] TLS enabled (optional but recommended)
- [ ] Memory limits configured
- [ ] Eviction policy set (allkeys-lru)

### Keycloak

- [ ] Keycloak deployed with HA configuration
- [ ] Admin credentials secured
- [ ] Realm imported (`lablet-cloud-manager` realm)
- [ ] Client configured with production URLs
- [ ] Identity provider configured (Cisco SSO)
- [ ] User groups and roles configured
- [ ] TLS certificate configured

---

## Security Configuration

### Secrets Management

- [ ] All secrets stored in Kubernetes Secrets or Vault
- [ ] No secrets in environment files or code
- [ ] Secret rotation schedule documented

Required secrets:

```yaml
# kubernetes-secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: lablet-secrets
type: Opaque
stringData:
  MONGODB_URI: "mongodb://user:pass@mongo:27017/lablet_cloud_manager"
  REDIS_URL: "redis://user:pass@redis:6379/0"
  KEYCLOAK_CLIENT_SECRET: "<client-secret>"
  AWS_ACCESS_KEY_ID: "<aws-key>"
  AWS_SECRET_ACCESS_KEY: "<aws-secret>"
```

### Network Security

- [ ] TLS certificates installed
- [ ] HTTPS enforced (redirect HTTP → HTTPS)
- [ ] Security headers configured in nginx/ingress
- [ ] CORS origins restricted to production domains
- [ ] Rate limiting enabled

### AWS IAM

- [ ] IAM role/user created with minimal permissions
- [ ] EC2 permissions limited to required actions
- [ ] CloudWatch permissions for metrics
- [ ] Resource tagging for cost allocation
- [ ] Access keys rotated

Required IAM permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:StartInstances",
        "ec2:StopInstances",
        "ec2:TerminateInstances",
        "ec2:CreateTags",
        "ec2:RunInstances"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {"ec2:ResourceTag/Environment": "production"}
      }
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricData",
        "cloudwatch:GetMetricStatistics"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Observability Setup

### OpenTelemetry Collector

- [ ] OTEL Collector deployed
- [ ] OTLP receiver configured (gRPC port 4317)
- [ ] Exporters configured:
  - [ ] Prometheus (metrics)
  - [ ] Tempo/Jaeger (traces)
  - [ ] Loki (logs)
- [ ] Resource detection enabled
- [ ] Sampling configured for high-volume traces

### Prometheus

- [ ] Prometheus deployed with adequate storage
- [ ] Scrape configs for:
  - [ ] Control Plane API metrics
  - [ ] MongoDB exporter
  - [ ] Redis exporter
  - [ ] Node exporter
- [ ] Alerting rules configured
- [ ] Recording rules for dashboards

### Grafana

- [ ] Grafana deployed with SSO integration
- [ ] Dashboards imported:
  - [ ] System Overview
  - [ ] Worker Health
  - [ ] Lablet Instance Metrics
  - [ ] API Performance
- [ ] Alert channels configured (PagerDuty, Slack)
- [ ] Data retention configured

### Logging

- [ ] Loki deployed for log aggregation
- [ ] Log shipping configured from all services
- [ ] Log retention policy set (30-90 days)
- [ ] Sensitive data scrubbed from logs

---

## Application Configuration

### Environment Variables

```bash
# Core
APP_NAME=lablet-cloud-manager
APP_ENV=production
APP_PORT=8000
LOG_LEVEL=INFO

# Database
MONGODB_URI=<from-secret>
REDIS_URL=<from-secret>

# Security
KEYCLOAK_URL=https://auth.example.com
KEYCLOAK_REALM=lablet-cloud-manager
KEYCLOAK_CLIENT_ID=lablet-cloud-manager
KEYCLOAK_CLIENT_SECRET=<from-secret>
SECURE_COOKIES=true
CORS_ALLOWED_ORIGINS=https://lablet.example.com

# AWS
AWS_REGION=us-west-2
AWS_ACCESS_KEY_ID=<from-secret>
AWS_SECRET_ACCESS_KEY=<from-secret>

# Observability
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_SERVICE_NAME=control-plane-api
```

### Replicas & Scaling

- [ ] Control Plane API: min 2 replicas
- [ ] Resource Scheduler: 1 replica (singleton)
- [ ] Worker Controller: 1 replica per region
- [ ] Lablet Controller: 2 replicas
- [ ] HPA configured for auto-scaling

---

## Deployment Steps

### 1. Database Migrations

```bash
# Verify MongoDB indexes exist
poetry run python -c "
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
async def check():
    client = AsyncIOMotorClient('$MONGODB_URI')
    db = client.lablet_cloud_manager
    for coll in await db.list_collection_names():
        indexes = await db[coll].index_information()
        print(f'{coll}: {list(indexes.keys())}')
asyncio.run(check())
"
```

### 2. Deploy Services

```bash
# Kubernetes
kubectl apply -f deployment/helm/lablet-cloud-manager/

# Docker Compose (simpler deployments)
docker-compose -f docker-compose.prod.yml up -d
```

### 3. Verify Deployment

```bash
# Health checks
curl https://lablet.example.com/api/diagnostics/health
curl https://lablet.example.com/api/diagnostics/ready

# Verify authentication
curl https://lablet.example.com/api/auth/login

# Check logs
kubectl logs -l app=control-plane-api --tail=100
```

### 4. Smoke Tests

- [ ] Can log in via Keycloak
- [ ] Workers list loads (even if empty)
- [ ] Lablet definitions list loads
- [ ] Health endpoint returns healthy
- [ ] SSE stream connects
- [ ] Metrics endpoint returns data

---

## Post-Deployment Verification

### Functional Tests

- [ ] User can authenticate via SSO
- [ ] Admin can view all workers
- [ ] Operator can start/stop workers
- [ ] User can create lablet instance
- [ ] Instance lifecycle works (schedule → running → terminate)
- [ ] Grading results are saved correctly
- [ ] SSE events are received in UI

### Performance Tests

- [ ] Response times < 200ms for list operations
- [ ] Response times < 500ms for create operations
- [ ] No memory leaks under load (24-hour soak test)
- [ ] Database queries use indexes (no collection scans)

### Observability Tests

- [ ] Traces appear in Tempo/Jaeger
- [ ] Metrics appear in Prometheus
- [ ] Logs appear in Loki
- [ ] Dashboards show real data
- [ ] Alerts fire when triggered (test alert)

---

## Rollback Plan

### Quick Rollback

```bash
# Kubernetes
kubectl rollout undo deployment/control-plane-api

# Docker Compose
docker-compose -f docker-compose.prod.yml up -d --force-recreate \
  --build-arg VERSION=<previous-version>
```

### Database Rollback

If database schema changed:

```bash
# Restore from backup
mongorestore --uri="$MONGODB_URI" --archive=backup-<date>.gz --gzip
```

### Rollback Triggers

Initiate rollback if:

- Error rate > 5% for 5 minutes
- P95 latency > 2 seconds for 10 minutes
- Health check failures > 3 consecutive
- Critical security vulnerability discovered

---

## Go-Live Checklist

### Final Verification

- [ ] All deployment steps completed
- [ ] Smoke tests passing
- [ ] Monitoring dashboards showing normal metrics
- [ ] On-call team briefed
- [ ] Runbooks reviewed and accessible
- [ ] Communication sent to stakeholders

### Documentation

- [ ] Release notes published
- [ ] API documentation updated
- [ ] Known issues documented
- [ ] Support contacts listed

### Sign-Off

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Engineering Lead | | | |
| QA Lead | | | |
| DevOps Lead | | | |
| Product Owner | | | |

---

## Appendix: Quick Commands

```bash
# View all pods
kubectl get pods -l app.kubernetes.io/name=lablet-cloud-manager

# View logs
kubectl logs -l app=control-plane-api -f

# Port forward for debugging
kubectl port-forward svc/control-plane-api 8000:8000

# Execute command in pod
kubectl exec -it deploy/control-plane-api -- /bin/bash

# Scale deployment
kubectl scale deployment/control-plane-api --replicas=3

# Check resource usage
kubectl top pods -l app=control-plane-api
```
