# Scenario Engine — TODO

## Phase 1: Scaffold (Current)

- [x] Project structure (Makefile, pyproject.toml, Dockerfile, pytest.ini)
- [x] main.py with Neuroglia WebApplicationBuilder
- [x] API controllers (jobs, content, scenarios) — returning 501
- [x] Domain entities (Job, PodDefinition) with event sourcing
- [x] Scenario registry (@scenario decorator)
- [x] Repository interfaces
- [x] Unit tests for scenario registry

## Phase 2: Core Implementation

- [ ] Wire controllers to CQRS commands/queries via Mediator
- [ ] Implement MongoDB repositories (Motor)
- [ ] Job execution engine (async task runner)
- [ ] Content sync from BlobStorage (S3)
- [ ] CloudEvents callback for job completion

## Phase 3: DSL Runtime

- [ ] DSL parser (YAML → task DAG)
- [ ] jq expression evaluator (pyjq)
- [ ] Task executor with retry/timeout/skip_when
- [ ] Progress tracking and reporting

## Phase 4: Adapters

- [ ] CmlOnAwsAdapter (port from lablet-controller step handlers)
- [ ] RocRadkitAdapter (stub)
- [ ] ProxmoxAdapter (stub)
- [ ] VMWareAdapter (stub)

## Phase 5: First Scenarios

- [ ] lab_resolve@v1 — Resolve CML lab topology
- [ ] lab_start@v1 — Start a CML lab on a worker
- [ ] execute_command@v1 — Run commands on lab nodes
- [ ] collect_evidence@v1 — Collect grading evidence
