# Scenario Engine API

## Overview

The **Scenario Engine** executes pod automation scenarios against infrastructure adapters.
It provides a fire-and-forget job API for LCM services to submit automation work.

**Key Responsibilities:**

- 🚀 Execute automation jobs (scenarios) against infrastructure
- 📦 Manage PodDefinition content sync from BlobStorage
- 📋 Expose scenario registry for discovery
- 🔄 Report progress via CloudEvents callbacks

## Domain: Pod Automation (DSL Execution)

The Scenario Engine operates at the **automation layer**, managing:

- Job lifecycle (submitted → running → completed/failed/cancelled)
- DSL task execution (DAG ordering, jq expressions, retry, timeout)
- Adapter dispatch (CML/AWS, ROC/RADkit, Proxmox, VMWare)
- Content synchronization from BlobStorage (S3)

## Architecture

### Job Execution Model

Uses **fire-and-forget** pattern:

- Caller submits job with scenario name + input data
- SE returns job_id immediately (202 Accepted)
- SE executes scenario asynchronously
- Progress/completion reported via CloudEvents to callback URL

### Scenario Registry

Decorator-based auto-discovery at boot:

```python
@scenario(name="lab_resolve", version="v1")
class LabResolveScenario:
    ...
```

## Content Model

PodDefinitions synced on-demand:

- `DEFINED` → `SYNCHRONIZING` → `READY` → `EXPIRED` → `SUPERSEDED`
- Content stored locally after sync from BlobStorage
