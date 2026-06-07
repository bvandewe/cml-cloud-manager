# Scenario Engine Service

The Scenario Engine is responsible for **pod automation execution** — running content-defined lifecycle scenarios against infrastructure adapters (CML/AWS, ROC/RADkit, Proxmox, VMWare).

## Domain: Pod Automation (DSL Execution)

The Scenario Engine operates at the **automation layer**, executing scenarios submitted by LCM services:

- **Job execution** — Fire-and-forget jobs with progress tracking and CloudEvents callbacks
- **DSL runtime** — ServerlessWorkflow-inspired task DAG with jq expression evaluation
- **Scenario registry** — Decorator-based auto-discovery of scenario implementations
- **Multi-adapter dispatch** — Infrastructure calls routed to appropriate adapter
- **Content management** — PodDefinition sync from BlobStorage (S3)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│               SCENARIO ENGINE - EXECUTION PATTERN                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐   │
│   │    SUBMIT JOB    │     │    EXECUTE DSL   │     │    CALLBACK      │   │
│   │   (from LCM)     │     │   (scenarios)    │     │  (CloudEvents)   │   │
│   └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘   │
│            │                        │                        │              │
│            ▼                        ▼                        ▼              │
│   ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐   │
│   │ Job              │     │ Scenario         │     │ CloudEvent       │   │
│   │ • scenario_name  │     │ • Task DAG       │     │ • job.completed  │   │
│   │ • input_data     │ →   │ • jq evaluation  │  →  │ • job.failed     │   │
│   │ • callback_url   │     │ • Adapter calls  │     │ • progress       │   │
│   └──────────────────┘     └──────────────────┘     └──────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/jobs` | Submit a new automation job |
| GET | `/api/v1/jobs/{job_id}` | Get job status and progress |
| DELETE | `/api/v1/jobs/{job_id}` | Cancel a running job |
| POST | `/api/v1/content/sync` | Trigger content sync from BlobStorage |
| GET | `/api/v1/content/{definition_id}` | Get synced content status |
| GET | `/api/v1/scenarios` | List available scenarios |
| GET | `/api/v1/scenarios/{name}/{ver}` | Get scenario details and schema |
| GET | `/healthz` | Health check |

## Architecture

- **ADR-044**: ScenarioEngine as a separate microservice
- **DSL Specification**: `docs/architecture/dsl/DSL-SPECIFICATION.md`
- **Neuroglia Framework**: CQRS, DI, HostedServices
- **Port**: 8004

## Development

```bash
make install      # Install dependencies
make build-ui     # Build frontend
make run          # Start locally
make test         # Run tests
make lint         # Lint check
```
